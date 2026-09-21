"""Prompts for the single-shot VLM refiner call.

The refiner prompt is intentionally compact: the model receives the 10-op edit
DSL, objective findings, and critique context, then returns a JSON edit list.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


MAX_MANIFEST_SUMMARY_ELEMENTS = 120


REFINER_LLM_SYSTEM_PROMPT = """You improve rendered Excalidraw diagrams through small, evidence-based edits. Fix visible defects while preserving clear composition and faithful relationships. A successful pass may need only one edit, or no edits.

You will receive:
1. A rendered PNG of the current diagram.
2. A list of objective findings from a rule-based verifier (some MAY have
   been auto-fixed already — only REMAINING findings are shown).
3. The diagram's subjective critique across structure / styling / layout.
4. A compact element summary with geometry, current styles, semantic roles,
   group membership, and connector endpoints.
5. The history of edits already applied this iteration cycle.

Your job: emit a JSON LIST of primitive edit ops that, when applied, will
move the diagram closer to a clean, well-aligned, readable state.

You have ONLY these 10 ops:

  {"op": "set_position",         "id": "<elem_id>", "payload": {"x": 100, "y": 200},                                "rationale": "..."}
  {"op": "set_size",             "id": "<elem_id>", "payload": {"width": 180, "height": 80},                       "rationale": "..."}
  {"op": "set_style",            "id": "<elem_id>", "payload": {"backgroundColor": "#dbeafe"},                     "rationale": "..."}
       /* set_style payload keys: backgroundColor, strokeColor, strokeWidth, strokeStyle, fillStyle, opacity, fontSize, textAlign */
  {"op": "set_text",             "id": "<elem_id>", "payload": {"text": "..."},                                    "rationale": "..."}
  {"op": "delete_element",       "id": "<elem_id>", "payload": {},                                                  "rationale": "..."}
       /* delete_element REJECTED if element has boundElements, containerId, or incoming arrows */
  {"op": "clear_arrow_binding",  "id": "<arrow_id>","payload": {"side": "start"},                                  "rationale": "..."}
  {"op": "clear_container_binding","id": "<text_id>","payload": {"container_id": "<missing_or_stale_container_id>"}, "rationale": "..."}
  {"op": "append_bound_element", "id": "<elem_id>", "payload": {"bound_id": "<arrow_id>", "type": "arrow"},        "rationale": "..."}
  {"op": "remove_bound_element", "id": "<elem_id>", "payload": {"bound_id": "<missing_or_stale_id>"},              "rationale": "..."}
  {"op": "set_index",            "id": "<elem_id>", "payload": {"index": "a00000"},                                "rationale": "..."}

Hard rules:
- Use ONLY manifest-summary ids as edit targets. For stale-reference payloads
  such as bound_id or container_id, use the exact missing id from the finding.
- Each edit must address a SPECIFIC finding or critique point, named in the
  rationale. Vague rationales like "improve layout" are rejected.
- Treat subjective critique as a hypothesis to check against the current
  PNG and semantic roles. Do not apply a suggestion that removes meaning,
  breaks an already clear alignment, or fixes a defect no longer visible.
- Do not fix things the deterministic pass already handled. The remaining
  findings list is what's left.
- For overlap: move the smaller element OR the more recently added one.
- For arrow crossings: prefer moving endpoint shapes (set_position) rather
  than deleting arrows.
- For generated diagrams with semantic connectors, moving/resizing shapes
  automatically recomputes connector paths. Do not separately translate arrow
  elements or detach valid bindings to chase their old coordinates. Move the
  endpoint or obstacle shapes and let routing maintain the connections.
- Group backgrounds identify their member_ids. A background is not a concept
  node: moving it alone does not move its contents. Keep every member inside
  its original group, with space for the heading. Keep different groups apart.
- A fact_bearing_section_heading_keep_border is also a collective relation
  endpoint. Preserve its visible outline and contrast; making it blend into
  the frame would leave its connector floating. It may differ from navigation-only headings.
- Navigation headings and collective fact endpoints have different roles.
  Do not add borders to every heading merely to match a fact endpoint.
- Preserve established rows, columns, and balanced group margins. Shortening
  one connector is not an improvement if it pushes an otherwise centered
  group against one side. A perimeter route can be appropriate when a
  shorter path would cross nodes or other relationships.
- Adjust typography consistently across labels with the same role. Compare
  current font sizes before editing; predicates should remain subordinate
  to concept labels, section headings, and the main title.
- Preserve the meaning and visibility of nodes, predicates, and semantic
  connectors. Never hide a fact with opacity=0, erase its label, or change a
  dependency/association to a causal link for aesthetic reasons. Opacity-zero
  organizer connectors are intentionally expressed by group containment.
- delete_element is BLOCKED on connected elements. Before deleting, use
  clear_arrow_binding to disconnect arrows first, then delete if orphaned.
- Use clear_container_binding for text whose containerId points to a missing
  or stale container; do not delete the text just to clear the reference.
- Output a JSON ARRAY only. No prose, no markdown fences. An empty array
  means "no fix needed; converged".

VISUAL REVIEW — Inspect the PNG for visible issues the verifier may have missed.
These are checks, not a required list of changes:
- Micro-misalignments: elements in the same row/column that are off by > 2px.
- Semantic inconsistency: similar entities with different colors/shapes.
- Text hierarchy: titles and labels using the same font size.
- Low contrast: text that is hard to read against its background.
- Orphan whitespace: large empty areas that break visual flow.
- Edge clarity: arrows with ambiguous endpoints or unnecessarily long routes.

COMPOUND FIXES — Prefer edits that solve multiple issues simultaneously:
- Example: moving a node to eliminate overlap AND improve row alignment.
- Example: resizing a group background to fix containment AND reduce whitespace.

PRIORITY ORDER — Apply edits by impact, highest first:
  1. Critical/major objective findings (overlap, out-of-canvas, broken binding)
  2. Structural readability issues (alignment, spacing, visual hierarchy)
  3. Styling improvements (contrast, semantic color, font size hierarchy)
  4. Minor polish (micro-adjustments, consistency nits)
Do NOT apply a minor cosmetic edit if a major layout issue remains unfixed.

If you can't fix something with these 10 ops, leave it alone.
"""


def build_refiner_user_prompt(
    chart_type: Optional[str],
    remaining_findings: List[Dict[str, Any]],
    critique: Optional[Dict[str, Any]],
    manifest_summary: List[Dict[str, Any]],
    previous_attempts: Optional[List[Dict[str, Any]]] = None,
    iteration: int = 1,
    max_iterations: int = 3,
) -> str:
    """Assemble the text part of the multimodal user message."""
    lines = [
        f"Iteration {iteration}/{max_iterations}.",
    ]
    if chart_type:
        lines.append(f"Declared chart_type: {chart_type}")

    lines.append("")
    lines.append(f"Remaining objective findings ({len(remaining_findings)}):")
    if remaining_findings:
        for f in remaining_findings:
            sev = f.get("severity", "?")
            cat = f.get("category", "?")
            eid = f.get("element_id") or "-"
            msg = (f.get("message") or "")[:160]
            lines.append(f"  [{sev}] {cat} ({eid}): {msg}")
            location = f.get("location")
            if location:
                loc_json = json.dumps(location, ensure_ascii=False, sort_keys=True)[:240]
                lines.append(f"      location={loc_json}")
    else:
        lines.append("  (none — no objective issues remain)")

    lines.append("")
    if critique:
        for dim in ("structure", "styling", "layout"):
            d = critique.get(dim) or {}
            score = d.get("score", "?")
            weaknesses = d.get("weaknesses") or []
            if weaknesses:
                lines.append(f"{dim.title()} (score={score}):")
                for w in weaknesses[:3]:
                    lines.append(f"  - {w}")
        if critique.get("summary"):
            lines.append(f"Overall: {critique['summary']}")
    else:
        lines.append("(no subjective critique provided this run)")

    lines.append("")
    lines.append("Manifest summary:")
    # Use the same budget as build_manifest_summary; a second smaller cap
    # silently hid the final relationship labels of ordinary overview diagrams.
    for entry in manifest_summary[:MAX_MANIFEST_SUMMARY_ELEMENTS]:
        eid = entry.get("id", "?")
        etype = entry.get("type", "?")
        x, y, w, h = entry.get("bbox", [0, 0, 0, 0])
        text = (entry.get("text") or "").replace("\n", " ")[:60]
        lines.append(
            f"  {eid:24s} {etype:9s} x={x:>5.0f} y={y:>5.0f} w={w:>5.0f} h={h:>5.0f}  text={text!r}"
        )
        context = {key: value for key, value in entry.items() if key not in {"id", "type", "bbox", "text"}}
        if context:
            lines.append("    " + json.dumps(context, ensure_ascii=False, sort_keys=True))
    if len(manifest_summary) > MAX_MANIFEST_SUMMARY_ELEMENTS:
        lines.append(f"  … ({len(manifest_summary) - MAX_MANIFEST_SUMMARY_ELEMENTS} more elements omitted)")

    if previous_attempts:
        lines.append("")
        lines.append("Edits already applied this cycle (do NOT re-apply identical edits):")
        for log in previous_attempts:
            it = log.get("iteration", "?")
            for outcome_kind in ("deterministic_edits", "llm_edits"):
                outs = log.get(outcome_kind, [])
                for o in outs[:6]:
                    edit = o.get("edit", {})
                    applied = "✓" if o.get("applied") else "✗"
                    lines.append(
                        f"  iter{it} {outcome_kind[:4]} {applied} "
                        f"{edit.get('op')}({edit.get('id')}) → {edit.get('rationale', '')[:60]}"
                    )

    lines.append("")
    lines.append("Return ONLY a JSON array of edit ops. No markdown fences, no prose.")
    return "\n".join(lines)


__all__ = [
    "REFINER_LLM_SYSTEM_PROMPT",
    "build_refiner_user_prompt",
]
