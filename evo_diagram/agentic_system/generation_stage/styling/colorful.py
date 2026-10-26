"""
Color palette catalog for the EvoDiagram styling agent.

Design principle (rev 2026-04-25 — fixes the dark-on-dark contrast
failure observed on Corporate Navy Gold concept maps):

    Every node FILL is light. Every PAIRED stroke is dark.

Catalog data is loaded from ``palette_catalog/*.md`` under
``agentic_system/system_prompt/``. Each file is a standalone Markdown
document with prose guidance fields, hex values, and a fill-family
table.

This module loads + validates all palettes at import time and exposes:

- ``PALETTES`` — dict of key → palette spec.
- ``PALETTE_KEYS`` — list of valid palette keys (alphabetical order).
- ``PALETTE_DIGEST_TABLE`` — a markdown table for embedding into router
  and system prompts.
- ``render_palette_card(key)`` — the single canonical renderer for a
  full palette card, used by the styling agent's task prompt.
- ``palette_hexes(key)`` — utility returning the set of hex codes any
  node/edge in that palette is allowed to emit (used by the contrast
  guard and any future validator).

All ``fill`` × ``#1e1e1e`` text-contrast pairs were verified ≥4.5:1
WCAG AA at design time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_DIR = (
    Path(__file__).resolve().parents[2] / "system_prompt"
)
_CATALOG_DIR = _SYSTEM_PROMPT_DIR / "palette_catalog"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_REQUIRED_PALETTE_FIELDS = (
    "display_name",
    "mood",
    "use_when",
    "avoid_when",
    "reference_anchors",
    "balance_guidance",
    "common_mistakes",
    "digest",
    "canvas",
    "border_default",
    "accent_edge",
    "fill_families",
)

_REQUIRED_FAMILY_FIELDS = ("name", "fill", "stroke", "voice")


def _validate_hex(value: Any, where: str) -> None:
    if not (isinstance(value, str) and _HEX_RE.match(value)):
        raise ValueError(
            f"palette_catalog: invalid hex at {where}: {value!r} "
            f"(expected '#RRGGBB')"
        )


def _validate_palette(key: str, p: Dict[str, Any]) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(
            f"palette_catalog: invalid palette key {key!r} "
            f"(must be snake_case, ^[a-z][a-z0-9_]*$)"
        )

    for field in _REQUIRED_PALETTE_FIELDS:
        if field not in p:
            raise ValueError(
                f"palette_catalog: palette {key!r} missing field "
                f"{field!r}"
            )

    if not isinstance(p["display_name"], str) or not p["display_name"].strip():
        raise ValueError(
            f"palette_catalog: palette {key!r} has empty/non-string display_name"
        )

    _validate_hex(p["canvas"], f"{key}.canvas")
    _validate_hex(p["border_default"], f"{key}.border_default")
    _validate_hex(p["accent_edge"], f"{key}.accent_edge")

    families = p["fill_families"]
    if not isinstance(families, list) or len(families) < 4:
        raise ValueError(
            f"palette_catalog: palette {key!r} must have >=4 "
            f"fill_families (got {len(families) if isinstance(families, list) else '?'})"
        )

    seen_names: Set[str] = set()
    for i, fam in enumerate(families):
        if not isinstance(fam, dict):
            raise ValueError(
                f"palette_catalog: {key}.fill_families[{i}] is not a dict"
            )
        for field in _REQUIRED_FAMILY_FIELDS:
            if field not in fam:
                raise ValueError(
                    f"palette_catalog: {key}.fill_families[{i}] "
                    f"missing field {field!r}"
                )
        _validate_hex(fam["fill"],   f"{key}.fill_families[{i}].fill")
        _validate_hex(fam["stroke"], f"{key}.fill_families[{i}].stroke")
        if fam["name"] in seen_names:
            raise ValueError(
                f"palette_catalog: {key} has duplicate family name "
                f"{fam['name']!r}"
            )
        seen_names.add(fam["name"])


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(r"^\*\*(\w+):\*\*\s*(.*)$")


def _parse_palette_markdown(text: str) -> Dict[str, Any]:
    """Parse a single ``palette_catalog/*.md`` file into a structured dict."""
    lines = text.splitlines()

    # Extract key from first line: ## key
    key = ""
    if lines and lines[0].startswith("## "):
        key = lines[0][3:].strip()

    # Extract **field:** value pairs (support multi-line values)
    fields: Dict[str, str] = {}
    current_field: Optional[str] = None
    current_value: List[str] = []
    fill_families_start: Optional[int] = None

    for i, line in enumerate(lines):
        if line.startswith("### Fill Families"):
            if current_field is not None:
                fields[current_field] = "\n".join(current_value).strip()
                current_field = None
            fill_families_start = i
            break

        m = _FIELD_RE.match(line)
        if m:
            if current_field is not None:
                fields[current_field] = "\n".join(current_value).strip()
            current_field = m.group(1)
            current_value = [m.group(2)]
        elif current_field is not None:
            current_value.append(line)

    if current_field is not None:
        fields[current_field] = "\n".join(current_value).strip()

    # Strip backticks from hex values
    for hex_field in ("canvas", "border_default", "accent_edge"):
        if hex_field in fields:
            fields[hex_field] = fields[hex_field].strip().strip("`")

    # Parse Fill Families table
    fill_families: List[Dict[str, str]] = []
    if fill_families_start is not None:
        table_lines: List[str] = []
        for line in lines[fill_families_start + 1:]:
            stripped = line.strip()
            if stripped.startswith("|"):
                table_lines.append(stripped)
            elif stripped == "":
                continue
            else:
                break

        # Skip header and separator rows
        for row_line in table_lines[2:]:
            cells = [c.strip() for c in row_line.strip("|").split("|")]
            if len(cells) == 4:
                fill_families.append({
                    "name": cells[0],
                    "fill": cells[1].strip("`"),
                    "stroke": cells[2].strip("`"),
                    "voice": cells[3],
                })

    return {
        "key": key,
        "display_name": fields.get("display_name", ""),
        "mood": fields.get("mood", ""),
        "use_when": fields.get("use_when", ""),
        "avoid_when": fields.get("avoid_when", ""),
        "reference_anchors": fields.get("reference_anchors", ""),
        "balance_guidance": fields.get("balance_guidance", ""),
        "common_mistakes": fields.get("common_mistakes", ""),
        "digest": fields.get("digest", ""),
        "canvas": fields.get("canvas", ""),
        "border_default": fields.get("border_default", ""),
        "accent_edge": fields.get("accent_edge", ""),
        "fill_families": fill_families,
    }


# ---------------------------------------------------------------------------
# Digest table builder
# ---------------------------------------------------------------------------

def _build_digest_table(palettes: Dict[str, Dict[str, Any]]) -> str:
    """Build the concise palette digest table from loaded Markdown data."""
    rows = [
        "| key | display_name | use this when |",
        "|---|---|---|",
    ]
    for key in sorted(palettes.keys()):
        p = palettes[key]
        digest = p.get("digest", p.get("use_when", ""))
        # Truncate overly long digests
        if len(digest) > 120:
            digest = digest[:117] + "..."
        rows.append(
            f"| `{key}` | {p['display_name']} | {digest} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Catalog loader (with validation)
# ---------------------------------------------------------------------------

def _load_catalog() -> Tuple[Dict[str, Dict[str, Any]], str]:
    if not _CATALOG_DIR.is_dir():
        raise FileNotFoundError(
            f"palette_catalog directory missing: {_CATALOG_DIR}"
        )

    palettes: Dict[str, Dict[str, Any]] = {}
    for filepath in sorted(_CATALOG_DIR.glob("*.md")):
        text = filepath.read_text(encoding="utf-8")
        parsed = _parse_palette_markdown(text)
        key = parsed.get("key") or filepath.stem
        parsed["key"] = key
        _validate_palette(key, parsed)
        palettes[key] = parsed

    if len(palettes) < 12:
        raise ValueError(
            f"palette_catalog: expected at least the baseline catalog size "
            f"(12 palettes), got {len(palettes)}"
        )

    table_block = _build_digest_table(palettes)
    return palettes, table_block


PALETTES, PALETTE_DIGEST_TABLE = _load_catalog()
PALETTE_KEYS: List[str] = list(PALETTES.keys())


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------

def palette_hexes(palette_key: str) -> Set[str]:
    """Return the lowercase set of hex codes any element in this palette
    is allowed to emit. Used by the contrast guard and validators.
    """
    p = PALETTES[palette_key]
    out: Set[str] = {
        str(p["canvas"]).lower(),
        str(p["border_default"]).lower(),
        str(p["accent_edge"]).lower(),
    }
    for fam in p["fill_families"]:
        out.add(str(fam["fill"]).lower())
        out.add(str(fam["stroke"]).lower())
    return out


def render_palette_card(palette_key: str) -> str:
    """Render the full palette card (markdown) for one palette.

    This is the single canonical renderer used by the styling task
    prompt. The card carries the prose guidance fields (``use_when``,
    ``avoid_when``, ``reference_anchors``, ``balance_guidance``,
    ``common_mistakes``) plus the per-family ``voice`` strings so the
    styling agent sees what each family is FOR inside this palette.

    Raises ``KeyError`` if ``palette_key`` is not a valid catalog key —
    callers MUST validate against ``PALETTE_KEYS`` (or fall back to a
    known-good default) before calling.
    """
    p = PALETTES[palette_key]
    lines = [
        f"#### {p['display_name']} (`{palette_key}`)",
        f"*{p['mood']}*",
        f"- **Use when:** {p['use_when']}",
        f"- **Avoid when:** {p['avoid_when']}",
        f"- **Reference anchors:** {p['reference_anchors']}",
        f"- **Balance guidance:** {p['balance_guidance']}",
        f"- **Common mistakes:** {p['common_mistakes']}",
        f"- canvas: `{p['canvas']}`  ·  border_default: `{p['border_default']}`  ·  accent_edge: `{p['accent_edge']}`",
        "- fill_families:",
    ]
    for fam in p["fill_families"]:
        lines.append(
            f"    - **{fam['name']}** — fill `{fam['fill']}` + stroke `{fam['stroke']}` — {fam['voice']}"
        )
    return "\n".join(lines)


__all__ = [
    "PALETTES",
    "PALETTE_KEYS",
    "PALETTE_DIGEST_TABLE",
    "render_palette_card",
    "palette_hexes",
]
