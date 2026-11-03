"""Hand-built structure + layout scenes for the frame-defined diagram types.

Geometry imitates what the layout agent emits when it follows each pattern
file, including its usual imperfections (oversized frames, small captions).
"""

from __future__ import annotations

NODE = {"type": "rectangle", "backgroundColor": "#e7f5ff", "strokeColor": "#1971c2"}


def node(nid, text, x, y, w=160, h=56, fs=18, **extra):
    return nid, {**NODE, "x": x, "y": y, "w": w, "h": h, "label": {"text": text, "fontSize": fs}, **extra}


def frame(gid, title, x, y, w, h, fill="#f8f9fa", stroke="#adb5bd", tx=None, ty=None, fs=20):
    return {
        f"{gid}:background": {"type": "rectangle", "x": x, "y": y, "w": w, "h": h,
                              "backgroundColor": fill, "strokeColor": stroke},
        f"{gid}:title": {"type": "text", "x": tx if tx is not None else x + 16,
                         "y": ty if ty is not None else y + 10, "w": max(80, len(title) * 11), "h": 28,
                         "label": {"text": title, "fontSize": fs}},
    }


def edge(eid, a, b, sa="right", sb="left", routing="elbow", head="arrow", label=None):
    out = {"start": {"elementId": a, "side": sa}, "end": {"elementId": b, "side": sb},
           "routing": routing, "startArrowhead": None, "endArrowhead": head, "strokeColor": "#495057"}
    if label:
        out["label"] = {"text": label}
    return eid, out


def quadrant():
    groups = [("q_tl", "Big bets", 220, 80), ("q_tr", "Quick wins", 580, 80),
              ("q_bl", "Money pits", 220, 440), ("q_br", "Fill-ins", 580, 440)]
    layout, sgroups = {}, []
    items = {"q_tl": [("a", "Rewrite engine"), ("b", "Mobile app")],
             "q_tr": [("c", "Dark mode"), ("d", "CSV export"), ("e", "Keyboard nav")],
             "q_bl": [("f", "Custom DSL")], "q_br": [("g", "New icons"), ("h", "Tooltips")]}
    nodes = []
    for gid, title, x, y in groups:
        layout.update(frame(gid, title, x, y, 360, 360))
        for i, (nid, text) in enumerate(items[gid]):
            k, v = node(nid, text, x + 40 + (i % 2) * 150, y + 90 + (i // 2) * 110, w=140, h=50, fs=16)
            layout[k] = v
            nodes.append({"id": nid, "label": text})
        sgroups.append({"id": gid, "label": title, "members": [n for n, _ in items[gid]]})
    k, v = node("x_axis", "Ease →", 520, 830, w=120, h=36, fs=16); layout[k] = v
    k, v = node("y_axis", "Impact ↑", 40, 420, w=120, h=36, fs=16); layout[k] = v
    nodes += [{"id": "x_axis", "label": "Ease →", "class": "axis"},
              {"id": "y_axis", "label": "Impact ↑", "class": "axis"}]
    return {"chart_type": "quadrant", "nodes": nodes, "edges": [], "groups": sgroups}, layout


def layer_stack():
    layers = [("l_app", "Application", ["Web UI", "Mobile", "CLI"]),
              ("l_svc", "Services", ["Auth", "Billing", "Search", "Notify"]),
              ("l_data", "Data", ["Postgres", "Redis"]),
              ("l_infra", "Infrastructure", ["Kubernetes", "Object store"])]
    layout, nodes, groups = {}, [], []
    for i, (gid, title, parts) in enumerate(layers):
        y = 80 + i * 118
        layout.update(frame(gid, title, 100, y, 900, 110, ty=y + 40))
        ids = []
        for j, text in enumerate(parts):
            nid = f"{gid}_{j}"
            k, v = node(nid, text, 300 + j * 170, y + 27, w=150, h=56, fs=16)
            layout[k] = v
            nodes.append({"id": nid, "label": text})
            ids.append(nid)
        groups.append({"id": gid, "label": title, "members": ids})
    k, v = node("rule", "Each layer only uses the one below", 1180, 330, w=180, h=40, fs=12)
    layout[k] = v
    nodes.append({"id": "rule", "label": "Each layer only uses the one below", "class": "axis"})
    return {"chart_type": "layer_stack", "nodes": nodes, "edges": [], "groups": groups}, layout


def deployment():
    # Region > two AZs (mirrored) > hosts; shared DB in the region. Frames are
    # drawn generously, as the layout agent tends to.
    layout = {}
    layout.update(frame("region", "us-east-1", 60, 60, 1300, 860))
    layout.update(frame("az_a", "Zone A", 100, 130, 560, 480, fill="#ffffff"))
    layout.update(frame("az_b", "Zone B", 740, 130, 560, 480, fill="#ffffff"))
    layout.update(frame("host_a", "Node a1", 140, 200, 380, 300, fill="#f1f3f5"))
    layout.update(frame("host_b", "Node b1", 780, 200, 380, 300, fill="#f1f3f5"))
    nodes, layout_nodes = [], [
        ("web_a", "web:8080", 180, 270), ("api_a", "api:9000", 180, 390),
        ("web_b", "web:8080", 820, 270), ("api_b", "api:9000", 820, 390),
        ("lb", "Load balancer", 640, 30), ("db", "Postgres primary", 620, 760)]
    for nid, text, x, y in layout_nodes:
        k, v = node(nid, text, x, y, w=170, h=56, fs=16)
        layout[k] = v
        nodes.append({"id": nid, "label": text})
    edges = [("e1", "lb", "web_a", "bottom", "top", ":443"), ("e2", "lb", "web_b", "bottom", "top", ":443"),
             ("e3", "web_a", "api_a", "bottom", "top", None), ("e4", "web_b", "api_b", "bottom", "top", None),
             ("e5", "api_a", "db", "bottom", "left", ":5432"), ("e6", "api_b", "db", "bottom", "right", ":5432")]
    sedges = []
    for eid, a, b, sa, sb, lab in edges:
        k, v = edge(eid, a, b, sa, sb, label=lab)
        layout[k] = v
        sedges.append({"id": eid, "from": a, "to": b, **({"label": lab} if lab else {})})
    groups = [
        {"id": "region", "label": "us-east-1", "members": ["db"]},
        {"id": "az_a", "label": "Zone A", "members": [], "parent_group_id": "region"},
        {"id": "az_b", "label": "Zone B", "members": [], "parent_group_id": "region"},
        {"id": "host_a", "label": "Node a1", "members": ["web_a", "api_a"], "parent_group_id": "az_a"},
        {"id": "host_b", "label": "Node b1", "members": ["web_b", "api_b"], "parent_group_id": "az_b"},
    ]
    return {"chart_type": "deployment", "nodes": nodes, "edges": sedges, "groups": groups}, layout


def nested():
    layout = {}
    layout.update(frame("org", "Organisation", 60, 60, 1000, 640))
    layout.update(frame("dept", "Engineering", 100, 130, 620, 520, fill="#ffffff"))
    layout.update(frame("team", "Platform team", 140, 200, 400, 300, fill="#f1f3f5"))
    nodes, spots = [], [("p1", "Alice", 180, 270), ("p2", "Bob", 180, 370),
                        ("p3", "Carol", 560, 270), ("p4", "Finance", 800, 270)]
    for nid, text, x, y in spots:
        k, v = node(nid, text, x, y, w=140, h=50, fs=16)
        layout[k] = v
        nodes.append({"id": nid, "label": text})
    groups = [{"id": "org", "label": "Organisation", "members": ["p4"]},
              {"id": "dept", "label": "Engineering", "members": ["p3"], "parent_group_id": "org"},
              {"id": "team", "label": "Platform team", "members": ["p1", "p2"], "parent_group_id": "dept"}]
    return {"chart_type": "nested", "nodes": nodes, "edges": [], "groups": groups}, layout


def cycle():
    import math
    steps = ["Lower prices", "More customers", "More sellers", "Better selection", "Lower cost"]
    layout, nodes, edges = {}, [], []
    cx, cy, r = 500, 420, 280
    for i, text in enumerate(steps):
        a = -math.pi / 2 + i * 2 * math.pi / len(steps)
        k, v = node(f"s{i}", text, cx + r * math.cos(a) - 85, cy + r * math.sin(a) - 28, w=170, h=56, fs=16)
        layout[k] = v
        nodes.append({"id": f"s{i}", "label": text})
    for i in range(len(steps)):
        j = (i + 1) % len(steps)
        k, v = edge(f"c{i}", f"s{i}", f"s{j}", "right", "left")
        layout[k] = v
        edges.append({"id": f"c{i}", "from": f"s{i}", "to": f"s{j}"})
    return {"chart_type": "cycle", "nodes": nodes, "edges": edges, "groups": []}, layout


def user_journey():
    stages = [("st1", "Discover", "Sees an ad", 0), ("st2", "Sign up", "Fills a long form", 2),
              ("st3", "Onboard", "Imports data", 1), ("st4", "Use", "Shares a report", 0)]
    layout, nodes, groups, edges = {}, [], [], []
    for i, (gid, title, action, mood) in enumerate(stages):
        x = 80 + i * 260
        layout.update(frame(gid, title, x, 80, 240, 520))
        k, v = node(f"{gid}_act", action, x + 30, 150, w=180, h=56, fs=16); layout[k] = v
        k, v = node(f"{gid}_feel", ["Happy", "Neutral", "Frustrated"][mood], x + 60, 330 + mood * 70,
                    w=120, h=44, fs=14, type="ellipse"); layout[k] = v
        nodes += [{"id": f"{gid}_act", "label": action},
                  {"id": f"{gid}_feel", "label": ["Happy", "Neutral", "Frustrated"][mood], "class": "feeling"}]
        groups.append({"id": gid, "label": title, "members": [f"{gid}_act", f"{gid}_feel"]})
    for i in range(len(stages) - 1):
        a, b = f"{stages[i][0]}_feel", f"{stages[i + 1][0]}_feel"
        k, v = edge(f"f{i}", a, b)
        layout[k] = v
        edges.append({"id": f"f{i}", "from": a, "to": b})
    return {"chart_type": "user_journey", "nodes": nodes, "edges": edges, "groups": groups}, layout


ALL = {f.__name__: f for f in (quadrant, layer_stack, deployment, nested, cycle, user_journey)}
