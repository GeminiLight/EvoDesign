"""Group frame fitting and caption anchoring for the frame-defined diagram types."""

from evodesign.agentic_system.render_engine.excalidraw.caption_placer import place_captions
from evodesign.agentic_system.render_engine.excalidraw.design_theme import apply_design_theme
from evodesign.agentic_system.render_engine.excalidraw.group_fitter import (
    fit_excalidraw_groups_to_children,
)


def rect(eid, x, y, w, h, **extra):
    return {"id": eid, "type": "rectangle", "x": x, "y": y, "width": w, "height": h, **extra}


def text(eid, x, y, w, h, container=None, value="", size=20):
    return {"id": eid, "type": "text", "x": x, "y": y, "width": w, "height": h, "containerId": container,
            "text": value, "originalText": value, "fontSize": size}


def fit(elements, id_map, structure, padding=10):
    manifest = {"type": "excalidraw/clipboard", "_meta": {"id_map": id_map}, "elements": elements}
    return {e["id"]: e for e in fit_excalidraw_groups_to_children(manifest, structure, padding)["elements"]}


def test_quadrant_frames_do_not_grow_across_a_shared_centre_line():
    # An item placed across the centre line must not push its quadrant into the neighbour.
    elements = [rect("tl", 0, 0, 400, 400), rect("tr", 400, 0, 400, 400), rect("item", 300, 100, 160, 40)]
    out = fit(elements, {"q_tl": "tl", "q_tr": "tr", "n": "item"},
              {"chart_type": "quadrant", "groups": [{"id": "q_tl", "members": ["n"]}, {"id": "q_tr", "members": []}]})
    assert (out["tl"]["x"], out["tl"]["width"]) == (0, 400)
    assert (out["tr"]["x"], out["tr"]["width"]) == (400, 400)


def test_quadrant_frames_still_grow_on_the_outer_edge():
    elements = [rect("tl", 0, 0, 400, 400), rect("tr", 400, 0, 400, 400), rect("item", 700, 100, 160, 40)]
    out = fit(elements, {"q_tl": "tl", "q_tr": "tr", "n": "item"},
              {"chart_type": "quadrant", "groups": [{"id": "q_tl", "members": []}, {"id": "q_tr", "members": ["n"]}]})
    assert out["tr"]["x"] == 400 and out["tr"]["x"] + out["tr"]["width"] == 870


def test_containment_scopes_shrink_to_contents_and_carry_their_title():
    elements = [rect("frame", 0, 0, 900, 700), text("title", 16, 10, 120, 28, value="Zone A"),
                rect("svc", 100, 200, 160, 50)]
    out = fit(elements, {"zone:background": "frame", "zone:title": "title", "svc": "svc"},
              {"chart_type": "deployment", "groups": [{"id": "zone", "members": ["svc"]}]})
    frame, title = out["frame"], out["title"]
    assert frame["x"] == 100 - 24 and frame["x"] + frame["width"] == 260 + 24
    assert frame["y"] + frame["height"] == 250 + 24
    assert (title["x"], title["y"]) == (frame["x"] + 16, frame["y"] + 10)
    assert title["y"] + title["height"] < 200


def test_containment_scope_is_never_narrower_than_its_title():
    elements = [rect("frame", 0, 0, 900, 700), text("title", 16, 10, 400, 28, value="A very long scope title"),
                rect("svc", 100, 200, 60, 50)]
    out = fit(elements, {"zone:background": "frame", "zone:title": "title", "svc": "svc"},
              {"chart_type": "nested", "groups": [{"id": "zone", "members": ["svc"]}]})
    assert out["frame"]["width"] >= 16 + 400 + 24


def test_architecture_parent_with_only_child_scopes_keeps_its_title_room():
    # Previously skipped; now it must wrap its children without shrinking.
    elements = [rect("outer", 0, 0, 600, 400), rect("inner", 40, 80, 200, 200), rect("a", 60, 120, 120, 40)]
    out = fit(elements, {"outer": "outer", "inner": "inner", "a": "a"},
              {"chart_type": "architecture", "groups": [
                  {"id": "outer", "members": []}, {"id": "inner", "parent_group_id": "outer", "members": ["a"]}]})
    assert (out["outer"]["x"], out["outer"]["y"], out["outer"]["width"], out["outer"]["height"]) == (0, 0, 600, 400)


def quadrant_scene(axis_class="axis"):
    frames = [rect(f"f{i}", (i % 2) * 400, (i // 2) * 400, 400, 400) for i in range(4)]
    item = rect("item", 40, 80, 140, 50, boundElements=[{"id": "t_item", "type": "text"}])
    items = [item, text("t_item", 50, 90, 120, 30, "item", "Dark mode", 18)]
    axes = [rect("hx", 900, 900, 120, 30, boundElements=[{"id": "t_hx", "type": "text"}]),
            text("t_hx", 900, 900, 60, 15, "hx", "Ease →", 10),
            rect("vx", 900, 0, 120, 30, boundElements=[{"id": "t_vx", "type": "text"}]),
            text("t_vx", 900, 0, 60, 15, "vx", "Impact ↑", 10)]
    id_map = {"q_tl": "f0", "q_tr": "f1", "q_bl": "f2", "q_br": "f3", "n": "item", "x": "hx", "y": "vx"}
    structure = {"chart_type": "quadrant",
                 "groups": [{"id": g, "members": ["n"] if g == "q_tl" else []} for g in ("q_tl", "q_tr", "q_bl", "q_br")],
                 "nodes": [{"id": "n", "label": "Dark mode"}, {"id": "x", "label": "Ease →", "class": axis_class},
                           {"id": "y", "label": "Impact ↑", "class": axis_class}],
                 "edges": []}
    manifest = {"type": "excalidraw/clipboard", "_meta": {"id_map": id_map}, "elements": frames + items + axes}
    return manifest, structure


def test_quadrant_axis_names_anchor_to_the_block_at_item_size():
    manifest, structure = quadrant_scene()
    assert place_captions("quadrant", structure, manifest["elements"], manifest["_meta"]["id_map"]) == 2
    by_id = {e["id"]: e for e in manifest["elements"]}
    hx, vx = by_id["hx"], by_id["vx"]
    assert hx["y"] == 800 + 24 and abs(hx["x"] + hx["width"] / 2 - 400) < 1e-6
    assert vx["x"] + vx["width"] == -24 and abs(vx["y"] + vx["height"] / 2 - 400) < 1e-6
    assert by_id["t_hx"]["fontSize"] == by_id["t_vx"]["fontSize"] == 18
    assert by_id["t_vx"]["textAlign"] == "right"


def test_axis_class_is_matched_case_insensitively_by_the_theme():
    manifest, structure = quadrant_scene(axis_class=" Axis ")
    themed = apply_design_theme(manifest, structure)
    by_id = {e["id"]: e for e in themed["elements"]}
    assert by_id["hx"]["strokeColor"] == by_id["hx"]["backgroundColor"] == "transparent"
    assert by_id["hx"]["y"] == 824


def test_layer_stack_rule_caption_sits_beside_the_stack_on_balanced_lines():
    bands = [rect(f"b{i}", 0, i * 110, 900, 110) for i in range(4)]
    rule = "Higher layers depend only on lower ones, never the reverse"
    elements = bands + [rect("r", 2000, 2000, 100, 20, boundElements=[{"id": "t_r", "type": "text"}]),
                        text("t_r", 2000, 2000, 100, 20, "r", rule, 12)]
    id_map = {f"l{i}": f"b{i}" for i in range(4)} | {"rule": "r"}
    structure = {"chart_type": "layer_stack", "groups": [{"id": f"l{i}", "members": []} for i in range(4)],
                 "nodes": [{"id": "rule", "label": rule, "class": "axis"}]}
    place_captions("layer_stack", structure, elements, id_map)
    by_id = {e["id"]: e for e in elements}
    host, caption = by_id["r"], by_id["t_r"]
    assert host["x"] == 900 + 32 and abs(host["y"] + host["height"] / 2 - 220) < 1e-6
    lines = caption["text"].split("\n")
    assert caption["originalText"] == rule and caption["fontSize"] == 16 and caption["textAlign"] == "left"
    assert len(lines) == 3 and max(map(len, lines)) - min(map(len, lines)) <= 6
