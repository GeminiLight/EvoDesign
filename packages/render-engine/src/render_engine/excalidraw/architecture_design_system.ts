// Ported from evodesign/agentic_system/render_engine/excalidraw/architecture_design_system.py — keep in sync.
//
// Architecture design-system tool: executes agent decisions deterministically.
//
// The agents keep their roles from the method: Structure decides components,
// roles, sublabels and icons; Style assigns a palette family to every node;
// Layout decides the tier plan (which node sits in which column, in which order,
// and what forms the bottom row). This tool turns those decisions into canvas
// geometry with one fixed visual treatment.
//
// Representation notes (see migration/notes/WP08.md):
// - Python tuples (points, colours, (tier plan) pairs) are arrays.
// - Dicts keyed by node ids / tuple pairs that are only looked up internally
//   (``by_id``, ``neighbours``, ``canon``, ``pair_heads``, ``arrow_by_edge``,
//   junction candidates) are ``Map``s; tuple keys are JSON-encoded strings.
// - ``max(set(xs), key=xs.count)`` iterates a str set in hash order in Python
//   (PYTHONHASHSEED dependent, so non-deterministic on ties); the port breaks
//   ties by first occurrence.

import { assignF, copyF, isF, markF, pyDeepcopy } from '../../py/float_marks.ts';
import { pyGet, pyGetItem, pyItems, pySetdefault, type PyMapping } from '../../py/dict.ts';
import { pyEq, pyIn, pyNe } from '../../py/eq.ts';
import { getEnv } from '../../py/env.ts';
import { PyTypeError, ValueError } from '../../py/errors.ts';
import { sha256Hex } from '../../py/hash.ts';
import { getLogger } from '../../py/logging.ts';
import { floorDiv, pyInt, pyRound, pySum } from '../../py/number.ts';
import { pySort, pySorted } from '../../py/sort.ts';
import { cpLen, cpSlice, pyFormatFixed, pyIsupper, pyLower, pyStr, pyStrip } from '../../py/str.ts';
import { isDict, isList, isMapping, isStr, pyOr, truthy } from '../../py/truthy.ts';
import { east_asian_width } from '../../py/unicodedata.ts';
import {
  CARD_KEY,
  DECORATION_KEY,
  ICON_KEY,
  JUNCTION_KEY,
  bundled_icons,
  icon_file,
} from '../../common/node_icons.ts';
import { BACKGROUND_SUFFIX, TITLE_SUFFIX, group_frame_render_id } from '../../common/semantic_ids.ts';
import { unwrap_structure_instantiation } from '../../common/spec_utils.ts';
import { icons_disabled, preserve_explicit_design } from '../../common/design_constraints.ts';
import { sequential_index } from '../shared/order_keys.ts';

type Dict = Record<string, unknown>;
export type Point = [number, number];
type Colors = [string, string, string];
type Rgb = [number, number, number];

export const logger = getLogger('evodesign.agentic_system.render_engine.excalidraw.architecture_design_system');

export const _ARCHITECTURE_TYPES = new Set(['architecture', 'architecture_diagram']);
export const _MAX_NODES = 14;

export const _FONT = 2;
export const _TITLE_SIZE = 20;
export const _SUBLABEL_SIZE = 14;
export const _LINE_HEIGHT = 1.25;
export const _TITLE_INK = '#1F2937';
export const _SUBLABEL_INK = '#6B7280';

export const _PAD_X = 22;
export const _ICON = 36;
export const _ICON_GAP = 16;
export const _MIN_CARD_W = 220;
export const _MAX_CARD_W = 380;
export const _CARD_H = 84;
export const _CARD_H_NO_SUB = 64;

export const _COL_GAP = 120;
export const _ROW_GAP = 36;
export const _BOTTOM_GAP = 56;
export const _BUS_DROP = 48;
export const _SIDE_CORRIDOR = 24;
export const _MAX_BOTTOM = 5;
export const _MAX_COLUMN = 5;
export const _JUNCTION = 7;
export const _DIAGRAM_TITLE_SIZE = 26;
export const _ZONE_FILL = '#F8FAFC';
export const _ZONE_STROKE = '#E2E8F0';
export const _ZONE_INK = '#64748B';
export const _ZONE_LABEL_SIZE = 14;
export const _ZONE_PAD = 16;
export const _ZONE_HEAD = 40;
export const _MUTED: Colors = ['#F8FAFC', '#CBD5E1', '#64748B'];
export const _MUTED_TITLE_INK = '#475569';
export const _PRIMARY_STROKE_WIDTH = 2.5;
export const _PRIMARY_TITLE_SIZE = 22;
// Connectors touching a primary card form the main path; the rest step back.
export const _MAIN_PATH_WIDTH = 2.5;
export const _SIDE_PATH_OPACITY = 60;
// Default zone names by dominant role, used when the layout agent named none.
export const _ZONE_NAMES: Record<string, [string, string]> = {
  actor: ['用户', 'Users'], client: ['客户端', 'Clients'], gateway: ['接入层', 'Entry'],
  service: ['服务层', 'Services'], worker: ['服务层', 'Services'], model: ['外部能力', 'External'],
  external: ['外部能力', 'External'], bottom: ['数据与基础设施', 'Data & infrastructure'],
};
export const _ORIGIN: Point = [80.0, 80.0];

// Fallback (fill, stroke, ink) when the style agent assigned no usable colour.
// Ink colours the icon and every connector leaving the card.
export const _HUES: Record<string, Colors> = {
  blue: ['#EAF2FD', '#9DC1EE', '#2F6BD0'],
  violet: ['#F1EEFD', '#BDAEF2', '#6A4FD6'],
  green: ['#E8F6EF', '#97D2B5', '#1F9467'],
  orange: ['#FFF4E5', '#F2C47F', '#D9822B'],
  teal: ['#E6F5F7', '#93CFD6', '#14838C'],
  rose: ['#FDEEF2', '#EFB2C2', '#C2456A'],
  gray: ['#F4F5F7', '#C5CAD3', '#4B5563'],
};
export const _SERVICE_HUES = ['green', 'blue', 'orange', 'teal', 'rose'];

// Canonical role -> (tier, hue, default icon). Tiers: -1 people, 0 clients,
// 1 gateways, 2 services, 3 side systems (right column), 4 bottom row.
export const _ROLES: Record<string, [number, string | null, string]> = {
  actor: [-1, 'gray', 'outline_users'],
  client: [0, 'blue', 'outline_monitor'],
  gateway: [1, 'violet', 'outline_network'],
  service: [2, null, 'outline_boxes'],
  worker: [2, null, 'outline_workflow'],
  model: [3, 'rose', 'outline_brain'],
  external: [3, 'gray', 'outline_cloud'],
  database: [4, 'violet', 'outline_database'],
  cache: [4, 'green', 'outline_layers'],
  queue: [4, 'blue', 'outline_radio'],
  storage: [4, 'orange', 'outline_hard_drive'],
  search: [4, 'teal', 'outline_search'],
  observability: [4, 'orange', 'outline_activity'],
};

// Name keywords are checked before the coarse ``role``/``class`` tokens, in this
// order, because names like "MQTT 接入网关" or "Flink 流处理服务" carry the role.
export const _ENTRY_ROLES = new Set(['client', 'gateway']);
export const _BACKEND_ROLES = new Set(['service', 'worker', 'database', 'cache', 'queue', 'storage', 'search', 'observability']);

export const _NAME_ROLES: [string, string[]][] = [
  ['gateway', ['gateway', '网关', 'nginx', 'load balanc', '负载均衡', 'ingress', '反向代理', 'cdn',
    'waf', 'cloudflare', 'akamai']],
  ['database', ['mysql', 'postgres', 'mongo', 'database', '数据库', 'influx', '时序', 'milvus',
    'vector', '向量', 'clickhouse', 'oracle', 'sqlite', 'hbase', 'dynamo', 'warehouse']],
  ['cache', ['redis', 'cache', '缓存', 'memcache']],
  ['search', ['elasticsearch', 'elastic', 'opensearch', 'solr', '搜索引擎', 'search engine']],
  ['storage', ['oss', 's3', 'object stor', '对象存储', 'blob', 'minio', '文件存储', 'hdfs']],
  ['queue', ['kafka', 'rabbit', 'queue', '队列', '消息', 'pulsar', 'nats', 'event bus', 'broker']],
  ['observability', ['prometheus', 'monitoring', 'logging', '监控', '日志', 'tracing']],
  ['model', ['llm', '大模型', 'language model', 'gpt', '模型']],
  ['external', ['third-party', 'third party', '第三方', 'provider', 'sms', '短信', '企业微信',
    '钉钉', 'email', '邮件', 'stripe', '支付宝']],
  ['worker', ['pipeline', '流水线', 'flink', 'spark', 'etl', 'worker', '批处理', '流处理',
    'consumer', 'scheduler', '定时']],
  ['service', ['service', '服务', 'server', 'backend', '后端', 'engine', 'orchestr', '编排', 'api']],
  ['client', ['web', 'app', 'mobile', 'browser', '浏览器', 'h5', '小程序', 'portal', 'interface',
    '界面', '前端', 'frontend', 'client', '客户端', 'dashboard', '看板', 'grafana',
    'device', '设备', 'console', '控制台']],
  ['actor', ['user', '用户', '人员', '老师', '学生', 'customer', '客户', '运维', 'admin',
    'operator', 'engineer', 'person', 'people']],
];

export const _ROLE_ALIASES: [string, string][] = [
  ['observab', 'observability'], ['monitor', 'observability'],
  ['actor', 'actor'], ['person', 'actor'], ['client', 'client'], ['user', 'actor'],
  ['frontend', 'client'],
  ['gateway', 'gateway'], ['proxy', 'gateway'], ['load_balancer', 'gateway'],
  ['cache', 'cache'], ['queue', 'queue'], ['message', 'queue'], ['bus', 'queue'],
  ['broker', 'queue'], ['search', 'search'], ['vector', 'database'], ['database', 'database'],
  ['storage', 'storage'], ['store', 'storage'], ['model', 'model'], ['llm', 'model'],
  ['external', 'external'], ['third', 'external'], ['worker', 'worker'], ['pipeline', 'worker'],
  ['service', 'service'], ['api', 'service'],
];

// Keyword -> icon, matched against the label when the structure stage gave no icon.
export const _ICON_KEYWORDS: [string[], string][] = [
  [['仓库', 'warehouse', 'inventory', '库存'], 'outline_package'],
  [['退款', 'refund', 'reimburse'], 'outline_wallet'],
  [['物流', '快递', '退货', 'shipping', 'logistics', 'deliver'], 'outline_truck'],
  [['审核', '验货', 'review', 'approv', 'inspect'], 'outline_clipboard_list'],
  [['客服', '人工', 'support agent', 'customer service'], 'outline_users'],
  [['web', 'browser', 'h5', '网页', '浏览器', 'portal', '门户'], 'outline_globe'],
  [['app', 'mobile', 'ios', 'android', '手机', '小程序', '移动'], 'outline_smartphone'],
  [['gateway', '网关', 'nginx', 'load balanc', '负载'], 'outline_network'],
  [['老师', '学生', '人员', 'users', 'people', 'team'], 'outline_users'],
  [['user', 'account', 'member', '用户', '会员', '账号', 'customer', '客户'], 'outline_user'],
  [['order', '订单'], 'outline_file_text'],
  [['pay', '支付', 'billing', '账单'], 'outline_credit_card'],
  [['notif', '通知', '推送', 'sms', '短信', 'alert', '告警'], 'outline_bell'],
  [['search', '搜索', 'elastic'], 'outline_search'],
  [['cache', 'redis', '缓存'], 'outline_layers'],
  [['kafka', 'mq', 'queue', '队列', '消息', 'mqtt', 'rabbit'], 'outline_radio'],
  [['oss', 's3', 'object', '对象存储', '文件'], 'outline_hard_drive'],
  [['mysql', 'postgres', 'mongo', 'database', '数据库', 'influx', '时序', 'milvus', '向量'],
    'outline_database'],
  [['llm', 'gpt', '大模型', '模型', 'model'], 'outline_brain'],
  [['grafana', 'dashboard', '看板', 'monitor', '监控'], 'outline_chart_column'],
  [['flink', 'spark', 'stream', '流处理', 'pipeline', '流水线', 'etl'], 'outline_workflow'],
  [['dispatch', '调度', 'rider', 'courier', '骑手', '配送'], 'outline_truck'],
  [['course', '课程', '作业', 'homework'], 'outline_file_text'],
  [['live', '直播', 'video', '视频'], 'outline_video'],
  [['chat', '聊天', '对话'], 'outline_message_square'],
  [['device', '设备', 'sensor', '传感'], 'outline_cpu'],
  [['auth', '认证', '登录', 'security', '安全'], 'outline_shield'],
  [['merchant', '商家', 'restaurant', '餐厅', 'store', '店'], 'outline_store'],
  [['wechat', '企业微信', '微信', 'mail', '邮件'], 'outline_send'],
];

const _OFF = new Set(['0', 'false', 'no', 'off']);

function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** ``x or []`` iteration over JSON-ish values. */
function _iter(value: unknown): unknown[] {
  if (!truthy(value)) return [];
  if (isList(value)) return value;
  if (isStr(value)) return [...value];
  if (value instanceof Set) return [...value];
  if (value instanceof Map) return [...value.keys()];
  if (isDict(value)) return Object.keys(value);
  throw new PyTypeError(`'${typeof value}' object is not iterable`);
}

/** ``int(text, 16)`` with CPython's literal grammar (underscores only between digits). */
function _int16(text: string): number {
  const stripped = pyStrip(text);
  if (!/^[+-]?(0[xX]_?)?[0-9a-fA-F]+(_[0-9a-fA-F]+)*$/.test(stripped)) {
    throw new ValueError(`invalid literal for int() with base 16: '${text}'`);
  }
  return pyInt(stripped, 16);
}

/** ``key in container`` for the ``styling`` value (dict, list or str). */
function _contains(container: unknown, key: string): boolean {
  if (isDict(container)) return hasOwn(container, key);
  if (container instanceof Map) return container.has(key);
  if (isStr(container)) return container.includes(key);
  if (isList(container)) return pyIn(key, container);
  throw new PyTypeError(`argument of type '${typeof container}' is not iterable`);
}

/** ``max(set(items), key=items.count)``; ties go to the first occurrence (see header). */
function _mostCommon(items: string[]): string {
  if (!items.length) throw new ValueError('max() arg is an empty sequence');
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item, (counts.get(item) ?? 0) + 1);
  let best = items[0];
  let bestCount = -1;
  for (const [item, count] of counts) {
    if (count > bestCount) {
      best = item;
      bestCount = count;
    }
  }
  return best;
}

function _numMin(values: number[]): number {
  if (!values.length) throw new ValueError('min() arg is an empty sequence');
  let best = values[0];
  for (const v of values) if (v < best) best = v;
  return best;
}

function _numMax(values: number[]): number {
  if (!values.length) throw new ValueError('max() arg is an empty sequence');
  let best = values[0];
  for (const v of values) if (v > best) best = v;
  return best;
}

export function is_enabled(): boolean {
  return !_OFF.has(pyLower(pyStrip(getEnv('EVODESIGN_ARCH_DESIGN_SYSTEM', '1'))));
}

/** Switch for one aesthetic treatment (EMPHASIS, ZONES, TITLE); kept for ablations. */
export function aesthetic_enabled(name: string): boolean {
  return !_OFF.has(pyLower(pyStrip(getEnv(`EVODESIGN_AES_${name}`, '1'))));
}

/** The structure agent's emphasis decision: "primary", "muted" or "". */
export function emphasis_of(node: PyMapping): string {
  const value = pyLower(pyStrip(pyStr(pyOr(pyGet(node, 'emphasis'), ''))));
  return value === 'primary' || value === 'muted' ? value : '';
}

function _isWide(ch: string): boolean {
  const width = east_asian_width(ch);
  return width === 'W' || width === 'F';
}

export function has_cjk(texts: string[]): boolean {
  for (const text of texts) {
    for (const ch of text) {
      if (_isWide(ch)) return true;
    }
  }
  return false;
}

/** The diagram title the structure agent chose, placed above the content. */
export function title_element(title: string, x: number, y: number): Dict {
  const element = _text_element(_stable_id('diagram-title', title), title, _DIAGRAM_TITLE_SIZE, _TITLE_INK,
    x, y, [], '');
  element.customData = { [DECORATION_KEY]: 'title' };
  return element;
}

function _token(value: unknown): string {
  return pyLower(pyStrip(pyStr(pyOr(value, '')))).replaceAll('-', '_').replaceAll(' ', '_');
}

export function _canonical_role(node: PyMapping): string {
  const declared = _token(pyGet(node, 'role'));
  if (hasOwn(_ROLES, declared)) {
    return declared;
  }
  const name = pyLower(`${pyStr(pyGet(node, 'label', ''))} ${pyStr(pyGet(node, 'id', ''))}`);
  for (const [role, words] of _NAME_ROLES) {
    if (words.some((word) => name.includes(word))) {
      return role;
    }
  }
  for (const key of ['role', 'class', 'type', 'kind']) {
    const token = _token(pyGet(node, key));
    for (const [needle, role] of _ROLE_ALIASES) {
      if (token.includes(needle)) {
        return role;
      }
    }
  }
  return 'service';
}

export function _hex(value: unknown): Rgb | null {
  const text = pyStrip(pyStr(pyOr(value, '')));
  if (cpLen(text) !== 7 || !text.startsWith('#')) {
    return null;
  }
  try {
    return [1, 3, 5].map((i) => _int16(cpSlice(text, i, i + 2))) as Rgb;
  } catch (error) {
    if (error instanceof ValueError) return null;
    throw error;
  }
}

function _format02X(value: number): string {
  const digits = Math.abs(value).toString(16).toUpperCase();
  return value < 0 ? `-${digits}` : digits.padStart(2, '0');
}

/** Blend ``color`` toward white by ``weight`` (0 keeps it, 1 is white). */
export function _mix(color: readonly number[], weight: number): string {
  return '#' + color.map((c) => _format02X(pyRound(c + (255 - c) * weight))).join('');
}

/** Keep supplied colors exact; use role defaults for missing properties. */
export function _card_colors(card: _Card, styling: PyMapping): [Colors, string] {
  const fallback = _HUES[card.hue];
  let fill: unknown = pyGet(styling, 'backgroundColor');
  let stroke: unknown = pyGet(styling, 'strokeColor');
  fill = isStr(fill) && fill ? fill : null;
  stroke = isStr(stroke) && stroke ? stroke : null;
  if (truthy(fill) || truthy(stroke)) {
    const rgb = (_hex(stroke) ?? _hex(fallback[2]))!;
    const luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
    const ink = luminance < 0.62 ? rgb : rgb.map((c) => pyRound(c * 0.55));
    return [[(fill as string | null) || fallback[0], (stroke as string | null) || fallback[1], _mix(ink, 0)], 'style_agent'];
  }
  return [fallback, 'fallback'];
}

export function _text_width(text: string, size: number): number {
  if (text.includes('\n')) {
    let best = 0;
    let first = true;
    for (const line of text.split('\n')) {
      const width = _text_width(line, size);
      if (first || width > best) {
        best = width;
        first = false;
      }
    }
    return best;
  }
  let width = 0.0;
  for (const ch of text) {
    if (_isWide(ch)) {
      width += size;
    } else if (pyIsupper(ch)) {
      width += size * 0.66;
    } else if (ch === ' ') {
      width += size * 0.3;
    } else {
      width += size * 0.55;
    }
  }
  return width;
}

/** Wrap without truncating the source, including CJK and long identifiers. */
export function _wrap_text(text: string, size: number, width: number): string {
  const lines: string[] = [];
  for (const paragraph of text.split('\n')) {
    let line = '';
    for (const char of paragraph) {
      if (line && _text_width(line + char, size) > width) {
        lines.push(line);
        line = '';
      }
      line += char;
    }
    lines.push(line);
  }
  return lines.join('\n');
}

export function _pick_icon(node: PyMapping, role: string): string {
  const catalog = bundled_icons();
  const hinted = pyStrip(pyStr(pyOr(pyGet(node, 'icon'), '')));
  if (hinted.startsWith('outline_') && hasOwn(catalog, hinted)) {
    return hinted;
  }
  const haystack = pyLower(`${pyStr(pyGet(node, 'label', ''))} ${pyStr(pyGet(node, 'sublabel', ''))} ${pyStr(pyGet(node, 'id', ''))}`);
  for (const [needles, name] of _ICON_KEYWORDS) {
    if (needles.some((needle) => haystack.includes(needle))) {
      return name;
    }
  }
  return _ROLES[role][2];
}

export function _stable_id(...parts: string[]): string {
  return sha256Hex(parts.join(':')).slice(0, 20);
}

export function _label_parts(node: PyMapping): [string, string] {
  let title = pyStrip(pyStr(pyOr(pyOr(pyGet(node, 'label'), pyGet(node, 'id')), '')));
  let sublabel = pyStrip(pyStr(pyOr(pyOr(pyGet(node, 'sublabel'), pyGet(node, 'description')), '')));
  if (!sublabel && title.includes('\n')) {
    const cut = title.indexOf('\n');
    [title, sublabel] = [pyStrip(title.slice(0, cut)), pyStrip(title.slice(cut + 1))];
  }
  return [title, sublabel.replaceAll('\n', ' ')];
}

export class _Card {
  node: PyMapping;
  id: string;
  role: string;
  tier: number;
  title: string;
  sublabel: string;
  icon: string;
  hue: string;
  colors: Colors;
  x: number;
  y: number;
  w: number;
  h: number;
  col: number | null;
  row: number;
  emphasis: string;
  zone: string;
  // Set by _layout (dynamic attributes in Python).
  display_title = '';
  display_sublabel = '';

  constructor(node: PyMapping, role: string) {
    this.node = node;
    this.id = pyStr(pyGetItem(node, 'id'));
    this.role = role;
    this.tier = _ROLES[role][0];
    [this.title, this.sublabel] = _label_parts(node);
    this.icon = _pick_icon(node, role);
    this.hue = _ROLES[role][1] || 'green';
    this.colors = _HUES[this.hue];
    this.x = this.y = 0.0;
    this.w = this.h = 0.0;
    this.col = null;
    this.row = 0;
    this.emphasis = emphasis_of(node);
    this.zone = '';
  }

  get cx(): number {
    return this.x + this.w / 2;
  }

  get cy(): number {
    return this.y + this.h / 2;
  }

  get right(): number {
    return this.x + this.w;
  }

  get bottom(): number {
    return this.y + this.h;
  }
}

export function _assign_service_hues(cards: _Card[]): null {
  let index = 0;
  for (const card of cards) {
    if (_ROLES[card.role][1] === null) {
      card.hue = _SERVICE_HUES[index % _SERVICE_HUES.length];
      index += 1;
    }
  }
  return null;
}

export function _barycenter_order(
  group: _Card[],
  neighbours: Map<string, string[]>,
  cards: Map<string, _Card>,
  axis: 'cx' | 'cy',
): _Card[] {
  const key = ([position, card]: [number, _Card]): [number, number] => {
    const coords = (neighbours.get(card.id) ?? [])
      .filter((n) => cards.has(n)
        && cards.get(n) !== card && (cards.get(n)!.col !== card.col || card.col === null))
      .map((n) => cards.get(n)![axis]);
    return [coords.length ? pySum(coords) / coords.length : Infinity, position];
  };
  return pySorted(group.map((card, index) => [index, card] as [number, _Card]), key).map(([, card]) => card);
}

type Plan = [_Card[][], _Card[]];

/** Read the layout agent's tier plan; ``None`` unless it is complete and coherent. */
export function _plan_from_spec(layout_specification: unknown, cards: _Card[]): Plan | null {
  let plan: unknown = null;
  let holder: PyMapping = {};
  if (isDict(layout_specification)) {
    [plan, holder] = [pyGet(layout_specification, 'tier_plan'), layout_specification];
    const blueprint = pyGet(layout_specification, 'pattern_specific_layout_blueprint');
    if (plan === null && isDict(blueprint)) {
      [plan, holder] = [pyGet(blueprint, 'tier_plan'), blueprint];
    }
  }
  if (!isDict(plan)) {
    return null;
  }
  // Zone names may sit inside the plan or beside it.
  const planDict = plan;
  const named: Record<string, unknown> = {};
  for (const k of ['column_labels', 'bottom_label']) {
    named[k] = hasOwn(planDict, k) ? planDict[k] : pyGet(holder, k);
  }
  const by_id = new Map<string, _Card>();
  for (const c of cards) by_id.set(c.id, c);
  const raw_columns = pyGet(planDict, 'columns');
  const raw_bottom = pyOr(pyGet(planDict, 'bottom_row'), []);
  if (!isList(raw_columns) || !isList(raw_bottom)) {
    return null;
  }
  const columns: (_Card | null)[][] = raw_columns
    .filter((col) => isList(col) && col.length)
    .map((col) => (col as unknown[]).map((i) => by_id.get(pyStr(i)) ?? null));
  const bottom = raw_bottom.map((i) => by_id.get(pyStr(i)) ?? null);
  const placed = [...columns.flat(), ...bottom];
  if (!columns.length || placed.includes(null) || placed.length !== cards.length || new Set(placed).size !== cards.length) {
    return null;
  }
  // A column is one vertical stack of a single tier. Entry-side cards
  // (clients, gateways) stacked with back-end cards means the plan was read
  // as rows; executing it would scramble the request flow.
  for (const column of columns as _Card[][]) {
    const roles = new Set(column.map((c) => c.role));
    if ([...roles].some((r) => _ENTRY_ROLES.has(r)) && [...roles].some((r) => _BACKEND_ROLES.has(r))) {
      logger.info('[ArchDesignSystem] tier plan mixes entry and back-end roles in one column; using roles');
      return null;
    }
  }
  const labels = named.column_labels;
  if (isList(labels) && labels.length === columns.length) {
    columns.forEach((column, index) => {
      const label = labels[index];
      for (const card of column as _Card[]) {
        card.zone = cpSlice(pyStrip(pyStr(pyOr(label, ''))), null, 24);
      }
    });
  }
  for (const card of bottom as _Card[]) {
    card.zone = cpSlice(pyStrip(pyStr(pyOr(named.bottom_label, ''))), null, 24);
  }
  return [columns as _Card[][], bottom as _Card[]];
}

export function _layout(cards: _Card[], edges: [string, string][], plan: Plan | null = null): null {
  const by_id = new Map<string, _Card>();
  for (const card of cards) by_id.set(card.id, card);
  const widest = _numMax(cards.map((c) =>
    _PAD_X * 2 + (c.icon ? _ICON + _ICON_GAP : 0)
    + Math.max(_text_width(c.title, c.emphasis === 'primary' ? _PRIMARY_TITLE_SIZE : _TITLE_SIZE),
      _text_width(c.sublabel, _SUBLABEL_SIZE))));
  const width = Math.max(_MIN_CARD_W, Math.min(_MAX_CARD_W, widest));
  // Python: max(220, min(380, float)): the float survives only strictly between the int bounds.
  const width_f = widest < _MAX_CARD_W && widest > _MIN_CARD_W;
  let height = cards.some((c) => c.sublabel) ? _CARD_H : _CARD_H_NO_SUB;
  let height_f = false;
  for (const card of cards) {
    const size = card.emphasis === 'primary' ? _PRIMARY_TITLE_SIZE : _TITLE_SIZE;
    const available = width - _PAD_X * 2 - (card.icon ? _ICON + _ICON_GAP : 0);
    card.display_title = _wrap_text(card.title, size, available);
    card.display_sublabel = _wrap_text(card.sublabel, _SUBLABEL_SIZE, available);
    let text_height = card.display_title.split('\n').length * size * _LINE_HEIGHT;
    if (card.sublabel) {
      text_height += 6 + card.display_sublabel.split('\n').length * _SUBLABEL_SIZE * _LINE_HEIGHT;
    }
    if (text_height + 28 > height) height_f = true; // max(int, float) picks the float only when larger
    height = Math.max(height, text_height + 28);
  }
  for (const card of cards) {
    [card.w, card.h] = [width, height];
    markF(card, 'w', width_f);
    markF(card, 'h', height_f);
  }

  const neighbours = new Map<string, string[]>();
  for (const [source, target] of edges) {
    if (!neighbours.has(source)) neighbours.set(source, []);
    neighbours.get(source)!.push(target);
    if (!neighbours.has(target)) neighbours.set(target, []);
    neighbours.get(target)!.push(source);
  }
  // People who only receive from back-end tiers (alert recipients, report
  // readers) join the side-system column instead of standing before clients.
  for (const card of !plan ? cards : []) {
    if (card.role === 'actor') {
      const near = (neighbours.get(card.id) ?? []).filter((n) => by_id.has(n)).map((n) => by_id.get(n)!.tier);
      if (near.length && _numMin(near) >= 2) {
        card.tier = 3;
      }
    }
  }

  let columns: _Card[][];
  let bottom: _Card[];
  if (plan) {
    [columns, bottom] = [plan[0].map((col) => [...col]), [...plan[1]]];
  } else {
    const tiers = [...new Set(cards.filter((c) => c.tier < 4).map((c) => c.tier))].sort((a, b) => a - b);
    columns = tiers.map((tier) => cards.filter((c) => c.tier === tier));
    bottom = cards.filter((c) => c.tier === 4);
  }
  _orient_columns(columns, edges);
  _move_backward_sinks(columns, edges);
  _split_tall_columns(columns, edges);
  _spill_bottom_chains(columns, bottom, edges);

  const place_columns = (): void => {
    const heights = columns.map((col) => col.length * height + (col.length - 1) * _ROW_GAP);
    const main_h = heights.length ? _numMax(heights) : 0;
    columns.forEach((col, index) => {
      const top = _ORIGIN[1] + (main_h - heights[index]) / 2;
      col.forEach((card, row) => {
        [card.col, card.row] = [index, row];
        card.x = _ORIGIN[0] + index * (width + _COL_GAP);
        card.y = top + row * (height + _ROW_GAP);
      });
    });
  };

  const place_bottom = (): void => {
    const main_cards = columns.flat();
    const main_left = main_cards.length ? _numMin(main_cards.map((c) => c.x)) : _ORIGIN[0];
    const main_right = main_cards.length ? _numMax(main_cards.map((c) => c.right)) : _ORIGIN[0] + width;
    const main_bottom = main_cards.length ? _numMax(main_cards.map((c) => c.bottom)) : _ORIGIN[1] - _BUS_DROP * 2;
    const row_w = bottom.length * width + (bottom.length - 1) * _BOTTOM_GAP;
    const left = Math.max(_ORIGIN[0], (main_left + main_right) / 2 - row_w / 2);
    bottom.forEach((card, index) => {
      [card.col, card.row] = [null, index];
      card.x = left + index * (width + _BOTTOM_GAP);
      card.y = main_bottom + _BUS_DROP * 2;
    });
  };

  place_columns();
  place_bottom();
  if (plan) {
    return null;
  }
  // One barycentre pass reduces crossings without fighting the tier template.
  const reordered = columns.map((col) => _barycenter_order(col, neighbours, by_id, 'cy'));
  columns.splice(0, columns.length, ...reordered);
  const reorderedBottom = _barycenter_order(bottom, neighbours, by_id, 'cx');
  bottom.splice(0, bottom.length, ...reorderedBottom);
  place_columns();
  place_bottom();
  return null;
}

/** Mirror a plan whose flow runs right to left; the agent's grouping is kept. */
export function _orient_columns(columns: _Card[][], edges: [string, string][]): null {
  const column_of = new Map<string, number>();
  columns.forEach((col, index) => {
    for (const c of col) column_of.set(c.id, index);
  });
  let forward = 0;
  let backward = 0;
  for (const [source, target] of edges) {
    if (column_of.has(source) && column_of.has(target)) {
      const step = column_of.get(target)! - column_of.get(source)!;
      forward += step > 0 ? 1 : 0;
      backward += step < 0 ? 1 : 0;
    }
  }
  if (backward > forward) {
    logger.info('[ArchDesignSystem] tier plan flows right to left (%d vs %d); mirroring', backward, forward);
    columns.reverse();
  }
  return null;
}

/** Move an output that only receives from columns to its right after its sources. */
export function _move_backward_sinks(columns: _Card[][], edges: [string, string][]): null {
  const column_of = new Map<string, number>();
  columns.forEach((col, index) => {
    for (const c of col) column_of.set(c.id, index);
  });
  const moved: _Card[] = [];
  columns.forEach((col, index) => {
    for (const card of [...col]) {
      const incoming = edges.filter(([s, t]) => t === card.id && column_of.has(s)).map(([s]) => column_of.get(s)!);
      const outgoing = edges.filter(([s, t]) => s === card.id && column_of.has(t)).map(([, t]) => t);
      if (incoming.length && !outgoing.length && _numMin(incoming) > index && col.length > 1) {
        col.splice(col.indexOf(card), 1);
        moved.push(card);
      }
    }
  });
  if (moved.length) {
    logger.info('[ArchDesignSystem] moving end-of-flow nodes %s to a last column', moved.map((c) => c.id));
    columns.push(moved);
  }
  return null;
}

/** Unstack a column taller than the budget, usually a whole pipeline in one stack. */
export function _split_tall_columns(columns: _Card[][], edges: [string, string][]): null {
  let index = 0;
  while (index < columns.length) {
    const column = columns[index];
    if (column.length <= _MAX_COLUMN) {
      index += 1;
      continue;
    }
    const ids = new Set(column.map((c) => c.id));
    const inner = edges.filter(([s, t]) => ids.has(s) && ids.has(t) && s !== t);
    const depth = new Map<string, number>();
    for (const c of column) depth.set(c.id, 0);
    for (let pass = 0; pass < column.length; pass += 1) {
      for (const [source, target] of inner) {
        depth.set(target, Math.max(depth.get(target)!, Math.min(depth.get(source)! + 1, column.length)));
      }
    }
    let layers = [...new Set(depth.values())].sort((a, b) => a - b)
      .map((d) => column.filter((c) => depth.get(c.id) === d));
    if (layers.length < 2 || _numMax(layers.map((layer) => layer.length)) > _MAX_COLUMN) {
      const parts = -floorDiv(-column.length, _MAX_COLUMN);
      const size = -floorDiv(-column.length, parts);
      layers = [];
      for (let i = 0; i < column.length; i += size) layers.push(column.slice(i, i + size));
    }
    logger.info('[ArchDesignSystem] column of %d split into %s', column.length, layers.map((l) => l.length));
    columns.splice(index, 1, ...layers);
    index += layers.length;
  }
  return null;
}

/** Keep the bottom row readable by moving its downstream chains to a last column. */
export function _spill_bottom_chains(columns: _Card[][], bottom: _Card[], edges: [string, string][]): null {
  if (bottom.length <= _MAX_BOTTOM) {
    return null;
  }
  const ids = new Set(bottom.map((c) => c.id));
  const fed = new Set(edges.filter(([s, t]) => ids.has(s) && ids.has(t) && s !== t).map(([, t]) => t));
  const moved = bottom.filter((c) => fed.has(c.id));
  if (!moved.length || moved.length === bottom.length || moved.length > _MAX_BOTTOM) {
    return null;
  }
  logger.info('[ArchDesignSystem] bottom row has %d nodes; moving chain %s to a last column',
    bottom.length, moved.map((c) => c.id));
  columns.push(moved);
  const kept = bottom.filter((c) => !fed.has(c.id));
  bottom.splice(0, bottom.length, ...kept);
  return null;
}

/** Order endpoints so routing always runs left->right, top->bottom, main->bottom row. */
export function _canonical(src: _Card, dst: _Card): [_Card, _Card, boolean] {
  if ((src.col === null && dst.col !== null)
      || (src.col !== null && dst.col !== null && src.col > dst.col)
      || (src.col === null && dst.col === null && src.x > dst.x)
      || (src.col !== null && src.col === dst.col && src.y > dst.y)) {
    return [dst, src, true];
  }
  return [src, dst, false];
}

function _pairKey(source: unknown, target: unknown): string {
  return JSON.stringify([source, target]);
}

/**
 * Orthogonal router for the tier template.
 *
 * Edges crossing the same column gap share one vertical trunk, and every
 * edge into the bottom row shares one horizontal bus. Junction dots mark
 * shared branches.
 */
export class _Router {
  cards: _Card[];
  columns: number[];
  col_x: Map<number, number>;
  last_col: number;
  canon: Map<string, [_Card, _Card, boolean]>;

  constructor(cards: _Card[], pairs: [string, string][]) {
    this.cards = cards;
    const by_id = new Map<string, _Card>();
    for (const c of cards) by_id.set(c.id, c);
    this.columns = [...new Set(cards.filter((c) => c.col !== null).map((c) => c.col!))].sort((a, b) => a - b);
    this.col_x = new Map();
    for (const col of this.columns) {
      this.col_x.set(col, _numMin(cards.filter((c) => c.col === col).map((c) => c.x)));
    }
    this.last_col = this.columns.length ? _numMax(this.columns) : -1;
    this.canon = new Map();
    for (const pair of pairs) {
      this.canon.set(_pairKey(pair[0], pair[1]), _canonical(by_id.get(pair[0])!, by_id.get(pair[1])!));
    }
  }

  _blocked(points: Point[], skip: readonly _Card[]): boolean {
    for (let i = 0; i + 1 < points.length; i += 1) {
      const [x1, y1] = points[i];
      const [x2, y2] = points[i + 1];
      const [lo_x, hi_x, lo_y, hi_y] = [Math.min(x1, x2), Math.max(x1, x2), Math.min(y1, y2), Math.max(y1, y2)];
      for (const card of this.cards) {
        if (skip.includes(card)) {
          continue;
        }
        if (lo_x < card.right - 1 && hi_x > card.x + 1 && lo_y < card.bottom - 1 && hi_y > card.y + 1) {
          return true;
        }
      }
    }
    return false;
  }

  route(source: string, target: string): Point[] {
    const [a, b, reverse] = this.canon.get(_pairKey(source, target))!;
    const cards = this.cards;
    let path: Point[];
    if (a.col !== null && b.col !== null && a.col !== b.col) {
      const trunk_x = this.col_x.get(b.col)! - _COL_GAP / 2;
      const port_y = b.cy;
      path = [[a.right, a.cy], [trunk_x, a.cy], [trunk_x, port_y], [b.x, port_y]];
      if (this._blocked(path, [a, b])) {
        const top = _numMin(cards.filter((c) => c.col !== null).map((c) => c.y)) - _BUS_DROP;
        const exit_x = this.col_x.get(a.col)! + a.w + _COL_GAP / 2;
        path = [[a.right, a.cy], [exit_x, a.cy], [exit_x, top], [trunk_x, top],
          [trunk_x, port_y], [b.x, port_y]];
      }
    } else if (a.col !== null && b.col !== null) {
      if (b.row - a.row === 1) {
        path = [[a.cx, a.bottom], [b.cx, b.y]];
      } else {
        const side = a.right + _SIDE_CORRIDOR;
        path = [[a.right, a.cy], [side, a.cy], [side, b.cy], [b.right, b.cy]];
      }
    } else if (a.col !== null) {
      const bus_y = b.y - 32;
      const drop_x = b.cx;
      if (!cards.some((o) => o.col === a.col && o.row > a.row)) {
        path = [[a.cx, a.bottom], [a.cx, bus_y], [drop_x, bus_y], [drop_x, b.y]];
      } else {
        const on_right = a.col === this.last_col;
        const port = on_right ? a.right : a.x;
        const side = on_right ? a.right + _SIDE_CORRIDOR : a.x - _SIDE_CORRIDOR;
        path = [[port, a.cy], [side, a.cy], [side, bus_y], [drop_x, bus_y], [drop_x, b.y]];
      }
    } else if (b.row - a.row === 1) {
      path = [[a.right, a.cy], [b.x, b.cy]];
    } else {
      const low = _numMax(cards.map((c) => c.bottom)) + _BUS_DROP / 2;
      path = [[a.cx, a.bottom], [a.cx, low], [b.cx, low], [b.cx, b.bottom]];
    }

    const compact: Point[] = [];
    for (const point of path) {
      if (compact.length
          && Math.abs(compact[compact.length - 1][0] - point[0]) < 0.5
          && Math.abs(compact[compact.length - 1][1] - point[1]) < 0.5) {
        continue;
      }
      compact.push(point);
    }
    return reverse ? [...compact].reverse() : compact;
  }
}

export function _zone_rect(zone_id: string, x: number, y: number, w: number, h: number): Dict {
  return _floatGeometry({
    id: zone_id, type: 'rectangle', x, y, width: w, height: h, angle: 0,
    strokeColor: _ZONE_STROKE, backgroundColor: _ZONE_FILL, fillStyle: 'solid',
    strokeWidth: 1, strokeStyle: 'solid', roughness: 0, opacity: 100, groupIds: [],
    frameId: null, roundness: { type: 3 }, index: '', seed: 1, version: 1,
    versionNonce: 1, isDeleted: false, boundElements: [], updated: 1, link: null,
    locked: true, zIndex: 100, customData: { [DECORATION_KEY]: 'zone' },
  }); // every caller passes float geometry (card coordinates are floats)
}

/** Light background bands that name the tiers: one per run of columns, one for the bottom row. */
export function _zones(cards: _Card[]): Dict[] {
  const cjk = has_cjk(cards.map((c) => c.title));

  const name = (group: _Card[], bottom: boolean): string => {
    const agent = group.filter((c) => c.zone).map((c) => c.zone);
    if (agent.length) {
      return _mostCommon(agent);
    }
    const roles = bottom ? ['bottom'] : group.map((c) => c.role);
    const role = _mostCommon(roles);
    return (_ZONE_NAMES[role] ?? ['', ''])[cjk ? 0 : 1];
  };

  const main = cards.filter((c) => c.col !== null);
  if (!main.length) {
    return [];
  }
  const runs: [string, _Card[]][] = [];
  for (const col of [...new Set(main.map((c) => c.col!))].sort((a, b) => a - b)) {
    const group = main.filter((c) => c.col === col);
    const label = name(group, false);
    if (runs.length && runs[runs.length - 1][0] === label) {
      runs[runs.length - 1][1].push(...group);
    } else {
      runs.push([label, group]);
    }
  }

  const seen = new Set<string>();
  runs.forEach(([initial, group], i) => {
    let label = initial;
    if (seen.has(label) && !group.some((c) => c.zone)) {
      label = _ZONE_NAMES.external[cjk ? 0 : 1];
    }
    runs[i] = [!seen.has(label) ? label : '', group];
    seen.add(label);
  });

  const elements: Dict[] = [];
  for (const [label, group] of runs) {
    const x0 = _numMin(group.map((c) => c.x)) - _ZONE_PAD;
    const x1 = _numMax(group.map((c) => c.right)) + _ZONE_PAD;
    const top = _numMin(group.map((c) => c.y)) - _ZONE_HEAD;
    const bottom_edge = _numMax(group.map((c) => c.bottom)) + _ZONE_PAD;
    const zone_id = _stable_id('zone', label, pyFormatFixed(x0, 0));
    elements.push(_zone_rect(zone_id, x0, top, x1 - x0, bottom_edge - top));
    if (label) {
      const text = _text_element(_stable_id('zone-label', label, pyFormatFixed(x0, 0)), label, _ZONE_LABEL_SIZE,
        _ZONE_INK, x0 + 14, top + 12, [], '');
      text.customData = { [DECORATION_KEY]: 'zone_label' };
      elements.push(text);
    }
  }
  const row = cards.filter((c) => c.col === null);
  if (row.length) {
    const label = name(row, true);
    const label_w = label ? _text_width(label, _ZONE_LABEL_SIZE) + 28 : 0;
    const x0 = _numMin(row.map((c) => c.x)) - _ZONE_PAD - label_w;
    const x1 = _numMax(row.map((c) => c.right)) + _ZONE_PAD;
    const y0 = _numMin(row.map((c) => c.y)) - _ZONE_PAD;
    const y1 = _numMax(row.map((c) => c.bottom)) + _ZONE_PAD;
    elements.push(_zone_rect(_stable_id('zone', 'bottom'), x0, y0, x1 - x0, y1 - y0));
    if (label) {
      const text = _text_element(_stable_id('zone-label', 'bottom', label), label, _ZONE_LABEL_SIZE,
        _ZONE_INK, x0 + 14, (y0 + y1) / 2 - _ZONE_LABEL_SIZE * _LINE_HEIGHT / 2, [], '');
      text.customData = { [DECORATION_KEY]: 'zone_label' };
      elements.push(text);
    }
  }
  return elements;
}

function _heading(p: readonly number[], q: readonly number[]): string {
  if (Math.abs(p[0] - q[0]) < 0.5) {
    return q[1] > p[1] ? 'down' : 'up';
  }
  return q[0] > p[0] ? 'right' : 'left';
}

/**
 * Points where connectors branch or merge: three or more directions meet.
 *
 * A dot there reads as "joined" and keeps a branch apart from a plain
 * crossing, which has no dot.
 */
export function _junctions(paths: [readonly (readonly number[])[], string][]): [Point, string][] {
  const segments: [readonly number[], readonly number[]][] = [];
  for (const [points] of paths) {
    for (let i = 0; i + 1 < points.length; i += 1) segments.push([points[i], points[i + 1]]);
  }
  // dict keyed by the rounded (x, y) tuple: the first key is kept, the last colour wins.
  const candidates = new Map<string, [Point, string]>();
  for (const [points, color] of paths) {
    for (const [x, y] of points.slice(1, -1)) {
      const point: Point = [pyRound(x, 1), pyRound(y, 1)];
      const key = `${point[0] === 0 ? 0 : point[0]},${point[1] === 0 ? 0 : point[1]}`;
      const existing = candidates.get(key);
      if (existing) existing[1] = color;
      else candidates.set(key, [point, color]);
    }
  }
  const dots: [Point, string][] = [];
  for (const [[x, y], color] of candidates.values()) {
    const directions = new Set<string>();
    for (const [p, q] of segments) {
      const [lo_x, hi_x, lo_y, hi_y] = [Math.min(p[0], q[0]), Math.max(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[1], q[1])];
      if (!(lo_x - 0.5 <= x && x <= hi_x + 0.5 && lo_y - 0.5 <= y && y <= hi_y + 0.5)) {
        continue;
      }
      let matched = false;
      for (const [end, other] of [[p, q], [q, p]]) {
        if (Math.abs(end[0] - x) < 0.5 && Math.abs(end[1] - y) < 0.5) {
          directions.add(_heading(end, other));
          matched = true;
          break;
        }
      }
      if (!matched) {
        directions.add(_heading([x, y], p));
        directions.add(_heading([x, y], q));
      }
    }
    if (directions.size >= 3) {
      dots.push([[x, y], color]);
    }
  }
  return dots;
}

export function _text_element(
  element_id: string,
  text: string,
  size: number,
  color: string,
  x: number,
  y: number,
  group_ids: string[],
  index: string,
): Dict {
  // Callers pass float positions; _text_width / ``size * 1.25`` are floats; ``size`` is an int.
  return _floatGeometry({
    id: element_id, type: 'text', x, y,
    width: _text_width(text, size), height: size * _LINE_HEIGHT * text.split('\n').length,
    angle: 0, strokeColor: color, backgroundColor: 'transparent',
    fillStyle: 'solid', strokeWidth: 1, strokeStyle: 'solid', roughness: 0,
    opacity: 100, groupIds: group_ids, frameId: null, roundness: null,
    index, seed: _int16(cpSlice(element_id, null, 8)), version: 1, versionNonce: 1,
    isDeleted: false, boundElements: [], updated: 1, link: null, locked: false,
    text, originalText: text, fontSize: size, fontFamily: _FONT,
    textAlign: 'left', verticalAlign: 'top', containerId: null,
    autoResize: true, lineHeight: _LINE_HEIGHT,
  });
}

/** Mark both coordinates of ``[x, y]`` as Python floats. */
function _floatPair(point: number[]): number[] {
  markF(point, 0, true);
  markF(point, 1, true);
  return point;
}

/** Mark x/y/width/height as Python floats. */
function _floatGeometry<T extends object>(element: T): T {
  for (const key of ['x', 'y', 'width', 'height']) markF(element, key, true);
  return element;
}

/** A joined bus must not imply source/target relations absent from the graph. */
export function _ambiguous_junctions(connectors: Dict[]): boolean {
  const paths: Point[][] = connectors.map((a) =>
    (pyGetItem(a, 'points') as number[][]).map(([x, y]) =>
      [(pyGetItem(a, 'x') as number) + x, (pyGetItem(a, 'y') as number) + y] as Point));
  const parents = paths.map((_, i) => i);

  const root = (index: number): number => {
    while (parents[index] !== index) {
      index = parents[index];
    }
    return index;
  };

  for (const [[x, y]] of _junctions(paths.map((points) => [points, ''] as [Point[], string]))) {
    const joined: number[] = [];
    paths.forEach((points, i) => {
      for (let k = 0; k + 1 < points.length; k += 1) {
        const p = points[k];
        const q = points[k + 1];
        if (Math.min(p[0], q[0]) - 0.5 <= x && x <= Math.max(p[0], q[0]) + 0.5
            && Math.min(p[1], q[1]) - 0.5 <= y && y <= Math.max(p[1], q[1]) + 0.5) {
          joined.push(i);
          return;
        }
      }
    });
    for (const index of joined.slice(1)) {
      parents[root(index)] = root(joined[0]);
    }
  }
  const groups = new Map<number, Map<string, [unknown, unknown]>>();
  connectors.forEach((arrow, i) => {
    const meta = pyGetItem(arrow, 'meta') as PyMapping;
    const [source, target] = [pyGetItem(meta, 'source'), pyGetItem(meta, 'target')];
    const r = root(i);
    if (!groups.has(r)) groups.set(r, new Map());
    const arcs = groups.get(r)!;
    arcs.set(_pairKey(source, target), [source, target]);
    if (truthy(pyGet(arrow, 'startArrowhead'))) {
      arcs.set(_pairKey(target, source), [target, source]);
    }
  });
  for (const arcs of groups.values()) {
    for (const [s] of arcs.values()) {
      for (const [, t] of arcs.values()) {
        if (pyNe(s, t) && !arcs.has(_pairKey(s, t))) {
          return true;
        }
      }
    }
  }
  return false;
}

/** Execute the agents' architecture decisions on the manifest; unchanged on any doubt. */
export function apply_architecture_design_system(
  manifest: Dict,
  structure_instantiation: unknown,
  layout_instantiation: Dict | null = null,
  layout_specification: Dict | null = null,
  design_constraints = '',
): Dict {
  if (!is_enabled() || !isDict(manifest)) {
    return manifest;
  }
  const structure = unwrap_structure_instantiation(structure_instantiation);
  const chart_type = pyLower(pyStrip(pyStr(pyOr(pyGet(structure, 'chart_type'), ''))));
  const nodes = _iter(pyGet(structure, 'nodes')).filter((n) => isDict(n) && truthy(pyGet(n, 'id'))) as Dict[];
  if (!_ARCHITECTURE_TYPES.has(chart_type) || !(2 <= nodes.length && nodes.length <= _MAX_NODES)) {
    return manifest;
  }
  if (preserve_explicit_design(manifest, design_constraints)) {
    return manifest;
  }
  // This template has no faithful representation for named boundaries,
  // labeled relations or self-loops. Keep the native renderer's complete scene.
  if (truthy(pyGet(structure, 'groups')) || _iter(pyGet(structure, 'edges')).some((edge) =>
    isDict(edge) && (
      pyEq(pyGet(edge, 'source'), pyGet(edge, 'target')) || truthy(pyGet(edge, 'label')) || truthy(pyGet(edge, 'text'))
    ))) {
    return manifest;
  }
  const manifestElements = _iter(pyGet(manifest, 'elements', []));
  if (manifestElements.some((e) => pyGet(e, 'type') === 'text' && pyIn(
    pyGet(e, 'containerId'),
    manifestElements.filter((a) => pyGet(a, 'type') === 'arrow').map((a) => pyGet(a, 'id')),
  ))) {
    return manifest;
  }
  if (manifestElements.some((e) => pyGet(e, 'type') === 'arrow' && (
    pyGet(e, 'startArrowhead') !== null
    || (isMapping(e) && (e instanceof Map ? e.has('endArrowhead') : hasOwn(e, 'endArrowhead'))
      && !['arrow', 'triangle'].includes(pyGet(e, 'endArrowhead') as string))
  ))) {
    return manifest;
  }

  const result = pyDeepcopy(manifest);
  const elements = _iter(pyGet(result, 'elements')) as Dict[];
  const meta = pySetdefault<unknown>(result, '_meta', {}) as Dict;
  const id_map = pyOr(pyGet(meta, 'id_map'), {}) as Record<string, unknown>;
  const by_eid = new Map<unknown, Dict>();
  for (const e of elements) by_eid.set(pyGet(e, 'id'), e);
  const hosts = new Map<string, Dict>();
  for (const node of nodes) {
    const host = by_eid.get(pyGet(id_map, pyStr(pyGetItem(node, 'id')), ''));
    const hostType = host === undefined ? null : pyGet(host, 'type');
    if (!truthy(host) || !(hostType === 'rectangle' || hostType === 'ellipse' || hostType === 'diamond')) {
      logger.info('[ArchDesignSystem] node %s has no host shape; skipping', pyGetItem(node, 'id'));
      return manifest;
    }
    hosts.set(pyStr(pyGetItem(node, 'id')), host!);
  }

  const cards = nodes.map((node) => new _Card(node, _canonical_role(node)));
  const plan = _plan_from_spec(layout_specification, cards);
  if (plan === null && new Set(cards.map((c) => c.tier)).size < 2) {
    return manifest;
  }
  _assign_service_hues(cards);
  const colour_sources: string[] = [];
  for (const card of cards) {
    // Existing icons encode the user's toggle and intentional partial coverage.
    if (icons_disabled(design_constraints) || !elements.some((e) => pyGet(e, 'type') === 'image' && (
      pyEq(pyGet(e, 'id'), pyGet(id_map, `${card.id}:icon`))
      || pyEq(pyGet(pyOr(pyGet(pyOr(pyGet(e, 'customData'), {}), ICON_KEY), {}), 'hostId'), hosts.get(card.id)!.id)
    ))) {
      card.icon = '';
    }
    const styling = pyGet(pyOr(layout_instantiation, {}), card.id);
    let source: string;
    [card.colors, source] = _card_colors(card, isDict(styling) ? styling : {});
    colour_sources.push(source);
    if (source === 'fallback' && aesthetic_enabled('EMPHASIS') && card.emphasis === 'muted') {
      card.colors = _MUTED;
    } else if (source === 'fallback' && aesthetic_enabled('EMPHASIS') && card.emphasis === 'primary') {
      const ink = card.colors[2];
      card.colors = [_mix(_hex(ink)!, 0.82), ink, ink];
    }
  }
  const card_by_id = new Map<unknown, _Card>();
  for (const c of cards) card_by_id.set(c.id, c);

  const edges: Dict[] = [];
  for (const edge of _iter(pyGet(structure, 'edges'))) {
    if (isDict(edge) && card_by_id.has(pyGet(edge, 'source')) && card_by_id.has(pyGet(edge, 'target'))
        && pyNe(pyGet(edge, 'source'), pyGet(edge, 'target'))) {
      edges.push(edge);
    }
  }
  _layout(cards, edges.map((e) => [e.source, e.target] as [string, string]), plan);

  const removed = new Set<unknown>();
  // Remove stale decorative frames; semantic groups took the native path above.
  const group_ids = _iter(pyGet(structure, 'groups'))
    .filter((g) => isDict(g) && truthy(pyGet(g, 'id')))
    .map((g) => pyStr(pyGet(g, 'id')));
  for (const group_id of group_ids) {
    for (const eid of [group_frame_render_id(id_map, group_id), pyGet(id_map, group_id + TITLE_SUFFIX)]) {
      if (truthy(eid)) {
        removed.add(eid);
      }
    }
  }
  for (const [semantic_id, eid] of pyItems(id_map)) {
    if ((semantic_id as string).endsWith(BACKGROUND_SUFFIX) || (semantic_id as string).endsWith(TITLE_SUFFIX)) {
      removed.add(eid);
    }
  }
  const arrows = elements.filter((e) => pyGet(e, 'type') === 'arrow');
  for (const arrow of arrows) {
    removed.add(pyGet(arrow, 'id'));
  }
  for (const element of elements) {
    const custom = pyOr(pyGet(element, 'customData'), {});
    if (truthy(pyGet(custom, JUNCTION_KEY)) || truthy(pyGet(custom, DECORATION_KEY))) {
      removed.add(pyGet(element, 'id'));
    }
  }
  for (const element of elements) {
    if (removed.has(pyGet(element, 'containerId'))) {
      removed.add(pyGet(element, 'id'));
    }
  }

  const files = pySetdefault<unknown>(result, 'files', {}) as Dict;
  const new_elements: Dict[] = [];
  let index_counter = 0;

  const next_index = (): string => {
    index_counter += 1;
    return sequential_index(index_counter);
  };

  for (const card of cards) {
    const host = hosts.get(card.id)!;
    const [fill, stroke, ink] = card.colors;
    const emphasized = aesthetic_enabled('EMPHASIS') && card.emphasis === 'primary';
    const title_size = emphasized ? _PRIMARY_TITLE_SIZE : _TITLE_SIZE;
    const title_ink = aesthetic_enabled('EMPHASIS') && card.emphasis === 'muted' ? _MUTED_TITLE_INK : _TITLE_INK;
    const group_id = 'card-' + _stable_id('group', card.id);
    const texts = elements.filter((e) => pyGet(e, 'type') === 'text' && pyEq(pyGet(e, 'containerId'), host.id));
    const icon_eid = pyGet(id_map, `${card.id}:icon`);
    const icons = elements.filter((e) => pyGet(e, 'type') === 'image' && (
      pyEq(pyGet(e, 'id'), icon_eid)
      || pyEq(pyGet(pyOr(pyGet(pyOr(pyGet(e, 'customData'), {}), ICON_KEY), {}), 'hostId'), host.id)));
    for (const element of [...texts, ...icons]) {
      removed.add(pyGet(element, 'id'));
    }

    const update: Dict = {
      type: 'rectangle', x: card.x, y: card.y, width: card.w, height: card.h,
      backgroundColor: fill, strokeColor: stroke,
      strokeWidth: emphasized ? _PRIMARY_STROKE_WIDTH : 1.5,
      strokeStyle: card.role === 'external' ? 'dashed' : 'solid',
      fillStyle: 'solid', roughness: 0, opacity: 100, roundness: { type: 3 },
      groupIds: [group_id], boundElements: [], angle: 0,
      customData: { ...(pyOr(pyGet(host, 'customData'), {}) as Dict), [CARD_KEY]: { role: card.role } },
      version: pyInt(pyGet(host, 'version', 1) as number) + 1,
    };
    assignF(host, update, ['x', 'y']);
    markF(host, 'width', isF(card, 'w'));
    markF(host, 'height', isF(card, 'h'));
    const styling = pyOr(pyGet(pyOr(layout_instantiation, {}), card.id), {});
    if (_contains(styling, 'strokeWidth')) {
      if (!isMapping(styling)) throw new PyTypeError('string indices must be integers');
      host.strokeWidth = pyGetItem(styling, 'strokeWidth');
      copyF(styling, 'strokeWidth', host, 'strokeWidth');
    }
    host.index = next_index();
    new_elements.push(host);

    let icon_id: unknown = null;
    if (card.icon) {
      const asset = icon_file(card.icon, ink);
      files[asset.id as string] = asset;
      icon_id = icons.length ? icons[0].id : _stable_id('icon', card.id);
      new_elements.push({
        id: icon_id, type: 'image', x: card.x + _PAD_X, y: card.cy - _ICON / 2,
        width: _ICON, height: _ICON, angle: 0, strokeColor: 'transparent',
        backgroundColor: 'transparent', fillStyle: 'solid', strokeWidth: 1,
        strokeStyle: 'solid', roughness: 0, opacity: 100, groupIds: [group_id],
        frameId: null, roundness: null, index: next_index(), seed: 1,
        version: 2, versionNonce: 1, isDeleted: false, boundElements: [],
        updated: 1, link: null, locked: false, fileId: asset.id,
        status: 'saved', scale: [1, 1], crop: null,
        customData: { [ICON_KEY]: { hostId: host.id, name: card.icon } },
      });
      const icon_element = new_elements[new_elements.length - 1];
      markF(icon_element, 'x', true);
      markF(icon_element, 'y', true);
      id_map[`${card.id}:icon`] = icon_id;
    }

    const text_x = card.x + _PAD_X + (card.icon ? _ICON + _ICON_GAP : 0);
    const title_h = title_size * _LINE_HEIGHT * card.display_title.split('\n').length;
    const sub_h = card.sublabel ? _SUBLABEL_SIZE * _LINE_HEIGHT * card.display_sublabel.split('\n').length : 0.0;
    const gap = card.sublabel ? 6 : 0;
    const top = card.cy - (title_h + gap + sub_h) / 2;
    const title_id = (texts.length ? texts[0].id : _stable_id('title', card.id)) as string;
    const label_element = _text_element(title_id, card.display_title, title_size, title_ink,
      text_x, top, [group_id], next_index());
    Object.assign(label_element, {
      containerId: host.id, originalText: card.title, autoResize: false,
      width: card.right - _PAD_X - text_x,
    });
    new_elements.push(label_element);
    host.boundElements = [{ id: title_id, type: 'text' }];
    const parts = (host.customData as Dict)[CARD_KEY] as Dict;
    Object.assign(parts, { titleId: title_id, iconId: card.icon ? icon_id : null });
    if (card.sublabel) {
      const sublabel_id = _stable_id('sublabel', card.id);
      const sublabel = _text_element(sublabel_id, card.display_sublabel,
        _SUBLABEL_SIZE, _SUBLABEL_INK, text_x,
        top + title_h + gap, [group_id], next_index());
      Object.assign(sublabel, {
        originalText: card.sublabel,
        customData: { evoDesignCardPart: { hostId: host.id } },
      });
      new_elements.push(sublabel);
      parts.sublabelId = sublabel_id;
    }
  }

  // Connectors: one per unordered pair, double-headed when both directions exist.
  interface PairInfo { edge: Dict; bidirectional: boolean; merged: unknown[]; pair: [string, string] }
  const pair_heads = new Map<string, PairInfo>();
  for (const edge of edges) {
    const key = _pairKey(edge.source, edge.target);
    const reverse_key = _pairKey(edge.target, edge.source);
    if (pair_heads.has(reverse_key)) {
      pair_heads.get(reverse_key)!.bidirectional = true;
      pair_heads.get(reverse_key)!.merged.push(pyGet(edge, 'id'));
      continue;
    }
    if (pair_heads.has(key)) {
      pair_heads.get(key)!.merged.push(pyGet(edge, 'id'));
    } else {
      pair_heads.set(key, { edge, bidirectional: false, merged: [], pair: [edge.source as string, edge.target as string] });
    }
  }

  const router = new _Router(cards, [...pair_heads.values()].map((info) => info.pair));
  const primary = aesthetic_enabled('MAINPATH')
    ? new Set(cards.filter((c) => c.emphasis === 'primary').map((c) => c.id))
    : new Set<string>();
  const arrow_by_edge = new Map<unknown, Dict>();
  for (const a of arrows) arrow_by_edge.set(pyGet(pyOr(pyGet(a, 'meta'), {}), 'semantic_edge_id'), a);

  const connector_elements: Dict[] = [];
  for (const info of pair_heads.values()) {
    const [source, target] = info.pair;
    const edge = info.edge;
    const points = router.route(source, target);
    if (points.length < 2) {
      continue;
    }
    const [ox, oy] = points[0];
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const original = pyOr(arrow_by_edge.get(pyGet(edge, 'id')) ?? null, {}) as Dict;
    const arrow_id = pyOr(pyGet(original, 'id'),
      _stable_id('arrow', pyStr(pyOr(pyGet(edge, 'id'), `${pyStr(source)}->${pyStr(target)}`)))) as string;
    removed.delete(arrow_id);
    const dashed = ['dashed', 'async'].includes(
      pyLower(pyStr(pyOr(pyOr(pyGet(edge, 'style'), pyGet(edge, 'line_style')), ''))));
    const main = primary.size > 0 && (primary.has(source) || primary.has(target));
    const seedText = cpSlice(arrow_id, null, 8);
    connector_elements.push({
      id: arrow_id, type: 'arrow', x: ox, y: oy,
      width: _numMax(xs) - _numMin(xs), height: _numMax(ys) - _numMin(ys),
      points: points.map(([x, y]) => _floatPair([x - ox, y - oy])),
      angle: 0, strokeColor: card_by_id.get(source)!.colors[2],
      backgroundColor: 'transparent', fillStyle: 'solid',
      strokeWidth: main ? _MAIN_PATH_WIDTH : 1.5,
      strokeStyle: dashed ? 'dashed' : 'solid', roughness: 0,
      opacity: main || !primary.size ? 100 : _SIDE_PATH_OPACITY,
      groupIds: [], frameId: null, roundness: null, index: '',
      seed: [...seedText].every((ch) => '0123456789abcdef'.includes(ch)) ? _int16(seedText) : 1,
      version: pyInt(pyGet(original, 'version', 1) as number) + 1, versionNonce: 1,
      isDeleted: false, boundElements: [], updated: 1, link: null, locked: false,
      startArrowhead: info.bidirectional ? 'triangle' : null,
      endArrowhead: 'triangle', lastCommittedPoint: null, elbowed: false,
      startBinding: { elementId: hosts.get(source)!.id, focus: 0, gap: 1 },
      endBinding: { elementId: hosts.get(target)!.id, focus: 0, gap: 1 },
      meta: {
        ...(pyOr(pyGet(original, 'meta'), {}) as Dict),
        semantic_edge_id: pyGet(edge, 'id'),
        merged_semantic_edge_ids: info.merged.filter((i) => isStr(i)),
        source, target,
      },
    });
    _floatGeometry(connector_elements[connector_elements.length - 1]); // router points are floats
    for (const endpoint of [source, target]) {
      (hosts.get(endpoint)!.boundElements as unknown[]).push({ id: arrow_id, type: 'arrow' });
    }
  }

  if (_ambiguous_junctions(connector_elements)) {
    logger.info('[ArchDesignSystem] Shared junctions would imply extra relations; keeping native routing');
    return manifest;
  }

  // Paint order: connectors behind cards, so shared trunks never cover text.
  const ordered: Dict[] = [];
  // Main-path strokes paint last so a shared trunk shows them on top.
  pySort(connector_elements, (c) => c.strokeWidth);
  for (const connector of connector_elements) {
    connector.index = next_index();
    ordered.push(connector);
  }
  const paths = connector_elements.map((c) => [
    (c.points as number[][]).map(([px, py]) => [(c.x as number) + px, (c.y as number) + py] as Point),
    c.strokeColor as string,
  ] as [Point[], string]);
  for (const [[x, y], color] of _junctions(paths)) {
    const dot_id = _stable_id('junction', pyFormatFixed(x, 1), pyFormatFixed(y, 1));
    removed.delete(dot_id);
    ordered.push({
      id: dot_id, type: 'ellipse', x: x - _JUNCTION / 2, y: y - _JUNCTION / 2,
      width: _JUNCTION, height: _JUNCTION, angle: 0, strokeColor: color,
      backgroundColor: color, fillStyle: 'solid', strokeWidth: 1, strokeStyle: 'solid',
      roughness: 0, opacity: 100, groupIds: [], frameId: null, roundness: null,
      index: next_index(), seed: 1, version: 1, versionNonce: 1, isDeleted: false,
      boundElements: [], updated: 1, link: null, locked: true,
      customData: { [JUNCTION_KEY]: true },
    });
    markF(ordered[ordered.length - 1], 'x', true);
    markF(ordered[ordered.length - 1], 'y', true);
  }
  const decorations = aesthetic_enabled('ZONES') ? _zones(cards) : [];
  const title = pyStrip(pyStr(pyOr(pyGet(structure, 'title'), '')));
  if (title && aesthetic_enabled('TITLE')) {
    const boxes: Point[] = [...cards.map((c) => [c.x, c.y] as Point), ...decorations.map((d) => [d.x, d.y] as Point)];
    decorations.push(title_element(title, _numMin(boxes.map(([x]) => x)), _numMin(boxes.map(([, y]) => y)) - 64));
  }
  for (const decoration of decorations) {
    decoration.index = next_index();
  }
  ordered.unshift(...decorations);
  ordered.push(...new_elements);
  const handled = new Set<unknown>([...ordered.map((e) => e.id), ...removed, ...cards.map((c) => hosts.get(c.id)!.id)]);
  for (const element of elements) {
    if (handled.has(pyGet(element, 'id'))) {
      continue;
    }
    element.index = next_index();
    ordered.push(element);
  }
  ordered.forEach((element, position) => {
    element.index = sequential_index(position);
  });
  result.elements = ordered;

  const live_ids = new Set(ordered.map((e) => e.id));
  const filtered_id_map: Dict = {};
  for (const [k, v] of Object.entries(id_map)) {
    if (live_ids.has(v)) filtered_id_map[k] = v;
  }
  meta.id_map = filtered_id_map;
  const used_files = new Set(ordered.filter((e) => pyGet(e, 'type') === 'image').map((e) => pyGet(e, 'fileId')));
  const kept_files: Dict = {};
  for (const [k, v] of Object.entries(files)) {
    if (used_files.has(k)) kept_files[k] = v;
  }
  result.files = kept_files;
  const app_state = pySetdefault<unknown>(result, 'appState', {}) as Dict;
  pySetdefault<unknown>(app_state, 'viewBackgroundColor', '#FFFFFF');
  const cardSummary: Dict = {};
  for (const c of cards) cardSummary[c.id] = { role: c.role, icon: c.icon, colors: [...c.colors] };
  meta.architecture_design_system = {
    tier_plan_source: plan ? 'layout_agent' : 'fallback',
    colour_source: colour_sources.every((s) => s === 'style_agent') ? 'style_agent' : (
      colour_sources.includes('style_agent') ? 'mixed' : 'fallback'),
    cards: cardSummary,
  };
  logger.info('[ArchDesignSystem] Applied to %d cards, %d connectors', cards.length, connector_elements.length);
  return result;
}
