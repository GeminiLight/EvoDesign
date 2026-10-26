"""Carry the user's design intent unchanged across every quality stage."""
import json
from typing import Any

ICONS_DISABLED_CONSTRAINT = "Node icons are disabled. Do not add or recommend them."


def icons_disabled(constraints: str) -> bool:
    """Honor the explicit web toggle without guessing intent from free text."""
    try:
        return json.loads(constraints or "{}").get("icons") == ICONS_DISABLED_CONSTRAINT
    except (ValueError, TypeError, AttributeError):
        return False


def build_design_constraints(*, source_text: str = "", requirements: str = "",
                             design_expertise: str = "", diagram_type: str | None = None,
                             use_icons: bool | None = None,
                             locked_nodes: list[str] | None = None) -> str:
    # No extra model call: these are authoritative inputs, not inferred advice.
    data: dict[str, Any] = {
        "source_and_explicit_design_requests": source_text,
        "requirements": requirements,
        "user_design_preferences": design_expertise,
        "diagram_type": diagram_type,
        "locked_element_ids": locked_nodes or [],
    }
    if use_icons is not None:
        data["icons"] = ("Optional small icons on selected key nodes only. Partial coverage is intentional; "
                         "obey any explicitly named inclusions/exclusions. Do not demand icons everywhere."
                         if use_icons else ICONS_DISABLED_CONSTRAINT)
    return json.dumps(data, ensure_ascii=False)


def constraint_prompt(constraints: str | None) -> str:
    if not constraints:
        return ""
    return ("\nUSER DESIGN CONSTRAINTS (preserve throughout review and refinement):\n"
            + constraints + "\nExplicit user choices take priority over generic aesthetic preferences. "
            "Do not penalize requested partial icon coverage, palette or layout direction. "
            "Preserve entities, edge directions, labels and feedback loops. "
            "Report a constraint violation only with visible, concrete evidence.\n")


def locked_scene_elements(manifest: dict, constraints: str) -> dict:
    """Include the locked node's text/icon; derived connector paths may move."""
    try:
        ids = set(json.loads(constraints or "{}").get("locked_element_ids", []))
    except (ValueError, TypeError):
        ids = set()
    id_map = (manifest.get("_meta") or {}).get("id_map") or {}
    ids.update(id_map[key] for key in list(ids) if key in id_map)
    fields = ("x", "y", "width", "height", "angle", "text", "originalText", "isDeleted",
              "strokeColor", "backgroundColor", "fontSize", "fontFamily", "opacity", "fileId")
    protected = {}
    for item in manifest.get("elements", []):
        icon = (item.get("customData") or {}).get("evoDesignIcon") or {}
        if (item.get("id") in ids or item.get("containerId") in ids
                or isinstance(icon, dict) and icon.get("hostId") in ids):
            protected[item["id"]] = {key: item.get(key) for key in fields}
    return protected
