"""Helpers for loading curated diagram domain knowledge into agent prompts.

The pipeline runs three sequential agents (Structure → Styling → Layout) over a
shared conversation history. Repeating the same per-type identity / pattern
content in every turn wastes tokens, so this module separates two concerns:

* ``build_diagram_context(diagram_type)`` — the **shared** block: family
  identity, identity/usage cues, and the per-type slice extracted from
  ``type_patterns/`` file for the current diagram type. Injected once, in the Structure user message.

* ``build_stage_knowledge(diagram_type, stage)`` — only the **stage-specific
  delta**: per-stage rules from ``type_patterns/*.md``
  (common, structure, styling, layout).

Downstream agents pick up ``build_diagram_context`` from the conversation
history (Structure's user message), so they only need their own delta.

Note: the orthogonal ``design_expertise`` channel (memory-retrieved patterns
from ChromaDB) is **not** assembled here. It flows through its own state field
and its own ``{{design_expertise}}`` placeholder in the task prompt — see
``agentic_system/common/task_prompts.py``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from evo_diagram.agentic_system.common.diagram_types import (
    TYPE_PATTERNS_DIR,
    normalize_diagram_type,
    slugify as _slugify,
)


_SYSTEM_PROMPT_DIR = Path(__file__).resolve().parents[1] / "system_prompt"

GROUP_CONTAINMENT_PATH = _SYSTEM_PROMPT_DIR / "group_containment_reference.md"

STAGE_KEY_MAP = {
    "structure": "structure",
    "styling": "styling",
    "layout": "layout",
}

def _parse_rule_list(text: str) -> list[str]:
    """Extract top-level bullet rules from a Markdown section body.

    A new rule starts with either:
    - ``- `` at the beginning of a line (indent <= 2)
    - ``#### `` sub-heading

    Subsequent indented lines or blank lines belong to the same rule until
    the next starter.  ``####`` sub-headings and Markdown tables are kept
    intact inside their own rule instead of being swallowed into the previous
    bullet.
    """
    rules: list[str] = []
    current: list[str] = []
    in_rule = False

    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)

        is_subheading = stripped.startswith("#### ")
        is_bullet = stripped.startswith("- ") and indent <= 2

        if is_subheading or is_bullet:
            # Finish previous rule and start a new one
            if current:
                rules.append("\n".join(current).strip())
            current = [raw_line] if is_subheading else [stripped[2:]]
            in_rule = True
        elif in_rule:
            # Continue current rule (preserve original indentation)
            current.append(raw_line)

    if current:
        rules.append("\n".join(current).strip())

    return [r for r in rules if r]


def _parse_type_knowledge_markdown(text: str) -> Dict[str, Any]:
    """Parse a single ``type_patterns/*.md`` file into structured knowledge.

    Returns a dict with keys: ``common``, ``structure``, ``styling``,
    ``layout``.  Rule sections return lists of strings (top-level ``- ``
    bullets).  The raw Markdown body of the Common section is preserved
    under ``common_body`` so visual patterns (``#### `` sub-headings,
    ASCII diagrams, tables) can be extracted later.
    """
    sections: Dict[str, Any] = {}
    current_heading: Optional[str] = None
    current_body: list[str] = []

    for line in text.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()

            if current_heading:
                body = "\n".join(current_body).strip()
                if current_heading in ("Common", "Structure", "Styling", "Layout"):
                    sections[current_heading.lower()] = _parse_rule_list(body)
                    if current_heading == "Common":
                        sections["common_body"] = body

            current_heading = heading
            current_body = []
        elif line.startswith("#### ") and current_heading in (
            "Common", "Structure", "Styling", "Layout"
        ):
            # Sub-heading inside a main section — keep it in the body
            current_body.append(line)
        else:
            current_body.append(line)

    # Flush the last section
    if current_heading:
        body = "\n".join(current_body).strip()
        if current_heading in ("Common", "Structure", "Styling", "Layout"):
            sections[current_heading.lower()] = _parse_rule_list(body)
            if current_heading == "Common":
                sections["common_body"] = body

    return sections


@lru_cache(maxsize=1)
def load_domain_knowledge() -> Dict[str, Dict[str, Any]]:
    """Load curated domain knowledge from ``type_patterns/*.md`` files."""
    if not TYPE_PATTERNS_DIR.is_dir():
        return {}

    knowledge: Dict[str, Dict[str, Any]] = {}
    for filepath in sorted(TYPE_PATTERNS_DIR.glob("*.md")):
        type_key = filepath.stem
        text = filepath.read_text(encoding="utf-8").strip()
        # Strip the leading ``## Title`` line — it is not part of the data
        lines = text.splitlines()
        if lines and lines[0].startswith("## "):
            text = "\n".join(lines[1:]).strip()

        parsed = _parse_type_knowledge_markdown(text)
        if parsed:
            knowledge[type_key] = parsed

    return knowledge


def _read_optional_text(path: Path) -> str:
    """Read an optional markdown/text file if present."""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _extract_visual_patterns(body: str) -> str:
    """Extract all ``#### `` sub-sections from the Common body."""
    lines = body.splitlines()
    result: list[str] = []
    collecting = False
    for line in lines:
        if line.startswith("#### "):
            collecting = True
            result.append(line)
        elif collecting:
            result.append(line)
    return "\n".join(result).strip()


def get_diagram_pattern_slice(diagram_type: Optional[str]) -> str:
    """Return the per-type visual-pattern section, or empty string.

    Visual patterns are now embedded inside the ``Common`` section as a
    ``#### Visual Patterns`` sub-heading (or ``#### Visual Pattern: ...``
    sub-headings).  We extract them from ``common_body`` so they travel
    with the Common content instead of living in a separate section.
    """
    normalized = normalize_diagram_type(diagram_type)
    if not normalized:
        return ""
    knowledge = load_domain_knowledge()
    entry = knowledge.get(normalized)
    if not entry:
        return ""
    body = entry.get("common_body", "")
    if body:
        return _extract_visual_patterns(body)
    return ""


def _format_rule_block(title: str, rules: Iterable[str]) -> str:
    lines = [f"{title}:"]
    for rule in rules:
        if rule.startswith("#### "):
            # Sub-heading rule: render as bold label, not a bullet, so the
            # LLM sees a clear section break instead of a nested heading.
            parts = rule.split("\n", 1)
            heading = parts[0][5:].strip()
            lines.append(f"**{heading}**")
            if len(parts) > 1 and parts[1].strip():
                lines.append(parts[1].strip())
        else:
            lines.append(f"- {rule}")
    return "\n".join(lines)


def build_diagram_context(diagram_type: Optional[str]) -> str:
    """Compose the **shared** diagram-context block.

    Contains the per-type identity that every stage needs: family name,
    common identity cues, and the visual-pattern slice from the
    ``type_patterns/`` file for the current diagram type.
    Inject this once via the Structure user message — Styling and Layout
    inherit it through conversation history.
    """
    normalized_type = normalize_diagram_type(diagram_type)
    knowledge = load_domain_knowledge()

    parts = [
        "=== DIAGRAM CONTEXT ===",
        (
            "Zero-bloat reminder: treat the entries below as reusable type "
            "signals and invariants. Do not turn them into sample-specific "
            "coordinates or one-off patches."
        ),
    ]

    if normalized_type and normalized_type in knowledge:
        entry = knowledge[normalized_type]
        parts.append(f"Diagram family: {normalized_type}")

        common_rules = entry.get("common")
        if isinstance(common_rules, list) and common_rules:
            parts.append(_format_rule_block("Identity and usage cues", common_rules))
    else:
        fallback_type = normalized_type or "unknown"
        parts.append(
            f"No curated entry was found for diagram family `{fallback_type}`. "
            "Use the chart-type library, calibration anchors, subtype "
            "boundaries, and completeness checks to infer the correct "
            "structure."
        )

    pattern_slice = get_diagram_pattern_slice(diagram_type)
    if pattern_slice:
        display_name = normalized_type.replace("_", " ")
        parts.append(f"=== PATTERNS FOR {display_name.upper()} ===\n{pattern_slice}")

    return "\n\n".join(parts)


def build_stage_knowledge(
    diagram_type: Optional[str],
    stage: Optional[str],
    full_mode: bool = False,
) -> str:
    """Compose stage-specific knowledge for the given stage.

    When *full_mode* is ``False`` (default), returns only the rules for the
    requested stage — the standard delta-injection pattern.

    When *full_mode* is ``True``, returns **all** stage rules
    (structure + styling + layout) with the current stage listed first so
    it sits in the freshest attention position.

    Call ``build_diagram_context()`` separately if the shared identity block
    (``common`` rules + pattern slice) is also needed.
    """
    normalized_type = normalize_diagram_type(diagram_type)
    normalized_stage = STAGE_KEY_MAP.get(_slugify(stage or ""))
    knowledge = load_domain_knowledge()

    parts: list[str] = []

    if not normalized_type or normalized_type not in knowledge:
        return ""

    entry = knowledge[normalized_type]

    if full_mode:
        # Emit all stage rules, current stage first for freshest attention.
        all_stages = ["structure", "styling", "layout"]
        ordered_stages = []
        if normalized_stage and normalized_stage in all_stages:
            ordered_stages.append(normalized_stage)
            ordered_stages.extend(s for s in all_stages if s != normalized_stage)
        else:
            ordered_stages = list(all_stages)

        for stage_key in ordered_stages:
            stage_rules = entry.get(stage_key)
            if isinstance(stage_rules, list) and stage_rules:
                parts.append(
                    _format_rule_block(
                        f"{stage_key.capitalize()} priorities",
                        stage_rules,
                    )
                )
    else:
        if normalized_stage:
            stage_rules = entry.get(normalized_stage)
            if isinstance(stage_rules, list) and stage_rules:
                parts.append(
                    _format_rule_block(
                        f"{normalized_stage.capitalize()} priorities",
                        stage_rules,
                    )
                )
        else:
            for stage_key in ("structure", "styling", "layout"):
                stage_rules = entry.get(stage_key)
                if isinstance(stage_rules, list) and stage_rules:
                    parts.append(
                        _format_rule_block(
                            f"{stage_key.capitalize()} priorities",
                            stage_rules,
                        )
                    )

    return "\n\n".join(parts)


def get_group_containment_reference() -> str:
    """Load group containment reference for architecture Structure stage.

    Returns the trimmed element reference covering group background patterns,
    nested groups, and boundary derivation rules. Empty string if the file
    is missing.
    """
    return _read_optional_text(GROUP_CONTAINMENT_PATH)


# ---------------------------------------------------------------------------
# Router / Palette helpers
# ---------------------------------------------------------------------------

def get_selected_palette(palette_key: Optional[str]) -> str:
    """Return the formatted palette card for the given ``palette_key``.

    ``palette_key`` is the snake_case slug used as the canonical palette
    identifier across the pipeline (router output, styling state,
    spec.color_and_stroke_system.palette_name). Lookup is exact — no
    fuzzy / case-insensitive fallback. Returns an empty string if the
    key is missing or unknown so callers can apply their own default.
    Rendering is delegated to ``colorful.render_palette_card`` to keep a
    single source of truth.
    """
    if not palette_key:
        return ""
    from evo_diagram.agentic_system.generation_stage.styling.colorful import (
        PALETTES, render_palette_card,
    )
    if palette_key not in PALETTES:
        return ""
    return render_palette_card(palette_key)
