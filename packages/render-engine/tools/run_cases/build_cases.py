"""Write hand-authored run cases that examples/configured-model lacks.

``concept_ml`` — a concept map (no concept-map artifacts exist in
examples/configured-model; the only attempt, t_concept_ty, failed). The case
has the same files a real run leaves behind (1_structure, 2_styling, 3_layout)
so tools/cassette_synth.py can answer Structure/Styling/Layout from it.

Usage: PYTHONPATH=. .venv/bin/python packages/render-engine/tools/run_cases/build_cases.py
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def write(case: str, files: dict) -> None:
    for rel, data in files.items():
        path = HERE / case / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def concept_ml() -> dict:
    core = ("machine_learning", "机器学习")
    anchors = [("supervised", "监督学习"), ("unsupervised", "无监督学习"), ("reinforcement", "强化学习")]
    leaves = [
        ("classification", "分类", "supervised"),
        ("regression", "回归", "supervised"),
        ("clustering", "聚类", "unsupervised"),
        ("dim_reduction", "降维", "unsupervised"),
        ("agent", "智能体", "reinforcement"),
        ("reward", "奖励信号", "reinforcement"),
    ]
    nodes = [{"id": core[0], "label": core[1], "class": "core_concept", "branch_id": None}]
    nodes += [{"id": i, "label": l, "class": "branch_anchor", "branch_id": i} for i, l in anchors]
    nodes += [{"id": i, "label": l, "class": "concept", "branch_id": b} for i, l, b in leaves]
    edges = [
        {"id": f"edge:{core[0]}2{i}", "source": core[0], "target": i, "label": "organized into",
         "relation_type": "hierarchy", "directionality": "directed", "evidence_basis": "structural"}
        for i, _ in anchors
    ]
    facts = [
        ("supervised", "包括", "classification", "composition", "监督学习包括分类"),
        ("supervised", "包括", "regression", "composition", "监督学习包括回归"),
        ("unsupervised", "包括", "clustering", "composition", "无监督学习包括聚类"),
        ("unsupervised", "包括", "dim_reduction", "composition", "无监督学习包括降维"),
        ("reinforcement", "训练", "agent", "composition", "强化学习训练智能体"),
        ("reward", "引导", "agent", "causal", "奖励信号引导智能体的行为"),
        ("dim_reduction", "常用于", "clustering", "dependency", "降维常用于聚类之前的预处理"),
    ]
    for source, label, target, relation, evidence in facts:
        edges.append({"id": f"edge:{source}2{target}", "source": source, "target": target, "label": label,
                      "relation_type": relation, "directionality": "directed", "evidence_basis": "explicit",
                      "evidence": evidence})
    structure = {"chart_type": "concept_map", "nodes": nodes, "edges": edges, "groups": []}
    spec = {
        "diagram_paradigm": {"chart_type": "concept_map", "confidence": "high", "primary_organizer": "radial",
                             "recognition_signal": "一个核心概念向三个学习范式分支展开，分支下列出具体任务。"},
        "semantic_typology": {"entities": [n["id"] for n in nodes]},
    }

    palette = {
        "core": ("#3F4A8A", "#DCE0F5"),
        "supervised": ("#2F6F5E", "#D5EDE4"),
        "unsupervised": ("#8A5A2B", "#F4E3CF"),
        "reinforcement": ("#7A3F6B", "#F0D9EA"),
    }
    styling = {}
    for node in nodes:
        branch = "core" if node["class"] == "core_concept" else node["branch_id"]
        stroke, fill = palette[branch]
        styling[node["id"]] = {
            "shape": "ellipse" if node["class"] == "core_concept" else "rectangle",
            "label": {"text": node["label"]},
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "strokeWidth": 3 if node["class"] != "concept" else 2, "roughness": 0,
        }
    for edge in edges:
        styling[edge["id"]] = {"strokeColor": "#4A5060"}
    styling_spec = {"visual_paradigm": "核心椭圆居中，三个分支以颜色区分。",
                    "color_and_stroke_system": {"palette_name": "blush_sage"}}

    boxes = {
        "machine_learning": (700, 420, 220, 90),
        "supervised": (320, 180, 180, 64), "unsupervised": (1120, 180, 200, 64), "reinforcement": (720, 720, 180, 64),
        "classification": (80, 80, 140, 56), "regression": (80, 300, 140, 56),
        "clustering": (1440, 80, 140, 56), "dim_reduction": (1440, 300, 140, 56),
        "agent": (440, 900, 140, 56), "reward": (1040, 900, 160, 56),
    }
    layout = {}
    for node in nodes:
        x, y, w, h = boxes[node["id"]]
        layout[node["id"]] = {**styling[node["id"]], "x": x, "y": y, "w": w, "h": h}

    def side(a: str, b: str) -> tuple:
        ax, ay, aw, ah = boxes[a]
        bx, by, bw, bh = boxes[b]
        dx, dy = (bx + bw / 2) - (ax + aw / 2), (by + bh / 2) - (ay + ah / 2)
        if abs(dx) >= abs(dy):
            return ("right", "left") if dx > 0 else ("left", "right")
        return ("bottom", "top") if dy > 0 else ("top", "bottom")

    for edge in edges:
        start, end = side(edge["source"], edge["target"])
        layout[edge["id"]] = {
            "strokeColor": "#4A5060",
            "start": {"elementId": edge["source"], "side": start},
            "end": {"elementId": edge["target"], "side": end},
            "routing": "curved", "startArrowhead": None, "endArrowhead": "arrow",
            **({"label": {"text": edge["label"]}} if edge["evidence_basis"] == "explicit" else {}),
        }
    layout_spec = {"canvas_use_plan": {"viewport": {"width": 1600, "height": 1000}, "primary_axis": "radial"}}
    return {
        "1_structure/structure_instantiation.json": structure,
        "1_structure/structure_specification.json": spec,
        "2_styling/styling_instantiation.json": styling,
        "2_styling/styling_specification.json": styling_spec,
        "3_layout/layout_instantiation.json": layout,
        "3_layout/layout_specification.json": layout_spec,
    }


if __name__ == "__main__":
    write("concept_ml", concept_ml())
    print("wrote", HERE / "concept_ml")
