"""Shared helpers for semantic IDs and manifest ``_meta.id_map``.

EvoDesign uses semantic IDs as the foreign keys between Structure, Styling,
Layout, Render, Verification, and Refiner. Renderable companion entries such
as ``g_lane:background`` or ``n_api:icon`` are still rooted in a real semantic
node/group/edge. Keeping the parsing rules here prevents each stage from
inventing a slightly different dialect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional


BACKGROUND_SUFFIX = ":background"
TITLE_SUFFIX = ":title"
LABEL_SUFFIX = ":label"
ICON_SUFFIX = ":icon"

GROUP_FRAME_SUFFIXES = (BACKGROUND_SUFFIX,)
GROUP_TITLE_SUFFIXES = (TITLE_SUFFIX, LABEL_SUFFIX)
COMPANION_ID_SUFFIXES = (
    BACKGROUND_SUFFIX,
    TITLE_SUFFIX,
    LABEL_SUFFIX,
    ICON_SUFFIX,
)

# Canvas-level captions that Styling or Layout sometimes add on their own.
# They are not part of the semantic graph and carry no relation, so dropping
# one never removes or invents a claim.
CANVAS_DECORATION_IDS = frozenset({
    "title", "subtitle", "caption", "heading",
    "diagram_title", "main_title", "canvas_title",
})


def drop_canvas_decorations(
    entries: Dict[str, Any], known_ids: set[str],
) -> tuple[Dict[str, Any], list[str]]:
    """Remove stand-alone canvas captions that no upstream stage declared.

    An id is dropped only when it is one of ``CANVAS_DECORATION_IDS`` and is
    not a real upstream id (a Structure node may legitimately be ``title``).
    Every other unknown id is left for the caller's strict validation.
    ``entries`` itself is returned when nothing is dropped.
    """
    dropped = [
        key for key in entries
        if isinstance(key, str) and key.strip().lower() in CANVAS_DECORATION_IDS
        and key not in known_ids
    ]
    if not dropped:
        return entries, []
    return {key: value for key, value in entries.items() if key not in dropped}, dropped


@dataclass(frozen=True)
class GroupIdMap:
    """Resolved group render IDs from a manifest id_map."""

    background_by_group: Dict[str, str]
    title_by_group: Dict[str, str]

    @property
    def background_ids(self) -> set[str]:
        return set(self.background_by_group.values())

    @property
    def title_ids(self) -> set[str]:
        return set(self.title_by_group.values())


def semantic_id_base(semantic_id: Any) -> Optional[str]:
    """Return the base semantic id for a companion key, otherwise the id itself."""
    if not isinstance(semantic_id, str) or not semantic_id.strip():
        return None
    for suffix in COMPANION_ID_SUFFIXES:
        if semantic_id.endswith(suffix):
            base = semantic_id[: -len(suffix)]
            return base or None
    return semantic_id


def companion_base_id(semantic_id: Any) -> Optional[str]:
    """Return the base id only when ``semantic_id`` uses a known companion suffix."""
    if not isinstance(semantic_id, str) or not semantic_id.strip():
        return None
    for suffix in COMPANION_ID_SUFFIXES:
        if semantic_id.endswith(suffix):
            base = semantic_id[: -len(suffix)]
            return base or None
    return None


def companion_id(base_id: str, suffix: str) -> str:
    """Build a companion semantic id from a base id and one canonical suffix."""
    if suffix not in COMPANION_ID_SUFFIXES:
        raise ValueError(f"Unknown semantic companion suffix: {suffix!r}")
    return f"{base_id}{suffix}"


def id_map_from_manifest(manifest: Mapping[str, Any]) -> Dict[str, str]:
    """Extract a string-to-string ``_meta.id_map`` from a manifest."""
    meta = manifest.get("_meta") if isinstance(manifest, Mapping) else None
    if not isinstance(meta, Mapping):
        return {}
    id_map = meta.get("id_map")
    if not isinstance(id_map, Mapping):
        return {}
    return {
        key: value
        for key, value in id_map.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def resolve_group_id_map(id_map: Mapping[str, Any]) -> GroupIdMap:
    """Resolve group background/title render IDs from semantic companion keys."""
    background_by_group: Dict[str, str] = {}
    title_by_group: Dict[str, str] = {}
    for key, value in id_map.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        for suffix in GROUP_FRAME_SUFFIXES:
            if key.endswith(suffix):
                base = key[: -len(suffix)]
                if base:
                    background_by_group[base] = value
                break
        else:
            for suffix in GROUP_TITLE_SUFFIXES:
                if key.endswith(suffix):
                    base = key[: -len(suffix)]
                    if base:
                        title_by_group[base] = value
                    break
    return GroupIdMap(
        background_by_group=background_by_group,
        title_by_group=title_by_group,
    )


def group_frame_render_id(id_map: Mapping[str, Any], group_id: Any) -> Optional[str]:
    """Return the rendered frame id for a semantic group id, if mapped."""
    if not isinstance(group_id, str) or not group_id:
        return None
    direct = id_map.get(group_id)
    if isinstance(direct, str) and direct:
        return direct
    background = id_map.get(companion_id(group_id, BACKGROUND_SUFFIX))
    return background if isinstance(background, str) and background else None


def reverse_id_map(id_map: Mapping[str, Any]) -> Dict[str, str]:
    """Build rendered element id -> raw semantic id from an id_map."""
    return {
        value: key
        for key, value in id_map.items()
        if isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
    }


def reverse_base_id_map(id_map: Mapping[str, Any]) -> Dict[str, str]:
    """Build rendered element id -> base semantic id from an id_map."""
    reverse: Dict[str, str] = {}
    for key, value in id_map.items():
        if not isinstance(value, str) or not value:
            continue
        base = semantic_id_base(key)
        if base is not None:
            reverse[value] = base
    return reverse


# A JS object moves keys that look like array indices ("0", "7", ...) ahead of
# all other keys, in ascending order, so a semantic id of that shape would
# reorder every id-keyed dict in the TypeScript render engine and change the
# output. Such ids are rejected at Structure and at the render entry.
_ARRAY_INDEX_LIMIT = 2**32 - 1


def is_integer_like_id(value: Any) -> bool:
    """Whether ``value`` is a string JS would treat as an array index."""
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and (value == "0" or not value.startswith("0"))
        and int(value) < _ARRAY_INDEX_LIMIT
    )


def integer_like_semantic_ids(
    structure: Optional[Mapping[str, Any]], layout: Optional[Mapping[str, Any]],
) -> list[str]:
    """Integer-like Structure ids and Layout keys, in first-seen order."""
    found: list[str] = []
    if isinstance(structure, Mapping):
        for category in ("nodes", "edges", "groups"):
            items = structure.get(category)
            for item in items if isinstance(items, list) else []:
                item_id = item.get("id") if isinstance(item, Mapping) else None
                if is_integer_like_id(item_id) and item_id not in found:
                    found.append(item_id)
    if isinstance(layout, Mapping):
        for key in layout:
            if is_integer_like_id(key) and key not in found:
                found.append(key)
    return found


def ensure_no_integer_like_semantic_ids(
    structure: Optional[Mapping[str, Any]], layout: Optional[Mapping[str, Any]],
) -> None:
    found = integer_like_semantic_ids(structure, layout)
    if found:
        raise ValueError(
            "Semantic ids must not be bare integers (got "
            + ", ".join(repr(item) for item in found)
            + "); use descriptive ids such as 'n_login'."
        )


__all__ = [
    "BACKGROUND_SUFFIX",
    "TITLE_SUFFIX",
    "LABEL_SUFFIX",
    "ICON_SUFFIX",
    "GROUP_FRAME_SUFFIXES",
    "GROUP_TITLE_SUFFIXES",
    "COMPANION_ID_SUFFIXES",
    "GroupIdMap",
    "semantic_id_base",
    "companion_base_id",
    "companion_id",
    "id_map_from_manifest",
    "resolve_group_id_map",
    "group_frame_render_id",
    "reverse_id_map",
    "reverse_base_id_map",
    "is_integer_like_id",
    "integer_like_semantic_ids",
    "ensure_no_integer_like_semantic_ids",
]
