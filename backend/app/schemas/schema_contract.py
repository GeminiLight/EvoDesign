from __future__ import annotations

from typing import Literal, cast


SchemaEditor = Literal["excalidraw", "tldraw", "manual"]
DEFAULT_SCHEMA_EDITOR: SchemaEditor = "excalidraw"
SUPPORTED_SCHEMA_EDITORS: tuple[SchemaEditor, ...] = (
    "excalidraw",
    "tldraw",
    "manual",
)
REPLACE_SCHEMA_EDITORS: frozenset[SchemaEditor] = frozenset(
    ("excalidraw", "tldraw")
)


def normalize_schema_editor(editor: str | None) -> SchemaEditor | None:
    """Return a supported schema editor identifier, if one was supplied."""
    normalized = (editor or "").strip().lower()
    if normalized in SUPPORTED_SCHEMA_EDITORS:
        return cast(SchemaEditor, normalized)
    return None
