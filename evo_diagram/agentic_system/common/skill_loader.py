"""
Skill Loader
============

Loads the EvoDiagram system prompt from ``evodiagram_prompt.md`` — a compact
anti-drift prompt (~2K tokens) that prevents semantic drift across the 3-stage
pipeline (Structure → Styling → Layout).

Universal styling rules (roughness, arrow conventions, color combinations)
are part of ``evodiagram_prompt.md`` itself.

Per-type knowledge is injected per-stage via ``build_stage_knowledge()`` in
the task prompt, NOT in the system prompt, so the system prompt stays
cacheable and identical for every agent.

Public surface
--------------
- ``EVODIAGRAM_SKILL_SYSTEM_PROMPT`` — str, the base system prompt (no type
  knowledge); shared by all agents.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

SYSTEM_PROMPT_DIR_NAME = "system_prompt"
MAIN_PROMPT_FILE = "evodiagram_prompt.md"


def _locate_skill_dir() -> Path:
    """Locate ``agentic_system/system_prompt/`` relative to this module."""
    prompt_dir = Path(__file__).resolve().parents[1] / SYSTEM_PROMPT_DIR_NAME
    if prompt_dir.is_dir():
        return prompt_dir
    raise FileNotFoundError(
        f"Could not locate '{SYSTEM_PROMPT_DIR_NAME}/' at {prompt_dir}. "
        "The prompt markdown files are expected under agentic_system/system_prompt."
    )


@lru_cache(maxsize=1)
def _load_base_system_prompt() -> str:
    """Assemble the base system prompt from evodiagram_prompt.md + digest files."""
    skill_dir = _locate_skill_dir()
    prompt_path = skill_dir / MAIN_PROMPT_FILE
    if not prompt_path.is_file():
        raise FileNotFoundError(f"System prompt file missing: {prompt_path}")

    prompt_text = prompt_path.read_text(encoding="utf-8").strip()

    divider = "\n\n" + ("=" * 80) + "\n\n"

    # Append diagram type digest so every agent knows the supported families
    diagram_type_digest_path = skill_dir / "diagram_type_digest.md"
    if diagram_type_digest_path.is_file():
        diagram_type_digest = diagram_type_digest_path.read_text(
            encoding="utf-8"
        ).strip()
        prompt_text += divider + diagram_type_digest

    # Append palette digest so every agent knows which palettes exist
    # and when each one fits. The styling agent receives the full card for
    # the selected key via its task prompt.
    palette_digest_path = skill_dir / "palette_digest.md"
    if palette_digest_path.is_file():
        palette_digest = palette_digest_path.read_text(encoding="utf-8").strip()
        prompt_text += divider + palette_digest

    return prompt_text


EVODIAGRAM_SKILL_SYSTEM_PROMPT: str = _load_base_system_prompt()


__all__ = [
    "EVODIAGRAM_SKILL_SYSTEM_PROMPT",
]
