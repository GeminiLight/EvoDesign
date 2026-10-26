"""Shared helpers for semantic IDs and manifest ``_meta.id_map``.

EvoDiagram uses semantic IDs as the foreign keys between Structure, Styling,
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
]
