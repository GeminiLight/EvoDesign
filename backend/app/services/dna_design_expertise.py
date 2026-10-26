"""Format stored DNA rules into generation-time design expertise text.

"Your DNA" rules are the user's persisted design preferences. This module
turns the enabled rules of a scope (global or one project) into a single
prompt segment that the workflow engine receives as the caller-provided
``design_expertise`` — the highest-priority slot in
``Text2DiagramWorkflow.build_design_expertise``, ahead of retrieved design
memory and stored user-preference memory.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from app.db.session import create_db_session
from app.schemas.dna import DnaRulesPayload
from app.services.dna_rule_service import DnaRuleService, iter_payload_rules


DNA_SECTION_HEADER = "=== USER DESIGN DNA ==="
DNA_SECTION_FOOTER = "=== END USER DESIGN DNA ==="
# Prompt-size guards: a large rule library must not crowd out the document
# context, so injection is capped and each preview is truncated.
MAX_INJECTED_DNA_RULES = 20
MAX_DNA_PREVIEW_CHARS = 200

SessionFactory = Callable[[], Any]


def _single_line(value: str) -> str:
    """Collapse whitespace so each rule renders as exactly one bullet line."""
    return " ".join(value.split())


def format_dna_design_expertise(payload: DnaRulesPayload) -> str:
    """Return the prompt segment for a scope's enabled DNA rules.

    Rules keep the service's ordering convention (cabin order
    structure -> style -> layout, created_at within each cabin). At most
    MAX_INJECTED_DNA_RULES rules are rendered and previews are truncated to
    MAX_DNA_PREVIEW_CHARS. Returns "" when nothing is injectable, so callers
    never hand an empty section to the prompt.
    """
    lines: list[str] = []
    for _cabin_id, rule in iter_payload_rules(payload):
        if not rule.enabled:
            continue
        if len(lines) >= MAX_INJECTED_DNA_RULES:
            break
        title = _single_line(rule.title)
        preview = _single_line(rule.preview)[:MAX_DNA_PREVIEW_CHARS]
        if not title and not preview:
            continue
        lines.append(f"- {title}: {preview}" if title and preview else f"- {title or preview}")

    if not lines:
        return ""
    return "\n".join([DNA_SECTION_HEADER, *lines, DNA_SECTION_FOOTER])


async def load_dna_design_expertise(
    *,
    user_id: str | None,
    project_id: str | None = None,
    session_factory: SessionFactory = create_db_session,
) -> str:
    """Load a user's DNA rules and format them as design expertise text.

    Guests (``user_id is None``) have no DNA rules and are skipped without
    touching the database. Any lookup failure degrades to "" with a warning:
    DNA is an enhancement, and generation must never fail because of it.
    """
    if not user_id:
        return ""

    try:
        async with session_factory() as db:
            payload = await DnaRuleService(db).get_rules(
                user_id=user_id,
                project_id=project_id,
            )
    except Exception as exc:
        logger.warning(
            "DNA rule lookup failed; generating without user DNA: {}", exc
        )
        return ""

    return format_dna_design_expertise(payload)
