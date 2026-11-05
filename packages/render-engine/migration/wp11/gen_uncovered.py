import json, sys, copy
from evodesign.agentic_system.render_engine.shared import edge_routing as er, normalization as nm
from evodesign.agentic_system.render_engine.excalidraw import converter as cv
OUT = sys.argv[1]
vecs = []
def rec(fn, call, *args, transform=lambda r: r):
    a0 = copy.deepcopy(list(args))
    try:
        r = transform(call(*args))
        vecs.append({"fn": fn, "args": a0, "result": r, "args_after": list(args)})
    except Exception as e:
        vecs.append({"fn": fn, "args": a0, "raises": type(e).__name__})

hier = {"nodes": [{"id": "a", "label": "A"}, {"node_id": "b", "label": "B"}],
        "groups": [{"id": "g1", "label": "G", "members": [{"kind": "node", "node": {"id": "m", "label": "M"}}, "a", {"kind": "edge"}]}, "str-group", {"label": "noid", "members": [{"kind": "node"}]}]}
wrapped = {"structure_instantiation": hier}
for h in [hier, wrapped, {}, {"nodes": "x", "groups": []}, {"nodes": [], "groups": [{"id": "", "members": []}]}]:
    rec("iter_concept_nodes", lambda h: list(er.iter_concept_nodes(h)), h)
    for ref in ["a", "b", "m", "g1", "zz", "noid"]:
        rec("resolve_label_from_node_ref", er.resolve_label_from_node_ref, h, ref)
for t in [None, "", "  a\nb  c ", "中文　全角 空格", "tab\tsep\x0bvt\x1cfs\x85nel\xa0nbsp", " line para", "a\r\nb", "ＡＢ​zero"]:
    rec("normalize_text", er.normalize_text, t)
for ref in ["node:a", "a", "", None, "edge:x", "a::b", "group:g", "a__icon"]:
    rec("iter_shape_id_candidates", lambda r: list(er.iter_shape_id_candidates(r)), ref)
els = [{"id": "edge:1", "type": "arrow"}, {"id": "n1", "type": "rectangle"}, {"id": "g1", "type": "rectangle", "customData": {"group_frame": True}},
       {"id": "t1", "type": "text", "containerId": "n1"}, {"id": "i1", "type": "image"}, {"id": "lbl", "type": "text"}, {"id": "frame:x", "type": "frame"}]
rec("sort_and_reindex", nm.sort_and_reindex, copy.deepcopy(els), 0)
rec("sort_and_reindex", nm.sort_and_reindex, copy.deepcopy(els[::-1]), 7)
rec("sort_and_reindex", nm.sort_and_reindex, [], 3)
for d in [{}, {"size": "s"}, {"size": "m"}, {"size": "l"}, {"size": "xl"}, {"size": "huge", "props": {"w": 30, "h": 20}}, {"props": {"w": 20, "h": 20.0}}, {"props": {"w": 12.5}}, {"props": {"h": 9}}, {"props": {"w": True, "h": 3}}, {"props": "x"}, {"props": {"w": "10", "h": 4}}]:
    rec("converter._extract_icon_dimension", cv._extract_icon_dimension, d)
for s in ["<svg/>", "<svg xmlns='x'>中文 ✓ 😀</svg>", ""]:
    rec("_svg_text_to_data_uri", cv._svg_text_to_data_uri, s)
for d in [{"props": {"url": "data:image/png;base64,AAA"}}, {"props": {"url": "  <svg>é</svg>"}}, {"props": {"src": "<svg/>"}}, {"props": {"icon": "settings", "color": "blue"}}, {"props": {"url": "https://x/y/cloud.svg"}}]:
    rec("_icon_to_data_url", cv._icon_to_data_url, d)
json.dump(vecs, open(OUT, "w"), ensure_ascii=False)
print(len(vecs))
