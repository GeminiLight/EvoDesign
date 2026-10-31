"""Architecture design-system tool: executes agent decisions deterministically.

The agents keep their roles from the method: Structure decides components,
roles, sublabels and icons; Style assigns a palette family to every node;
Layout decides the tier plan (which node sits in which column, in which order,
and what forms the bottom row). This tool turns those decisions into canvas
geometry with one fixed visual treatment, the way the shape-size estimator
turns text into exact node sizes:

* Card: icon + title + muted sublabel, one width for all cards.
* Colour treatment: the style agent's family becomes a light fill, a mid
  stroke and a dark ink for the icon and outgoing connectors.
* Tier plan: columns left to right, data/infrastructure as a bottom row.
* Orthogonal routing: edges across a column gap share one trunk and edges
  into the bottom row share one bus.

Missing or invalid agent decisions fall back to role-derived defaults; scenes
it cannot place are returned unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from evo_diagram.agentic_system.common.node_icons import CARD_KEY, ICON_KEY, bundled_icons, icon_file
from evo_diagram.agentic_system.common.semantic_ids import (
    BACKGROUND_SUFFIX,
    TITLE_SUFFIX,
    group_frame_render_id,
)
from evo_diagram.agentic_system.common.spec_utils import unwrap_structure_instantiation
from evo_diagram.agentic_system.render_engine.shared.order_keys import sequential_index

logger = logging.getLogger(__name__)

_ARCHITECTURE_TYPES = {"architecture", "architecture_diagram"}
_MAX_NODES = 14

_FONT = 2
_TITLE_SIZE = 20
_SUBLABEL_SIZE = 14
_LINE_HEIGHT = 1.25
_TITLE_INK = "#1F2937"
_SUBLABEL_INK = "#6B7280"

_PAD_X = 22
_ICON = 36
_ICON_GAP = 16
_MIN_CARD_W = 220
_MAX_CARD_W = 380
_CARD_H = 84
_CARD_H_NO_SUB = 64

_COL_GAP = 120
_ROW_GAP = 36
_BOTTOM_GAP = 56
_BUS_DROP = 48
_SIDE_CORRIDOR = 24
_MAX_BOTTOM = 5
_MAX_COLUMN = 5
_ORIGIN = (80.0, 80.0)

# Fallback (fill, stroke, ink) when the style agent assigned no usable colour.
# Ink colours the icon and every connector leaving the card.
_HUES = {
    "blue": ("#EAF2FD", "#9DC1EE", "#2F6BD0"),
    "violet": ("#F1EEFD", "#BDAEF2", "#6A4FD6"),
    "green": ("#E8F6EF", "#97D2B5", "#1F9467"),
    "orange": ("#FFF4E5", "#F2C47F", "#D9822B"),
    "teal": ("#E6F5F7", "#93CFD6", "#14838C"),
    "rose": ("#FDEEF2", "#EFB2C2", "#C2456A"),
    "gray": ("#F4F5F7", "#C5CAD3", "#4B5563"),
}
_SERVICE_HUES = ["green", "blue", "orange", "teal", "rose"]

# Canonical role -> (tier, hue, default icon). Tiers: -1 people, 0 clients,
# 1 gateways, 2 services, 3 side systems (right column), 4 bottom row.
_ROLES = {
    "actor": (-1, "gray", "outline_users"),
    "client": (0, "blue", "outline_monitor"),
    "gateway": (1, "violet", "outline_network"),
    "service": (2, None, "outline_boxes"),
    "worker": (2, None, "outline_workflow"),
    "model": (3, "rose", "outline_brain"),
    "external": (3, "gray", "outline_cloud"),
    "database": (4, "violet", "outline_database"),
    "cache": (4, "green", "outline_layers"),
    "queue": (4, "blue", "outline_radio"),
    "storage": (4, "orange", "outline_hard_drive"),
    "search": (4, "teal", "outline_search"),
    "observability": (4, "orange", "outline_activity"),
}

# Name keywords are checked before the coarse ``role``/``class`` tokens, in this
# order, because names like "MQTT 接入网关" or "Flink 流处理服务" carry the role.
_ENTRY_ROLES = {"client", "gateway"}
_BACKEND_ROLES = {"service", "worker", "database", "cache", "queue", "storage", "search", "observability"}

_NAME_ROLES = [
    ("gateway", ("gateway", "网关", "nginx", "load balanc", "负载均衡", "ingress", "反向代理", "cdn",
                 "waf", "cloudflare", "akamai")),
    ("database", ("mysql", "postgres", "mongo", "database", "数据库", "influx", "时序", "milvus",
                  "vector", "向量", "clickhouse", "oracle", "sqlite", "hbase", "dynamo", "warehouse")),
    ("cache", ("redis", "cache", "缓存", "memcache")),
    ("search", ("elasticsearch", "elastic", "opensearch", "solr", "搜索引擎", "search engine")),
    ("storage", ("oss", "s3", "object stor", "对象存储", "blob", "minio", "文件存储", "hdfs")),
    ("queue", ("kafka", "rabbit", "queue", "队列", "消息", "pulsar", "nats", "event bus", "broker")),
    ("observability", ("prometheus", "monitoring", "logging", "监控", "日志", "tracing")),
    ("model", ("llm", "大模型", "language model", "gpt", "模型")),
    ("external", ("third-party", "third party", "第三方", "provider", "sms", "短信", "企业微信",
                  "钉钉", "email", "邮件", "stripe", "支付宝")),
    ("worker", ("pipeline", "流水线", "flink", "spark", "etl", "worker", "批处理", "流处理",
                "consumer", "scheduler", "定时")),
    ("service", ("service", "服务", "server", "backend", "后端", "engine", "orchestr", "编排", "api")),
    ("client", ("web", "app", "mobile", "browser", "浏览器", "h5", "小程序", "portal", "interface",
                "界面", "前端", "frontend", "client", "客户端", "dashboard", "看板", "grafana",
                "device", "设备", "console", "控制台")),
    ("actor", ("user", "用户", "人员", "老师", "学生", "customer", "客户", "运维", "admin",
               "operator", "engineer", "person", "people")),
]

_ROLE_ALIASES = [
    ("observab", "observability"), ("monitor", "observability"),
    ("actor", "actor"), ("person", "actor"), ("client", "client"), ("user", "actor"),
    ("frontend", "client"),
    ("gateway", "gateway"), ("proxy", "gateway"), ("load_balancer", "gateway"),
    ("cache", "cache"), ("queue", "queue"), ("message", "queue"), ("bus", "queue"),
    ("broker", "queue"), ("search", "search"), ("vector", "database"), ("database", "database"),
    ("storage", "storage"), ("store", "storage"), ("model", "model"), ("llm", "model"),
    ("external", "external"), ("third", "external"), ("worker", "worker"), ("pipeline", "worker"),
    ("service", "service"), ("api", "service"),
]

# Keyword -> icon, matched against the label when the structure stage gave no icon.
_ICON_KEYWORDS = [
    (("web", "browser", "h5", "网页", "浏览器", "portal", "门户"), "outline_globe"),
    (("app", "mobile", "ios", "android", "手机", "小程序", "移动"), "outline_smartphone"),
    (("gateway", "网关", "nginx", "load balanc", "负载"), "outline_network"),
    (("老师", "学生", "人员", "users", "people", "team"), "outline_users"),
    (("user", "account", "member", "用户", "会员", "账号", "customer", "客户"), "outline_user"),
    (("order", "订单"), "outline_file_text"),
    (("pay", "支付", "billing", "账单"), "outline_credit_card"),
    (("notif", "通知", "推送", "sms", "短信", "alert", "告警"), "outline_bell"),
    (("search", "搜索", "elastic"), "outline_search"),
    (("cache", "redis", "缓存"), "outline_layers"),
    (("kafka", "mq", "queue", "队列", "消息", "mqtt", "rabbit"), "outline_radio"),
    (("oss", "s3", "object", "对象存储", "文件"), "outline_hard_drive"),
    (("mysql", "postgres", "mongo", "database", "数据库", "influx", "时序", "milvus", "向量"),
     "outline_database"),
    (("llm", "gpt", "大模型", "模型", "model"), "outline_brain"),
    (("grafana", "dashboard", "看板", "monitor", "监控"), "outline_chart_column"),
    (("flink", "spark", "stream", "流处理", "pipeline", "流水线", "etl"), "outline_workflow"),
    (("dispatch", "调度", "rider", "courier", "骑手", "配送"), "outline_truck"),
    (("course", "课程", "作业", "homework"), "outline_file_text"),
    (("live", "直播", "video", "视频"), "outline_video"),
    (("chat", "聊天", "对话"), "outline_message_square"),
    (("device", "设备", "sensor", "传感"), "outline_cpu"),
    (("auth", "认证", "登录", "security", "安全"), "outline_shield"),
    (("merchant", "商家", "restaurant", "餐厅", "store", "店"), "outline_store"),
    (("wechat", "企业微信", "微信", "mail", "邮件"), "outline_send"),
]


def is_enabled() -> bool:
    return os.getenv("EVODESIGN_ARCH_DESIGN_SYSTEM", "1").strip().lower() not in {"0", "false", "no", "off"}


def _canonical_role(node: Dict[str, Any]) -> str:
    declared = str(node.get("role") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if declared in _ROLES:
        return declared
    name = f"{node.get('label', '')} {node.get('id', '')}".lower()
    for role, words in _NAME_ROLES:
        if any(word in name for word in words):
            return role
    for key in ("role", "class", "type", "kind"):
        token = str(node.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
        for needle, role in _ROLE_ALIASES:
            if needle in token:
                return role
    return "service"


def _hex(value: Any) -> Optional[Tuple[int, int, int]]:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError:
        return None


def _mix(color: Tuple[int, int, int], weight: float) -> str:
    """Blend ``color`` toward white by ``weight`` (0 keeps it, 1 is white)."""
    return "#" + "".join(f"{round(c + (255 - c) * weight):02X}" for c in color)


def _card_colors(card: "_Card", styling: Dict[str, Any]) -> Tuple[Tuple[str, str, str], str]:
    """Map the style agent's family onto the card treatment, else the role fallback."""
    fill, stroke = _hex(styling.get("backgroundColor")), _hex(styling.get("strokeColor"))
    if fill and stroke:
        luminance = (0.299 * stroke[0] + 0.587 * stroke[1] + 0.114 * stroke[2]) / 255
        ink = stroke if luminance < 0.62 else tuple(round(c * 0.55) for c in stroke)
        return (_mix(fill, 0.55), _mix(stroke, 0.5), _mix(ink, 0)), "style_agent"
    return _HUES[card.hue], "fallback"


def _text_width(text: str, size: float) -> float:
    width = 0.0
    for ch in text:
        if unicodedata.east_asian_width(ch) in {"W", "F"}:
            width += size
        elif ch.isupper():
            width += size * 0.66
        elif ch == " ":
            width += size * 0.3
        else:
            width += size * 0.55
    return width


def _pick_icon(node: Dict[str, Any], role: str) -> str:
    catalog = bundled_icons()
    hinted = str(node.get("icon") or "").strip()
    if hinted.startswith("outline_") and hinted in catalog:
        return hinted
    haystack = f"{node.get('label', '')} {node.get('sublabel', '')} {node.get('id', '')}".lower()
    for needles, name in _ICON_KEYWORDS:
        if any(needle in haystack for needle in needles):
            return name
    return _ROLES[role][2]


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:20]


def _label_parts(node: Dict[str, Any]) -> Tuple[str, str]:
    title = str(node.get("label") or node.get("id") or "").strip()
    sublabel = str(node.get("sublabel") or node.get("description") or "").strip()
    if not sublabel and "\n" in title:
        title, sublabel = (part.strip() for part in title.split("\n", 1))
    return title, sublabel.replace("\n", " ")


class _Card:
    def __init__(self, node: Dict[str, Any], role: str):
        self.node = node
        self.id = str(node["id"])
        self.role = role
        self.tier = _ROLES[role][0]
        self.title, self.sublabel = _label_parts(node)
        self.icon = _pick_icon(node, role)
        self.hue = _ROLES[role][1] or "green"
        self.colors: Tuple[str, str, str] = _HUES[self.hue]
        self.x = self.y = 0.0
        self.w = self.h = 0.0
        self.col: Optional[int] = None
        self.row = 0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def _assign_service_hues(cards: List[_Card]) -> None:
    index = 0
    for card in cards:
        if _ROLES[card.role][1] is None:
            card.hue = _SERVICE_HUES[index % len(_SERVICE_HUES)]
            index += 1


def _barycenter_order(group: List[_Card], neighbours: Dict[str, List[str]],
                      cards: Dict[str, _Card], axis: str) -> List[_Card]:
    def key(item: Tuple[int, _Card]) -> Tuple[float, int]:
        position, card = item
        coords = [getattr(cards[n], axis) for n in neighbours.get(card.id, []) if n in cards
                  and cards[n] is not card and (cards[n].col != card.col or card.col is None)]
        return (sum(coords) / len(coords) if coords else float("inf"), position)
    return [card for _, card in sorted(enumerate(group), key=key)]


def _plan_from_spec(layout_specification: Any, cards: List[_Card]
                    ) -> Optional[Tuple[List[List[_Card]], List[_Card]]]:
    """Read the layout agent's tier plan; ``None`` unless it is complete and coherent."""
    plan = None
    if isinstance(layout_specification, dict):
        plan = layout_specification.get("tier_plan")
        blueprint = layout_specification.get("pattern_specific_layout_blueprint")
        if plan is None and isinstance(blueprint, dict):
            plan = blueprint.get("tier_plan")
    if not isinstance(plan, dict):
        return None
    by_id = {c.id: c for c in cards}
    raw_columns = plan.get("columns")
    raw_bottom = plan.get("bottom_row") or []
    if not isinstance(raw_columns, list) or not isinstance(raw_bottom, list):
        return None
    columns = [[by_id.get(str(i)) for i in col] for col in raw_columns if isinstance(col, list) and col]
    bottom = [by_id.get(str(i)) for i in raw_bottom]
    placed = [c for col in columns for c in col] + bottom
    if not columns or None in placed or len(placed) != len(cards) or len({id(c) for c in placed}) != len(cards):
        return None
    # A column is one vertical stack of a single tier. Entry-side cards
    # (clients, gateways) stacked with back-end cards means the plan was read
    # as rows; executing it would scramble the request flow.
    for column in columns:
        roles = {c.role for c in column}
        if roles & _ENTRY_ROLES and roles & _BACKEND_ROLES:
            logger.info("[ArchDesignSystem] tier plan mixes entry and back-end roles in one column; using roles")
            return None
    return columns, bottom


def _layout(cards: List[_Card], edges: List[Tuple[str, str]],
            plan: Optional[Tuple[List[List[_Card]], List[_Card]]] = None) -> None:
    by_id = {card.id: card for card in cards}
    width = max(_MIN_CARD_W, min(_MAX_CARD_W, max(
        _PAD_X * 2 + _ICON + _ICON_GAP
        + max(_text_width(c.title, _TITLE_SIZE), _text_width(c.sublabel, _SUBLABEL_SIZE))
        for c in cards)))
    height = _CARD_H if any(c.sublabel for c in cards) else _CARD_H_NO_SUB
    for card in cards:
        card.w, card.h = width, height

    neighbours: Dict[str, List[str]] = {}
    for source, target in edges:
        neighbours.setdefault(source, []).append(target)
        neighbours.setdefault(target, []).append(source)
    # People who only receive from back-end tiers (alert recipients, report
    # readers) join the side-system column instead of standing before clients.
    for card in cards if not plan else []:
        if card.role == "actor":
            near = [by_id[n].tier for n in neighbours.get(card.id, []) if n in by_id]
            if near and min(near) >= 2:
                card.tier = 3

    if plan:
        columns, bottom = [list(col) for col in plan[0]], list(plan[1])
    else:
        tiers = sorted({c.tier for c in cards if c.tier < 4})
        columns = [[c for c in cards if c.tier == tier] for tier in tiers]
        bottom = [c for c in cards if c.tier == 4]
    _orient_columns(columns, edges)
    _move_backward_sinks(columns, edges)
    _split_tall_columns(columns, edges)
    _spill_bottom_chains(columns, bottom, edges)

    def place_columns() -> None:
        heights = [len(col) * height + (len(col) - 1) * _ROW_GAP for col in columns]
        main_h = max(heights, default=0)
        for index, col in enumerate(columns):
            top = _ORIGIN[1] + (main_h - heights[index]) / 2
            for row, card in enumerate(col):
                card.col, card.row = index, row
                card.x = _ORIGIN[0] + index * (width + _COL_GAP)
                card.y = top + row * (height + _ROW_GAP)

    def place_bottom() -> None:
        main_cards = [c for col in columns for c in col]
        main_left = min((c.x for c in main_cards), default=_ORIGIN[0])
        main_right = max((c.right for c in main_cards), default=_ORIGIN[0] + width)
        main_bottom = max((c.bottom for c in main_cards), default=_ORIGIN[1] - _BUS_DROP * 2)
        row_w = len(bottom) * width + (len(bottom) - 1) * _BOTTOM_GAP
        left = max(_ORIGIN[0], (main_left + main_right) / 2 - row_w / 2)
        for index, card in enumerate(bottom):
            card.col, card.row = None, index
            card.x = left + index * (width + _BOTTOM_GAP)
            card.y = main_bottom + _BUS_DROP * 2

    place_columns()
    place_bottom()
    if plan:
        return
    # One barycentre pass reduces crossings without fighting the tier template.
    columns[:] = [_barycenter_order(col, neighbours, by_id, "cy") for col in columns]
    bottom[:] = _barycenter_order(bottom, neighbours, by_id, "cx")
    place_columns()
    place_bottom()


def _orient_columns(columns: List[List[_Card]], edges: List[Tuple[str, str]]) -> None:
    """Mirror a plan whose flow runs right to left; the agent's grouping is kept."""
    column_of = {c.id: index for index, col in enumerate(columns) for c in col}
    forward = backward = 0
    for source, target in edges:
        if source in column_of and target in column_of:
            step = column_of[target] - column_of[source]
            forward += step > 0
            backward += step < 0
    if backward > forward:
        logger.info("[ArchDesignSystem] tier plan flows right to left (%d vs %d); mirroring", backward, forward)
        columns.reverse()


def _move_backward_sinks(columns: List[List[_Card]], edges: List[Tuple[str, str]]) -> None:
    """Move an output that only receives from columns to its right after its sources.

    An "editable diagram", a report reader or an alert recipient is the end of
    the flow; drawn before the clients it sends every arrow backwards.
    """
    column_of = {c.id: index for index, col in enumerate(columns) for c in col}
    moved: List[_Card] = []
    for index, col in enumerate(columns):
        for card in list(col):
            incoming = [column_of[s] for s, t in edges if t == card.id and s in column_of]
            outgoing = [t for s, t in edges if s == card.id and t in column_of]
            if incoming and not outgoing and min(incoming) > index and len(col) > 1:
                col.remove(card)
                moved.append(card)
    if moved:
        logger.info("[ArchDesignSystem] moving end-of-flow nodes %s to a last column", [c.id for c in moved])
        columns.append(moved)


def _split_tall_columns(columns: List[List[_Card]], edges: List[Tuple[str, str]]) -> None:
    """Unstack a column taller than the budget, usually a whole pipeline in one stack.

    Nodes are layered by their longest path over the column's own edges, so a
    chain of stages reads left to right; without inner edges the column is
    cut into even chunks in the planned order.
    """
    index = 0
    while index < len(columns):
        column = columns[index]
        if len(column) <= _MAX_COLUMN:
            index += 1
            continue
        ids = {c.id for c in column}
        inner = [(s, t) for s, t in edges if s in ids and t in ids and s != t]
        depth = {c.id: 0 for c in column}
        for _ in column:
            for source, target in inner:
                depth[target] = max(depth[target], min(depth[source] + 1, len(column)))
        layers = [[c for c in column if depth[c.id] == d] for d in sorted(set(depth.values()))]
        if len(layers) < 2 or max(len(layer) for layer in layers) > _MAX_COLUMN:
            parts = -(-len(column) // _MAX_COLUMN)
            size = -(-len(column) // parts)
            layers = [column[i:i + size] for i in range(0, len(column), size)]
        logger.info("[ArchDesignSystem] column of %d split into %s", len(column), [len(l) for l in layers])
        columns[index:index + 1] = layers
        index += len(layers)


def _spill_bottom_chains(columns: List[List[_Card]], bottom: List[_Card],
                         edges: List[Tuple[str, str]]) -> None:
    """Keep the bottom row readable by moving its downstream chains to a last column.

    Nodes fed by another bottom-row node (a warehouse behind a queue, a batch
    job behind the warehouse, an alert channel behind monitoring) are a flow,
    not shared infrastructure; stretched along the bottom row they make the
    canvas several times wider than tall.
    """
    if len(bottom) <= _MAX_BOTTOM:
        return
    ids = {c.id for c in bottom}
    fed = {t for s, t in edges if s in ids and t in ids and s != t}
    moved = [c for c in bottom if c.id in fed]
    if not moved or len(moved) == len(bottom) or len(moved) > _MAX_BOTTOM:
        return
    logger.info("[ArchDesignSystem] bottom row has %d nodes; moving chain %s to a last column",
                len(bottom), [c.id for c in moved])
    columns.append(moved)
    bottom[:] = [c for c in bottom if c.id not in fed]


Point = Tuple[float, float]


def _canonical(src: _Card, dst: _Card) -> Tuple[_Card, _Card, bool]:
    """Order endpoints so routing always runs left->right, top->bottom, main->bottom row."""
    if (src.col is None and dst.col is not None) \
            or (src.col is not None and dst.col is not None and src.col > dst.col) \
            or (src.col is None and dst.col is None and src.x > dst.x) \
            or (src.col is not None and src.col == dst.col and src.y > dst.y):
        return dst, src, True
    return src, dst, False


class _Router:
    """Orthogonal router for the tier template.

    Edges crossing the same column gap share one vertical trunk, and every
    edge into the bottom row shares one horizontal bus, as in hand-drawn
    reference diagrams. Separate per-connection-set lanes were evaluated and
    scored lower: the extra parallel strokes read as clutter.
    """

    def __init__(self, cards: List[_Card], pairs: List[Tuple[str, str]]):
        self.cards = cards
        by_id = {c.id: c for c in cards}
        self.columns = sorted({c.col for c in cards if c.col is not None})
        self.col_x = {col: min(c.x for c in cards if c.col == col) for col in self.columns}
        self.last_col = max(self.columns, default=-1)
        self.canon = {pair: _canonical(by_id[pair[0]], by_id[pair[1]]) for pair in pairs}

    def _blocked(self, points: List[Point], skip: Tuple[_Card, ...]) -> bool:
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            lo_x, hi_x, lo_y, hi_y = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
            for card in self.cards:
                if card in skip:
                    continue
                if lo_x < card.right - 1 and hi_x > card.x + 1 and lo_y < card.bottom - 1 and hi_y > card.y + 1:
                    return True
        return False

    def route(self, source: str, target: str) -> List[Point]:
        a, b, reverse = self.canon[(source, target)]
        cards = self.cards
        if a.col is not None and b.col is not None and a.col != b.col:
            trunk_x = self.col_x[b.col] - _COL_GAP / 2
            port_y = b.cy
            path = [(a.right, a.cy), (trunk_x, a.cy), (trunk_x, port_y), (b.x, port_y)]
            if self._blocked(path, (a, b)):
                top = min(c.y for c in cards if c.col is not None) - _BUS_DROP
                exit_x = self.col_x[a.col] + a.w + _COL_GAP / 2
                path = [(a.right, a.cy), (exit_x, a.cy), (exit_x, top), (trunk_x, top),
                        (trunk_x, port_y), (b.x, port_y)]
        elif a.col is not None and b.col is not None:
            if b.row - a.row == 1:
                path = [(a.cx, a.bottom), (b.cx, b.y)]
            else:
                side = a.right + _SIDE_CORRIDOR
                path = [(a.right, a.cy), (side, a.cy), (side, b.cy), (b.right, b.cy)]
        elif a.col is not None:
            bus_y = b.y - 32
            drop_x = b.cx
            if not any(o.col == a.col and o.row > a.row for o in cards):
                path = [(a.cx, a.bottom), (a.cx, bus_y), (drop_x, bus_y), (drop_x, b.y)]
            else:
                on_right = a.col == self.last_col
                port = a.right if on_right else a.x
                side = a.right + _SIDE_CORRIDOR if on_right else a.x - _SIDE_CORRIDOR
                path = [(port, a.cy), (side, a.cy), (side, bus_y), (drop_x, bus_y), (drop_x, b.y)]
        else:
            if b.row - a.row == 1:
                path = [(a.right, a.cy), (b.x, b.cy)]
            else:
                low = max(c.bottom for c in cards) + _BUS_DROP / 2
                path = [(a.cx, a.bottom), (a.cx, low), (b.cx, low), (b.cx, b.bottom)]

        compact: List[Point] = []
        for point in path:
            if compact and abs(compact[-1][0] - point[0]) < 0.5 and abs(compact[-1][1] - point[1]) < 0.5:
                continue
            compact.append(point)
        return list(reversed(compact)) if reverse else compact


def _text_element(element_id: str, text: str, size: float, color: str, x: float, y: float,
                  group_ids: List[str], index: str) -> Dict[str, Any]:
    return {
        "id": element_id, "type": "text", "x": x, "y": y,
        "width": _text_width(text, size), "height": size * _LINE_HEIGHT,
        "angle": 0, "strokeColor": color, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0,
        "opacity": 100, "groupIds": group_ids, "frameId": None, "roundness": None,
        "index": index, "seed": int(element_id[:8], 16), "version": 1, "versionNonce": 1,
        "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False,
        "text": text, "originalText": text, "fontSize": size, "fontFamily": _FONT,
        "textAlign": "left", "verticalAlign": "top", "containerId": None,
        "autoResize": True, "lineHeight": _LINE_HEIGHT,
    }


def apply_architecture_design_system(manifest: Dict[str, Any],
                                     structure_instantiation: Any,
                                     layout_instantiation: Optional[Dict[str, Any]] = None,
                                     layout_specification: Optional[Dict[str, Any]] = None,
                                     ) -> Dict[str, Any]:
    """Execute the agents' architecture decisions on the manifest; unchanged on any doubt."""
    if not is_enabled() or not isinstance(manifest, dict):
        return manifest
    structure = unwrap_structure_instantiation(structure_instantiation)
    chart_type = str(structure.get("chart_type") or "").strip().lower()
    nodes = [n for n in structure.get("nodes") or [] if isinstance(n, dict) and n.get("id")]
    if chart_type not in _ARCHITECTURE_TYPES or not 2 <= len(nodes) <= _MAX_NODES:
        return manifest

    result = deepcopy(manifest)
    elements: List[Dict[str, Any]] = result.get("elements") or []
    meta = result.setdefault("_meta", {})
    id_map: Dict[str, str] = meta.get("id_map") or {}
    by_eid = {e.get("id"): e for e in elements}
    hosts: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        host = by_eid.get(id_map.get(str(node["id"]), ""))
        if not host or host.get("type") not in {"rectangle", "ellipse", "diamond"}:
            logger.info("[ArchDesignSystem] node %s has no host shape; skipping", node["id"])
            return manifest
        hosts[str(node["id"])] = host

    cards = [_Card(node, _canonical_role(node)) for node in nodes]
    plan = _plan_from_spec(layout_specification, cards)
    if plan is None and len({c.tier for c in cards}) < 2:
        return manifest
    _assign_service_hues(cards)
    colour_sources = []
    for card in cards:
        styling = (layout_instantiation or {}).get(card.id)
        card.colors, source = _card_colors(card, styling if isinstance(styling, dict) else {})
        colour_sources.append(source)
    card_by_id = {c.id: c for c in cards}

    edges: List[Dict[str, Any]] = []
    for edge in structure.get("edges") or []:
        if isinstance(edge, dict) and edge.get("source") in card_by_id and edge.get("target") in card_by_id \
                and edge.get("source") != edge.get("target"):
            edges.append(edge)
    _layout(cards, [(e["source"], e["target"]) for e in edges], plan)

    removed: set = set()
    # Group frames are dropped: the tier template already carries the grouping.
    group_ids = [str(g.get("id")) for g in structure.get("groups") or [] if isinstance(g, dict) and g.get("id")]
    for group_id in group_ids:
        for eid in (group_frame_render_id(id_map, group_id), id_map.get(group_id + TITLE_SUFFIX)):
            if eid:
                removed.add(eid)
    for semantic_id, eid in id_map.items():
        if semantic_id.endswith(BACKGROUND_SUFFIX) or semantic_id.endswith(TITLE_SUFFIX):
            removed.add(eid)
    arrows = [e for e in elements if e.get("type") == "arrow"]
    for arrow in arrows:
        removed.add(arrow.get("id"))
    for element in elements:
        if element.get("containerId") in removed:
            removed.add(element.get("id"))

    files = result.setdefault("files", {})
    new_elements: List[Dict[str, Any]] = []
    index_counter = 0

    def next_index() -> str:
        nonlocal index_counter
        index_counter += 1
        return sequential_index(index_counter)

    for card in cards:
        host = hosts[card.id]
        fill, stroke, ink = card.colors
        group_id = "card-" + _stable_id("group", card.id)
        texts = [e for e in elements if e.get("type") == "text" and e.get("containerId") == host["id"]]
        icon_eid = id_map.get(f"{card.id}:icon")
        icons = [e for e in elements if e.get("type") == "image" and (
            e.get("id") == icon_eid or ((e.get("customData") or {}).get(ICON_KEY) or {}).get("hostId") == host["id"])]
        for element in texts + icons:
            removed.add(element.get("id"))

        host.update({
            "type": "rectangle", "x": card.x, "y": card.y, "width": card.w, "height": card.h,
            "backgroundColor": fill, "strokeColor": stroke, "strokeWidth": 1.5,
            "strokeStyle": "dashed" if card.role == "external" else "solid",
            "fillStyle": "solid", "roughness": 0, "opacity": 100, "roundness": {"type": 3},
            "groupIds": [group_id], "boundElements": [], "angle": 0,
            "customData": {**(host.get("customData") or {}),
                           CARD_KEY: {"role": card.role}},
            "version": int(host.get("version", 1)) + 1,
        })
        host["index"] = next_index()
        new_elements.append(host)

        asset = icon_file(card.icon, ink)
        files[asset["id"]] = asset
        icon_id = icons[0]["id"] if icons else _stable_id("icon", card.id)
        new_elements.append({
            "id": icon_id, "type": "image", "x": card.x + _PAD_X, "y": card.cy - _ICON / 2,
            "width": _ICON, "height": _ICON, "angle": 0, "strokeColor": "transparent",
            "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 1,
            "strokeStyle": "solid", "roughness": 0, "opacity": 100, "groupIds": [group_id],
            "frameId": None, "roundness": None, "index": next_index(), "seed": 1,
            "version": 2, "versionNonce": 1, "isDeleted": False, "boundElements": [],
            "updated": 1, "link": None, "locked": False, "fileId": asset["id"],
            "status": "saved", "scale": [1, 1], "crop": None,
            "customData": {ICON_KEY: {"hostId": host["id"], "name": card.icon}},
        })
        id_map[f"{card.id}:icon"] = icon_id

        text_x = card.x + _PAD_X + _ICON + _ICON_GAP
        title_h = _TITLE_SIZE * _LINE_HEIGHT
        sub_h = _SUBLABEL_SIZE * _LINE_HEIGHT if card.sublabel else 0.0
        gap = 6 if card.sublabel else 0
        top = card.cy - (title_h + gap + sub_h) / 2
        title_id = texts[0]["id"] if texts else _stable_id("title", card.id)
        new_elements.append(_text_element(title_id, card.title, _TITLE_SIZE, _TITLE_INK,
                                          text_x, top, [group_id], next_index()))
        if card.sublabel:
            new_elements.append(_text_element(_stable_id("sublabel", card.id), card.sublabel,
                                              _SUBLABEL_SIZE, _SUBLABEL_INK, text_x,
                                              top + title_h + gap, [group_id], next_index()))

    # Connectors: one per unordered pair, double-headed when both directions exist.
    pair_heads: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source"], edge["target"])
        reverse_key = (edge["target"], edge["source"])
        if reverse_key in pair_heads:
            pair_heads[reverse_key]["bidirectional"] = True
            pair_heads[reverse_key]["merged"].append(edge.get("id"))
            continue
        if key in pair_heads:
            pair_heads[key]["merged"].append(edge.get("id"))
        else:
            pair_heads[key] = {"edge": edge, "bidirectional": False, "merged": []}

    router = _Router(cards, list(pair_heads))
    arrow_by_edge = {(a.get("meta") or {}).get("semantic_edge_id"): a for a in arrows}

    connector_elements: List[Dict[str, Any]] = []
    for (source, target), info in pair_heads.items():
        edge = info["edge"]
        points = router.route(source, target)
        if len(points) < 2:
            continue
        ox, oy = points[0]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        original = arrow_by_edge.get(edge.get("id")) or {}
        arrow_id = original.get("id") or _stable_id("arrow", str(edge.get("id") or f"{source}->{target}"))
        removed.discard(arrow_id)
        dashed = str(edge.get("style") or edge.get("line_style") or "").lower() in {"dashed", "async"}
        connector_elements.append({
            "id": arrow_id, "type": "arrow", "x": ox, "y": oy,
            "width": max(xs) - min(xs), "height": max(ys) - min(ys),
            "points": [[x - ox, y - oy] for x, y in points],
            "angle": 0, "strokeColor": card_by_id[source].colors[2],
            "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 1.5,
            "strokeStyle": "dashed" if dashed else "solid", "roughness": 0, "opacity": 100,
            "groupIds": [], "frameId": None, "roundness": None, "index": "",
            "seed": int(arrow_id[:8], 16) if all(ch in "0123456789abcdef" for ch in arrow_id[:8]) else 1,
            "version": int(original.get("version", 1)) + 1, "versionNonce": 1,
            "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False,
            "startArrowhead": "triangle" if info["bidirectional"] else None,
            "endArrowhead": "triangle", "lastCommittedPoint": None, "elbowed": False,
            "meta": {**(original.get("meta") or {}), "semantic_edge_id": edge.get("id"),
                     "merged_semantic_edge_ids": [i for i in info["merged"] if isinstance(i, str)],
                     "source": source, "target": target},
        })

    # Paint order: connectors behind cards, so shared trunks never cover text.
    ordered: List[Dict[str, Any]] = []
    for connector in connector_elements:
        connector["index"] = next_index()
        ordered.append(connector)
    ordered.extend(new_elements)
    handled = {e["id"] for e in ordered} | removed | set(hosts[c.id]["id"] for c in cards)
    for element in elements:
        if element.get("id") in handled:
            continue
        element["index"] = next_index()
        ordered.append(element)
    for position, element in enumerate(ordered):
        element["index"] = sequential_index(position)
    result["elements"] = ordered

    live_ids = {e["id"] for e in ordered}
    meta["id_map"] = {k: v for k, v in id_map.items() if v in live_ids}
    used_files = {e.get("fileId") for e in ordered if e.get("type") == "image"}
    result["files"] = {k: v for k, v in files.items() if k in used_files}
    app_state = result.setdefault("appState", {})
    app_state["viewBackgroundColor"] = "#FFFFFF"
    meta["architecture_design_system"] = {
        "tier_plan_source": "layout_agent" if plan else "fallback",
        "colour_source": "style_agent" if all(s == "style_agent" for s in colour_sources) else (
            "mixed" if "style_agent" in colour_sources else "fallback"),
        "cards": {c.id: {"role": c.role, "icon": c.icon, "colors": list(c.colors)} for c in cards},
    }
    logger.info("[ArchDesignSystem] Applied to %d cards, %d connectors", len(cards), len(connector_elements))
    return result
