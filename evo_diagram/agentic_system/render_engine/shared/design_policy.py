"""Conservative boundaries for automatic visual treatments."""
import json


def preserve_design(manifest: dict, constraints: str) -> bool:
    """Saved locks and explicit DNA take priority over an automatic theme."""
    if any(element.get("locked") for element in manifest.get("elements", [])):
        return True
    try:
        policy = json.loads(constraints or "{}")
        return bool(policy.get("user_design_preferences") or policy.get("locked_element_ids"))
    except (ValueError, TypeError, AttributeError):
        return bool(constraints)
