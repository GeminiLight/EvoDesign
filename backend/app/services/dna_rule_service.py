"""DNA rule persistence service."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNotFoundException
from app.db.base import utc_now
from app.models.dna_rule import DnaRule
from app.models.project import Project
from app.schemas.dna import DnaRuleSchema, DnaRulesPayload


DnaRuleIdFactory = Callable[[], str]
Clock = Callable[[], datetime]


class DnaRuleService:
    """Load and replace a user's project-scoped or global DNA rules."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        id_factory: DnaRuleIdFactory | None = None,
        clock: Clock = utc_now,
    ):
        self.db = db
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock

    async def get_rules(
        self,
        *,
        user_id: str,
        project_id: str | None,
    ) -> DnaRulesPayload:
        """Load DNA rules for one user and scope."""
        rows = await self._fetch_rows(user_id=user_id, project_id=project_id)
        return rows_to_payload(rows, project_id)

    async def replace_rules(
        self,
        *,
        user_id: str,
        payload: DnaRulesPayload,
    ) -> DnaRulesPayload:
        """Replace all DNA rules for one user and scope."""
        project_id = payload.project_id
        if project_id is not None:
            await self._require_owned_project(user_id=user_id, project_id=project_id)

        await self.db.execute(
            delete(DnaRule).where(
                DnaRule.user_id == user_id,
                DnaRule.project_id == project_id,
            )
        )

        rows = self._build_rows(user_id=user_id, payload=payload)
        if rows:
            self.db.add_all(rows)

        await self.db.flush()
        saved = await self._fetch_rows(user_id=user_id, project_id=project_id)
        return rows_to_payload(saved, project_id)

    async def _require_owned_project(self, *, user_id: str, project_id: str) -> None:
        """Reject project-scoped writes that target another user's project."""
        result = await self.db.execute(
            select(Project.project_id).where(
                Project.project_id == project_id,
                Project.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise ProjectNotFoundException()

    async def _fetch_rows(
        self,
        *,
        user_id: str,
        project_id: str | None,
    ) -> list[DnaRule]:
        result = await self.db.execute(
            select(DnaRule)
            .where(DnaRule.user_id == user_id, DnaRule.project_id == project_id)
            .order_by(DnaRule.created_at)
        )
        return list(result.scalars().all())

    def _build_rows(self, *, user_id: str, payload: DnaRulesPayload) -> list[DnaRule]:
        now = self.clock()
        rows: list[DnaRule] = []
        # Rule IDs come from the client, so a payload can repeat one and collide
        # on the primary key. Repeats get a fresh server-side ID instead.
        used_rule_ids: set[str] = set()
        for cabin_id, rule in iter_payload_rules(payload):
            rule_id = rule.rule_id or self.id_factory()
            if rule_id in used_rule_ids:
                rule_id = self.id_factory()
            used_rule_ids.add(rule_id)
            rows.append(
                DnaRule(
                    rule_id=rule_id,
                    user_id=user_id,
                    project_id=payload.project_id,
                    cabin_id=cabin_id,
                    title=rule.title,
                    preview=rule.preview,
                    source=rule.source,
                    enabled=rule.enabled,
                    pinned=rule.pinned,
                    usage_count=rule.usage_count,
                    created_at=now,
                    updated_at=now,
                )
            )
        return rows


def iter_payload_rules(payload: DnaRulesPayload) -> Iterable[tuple[str, DnaRuleSchema]]:
    """Yield payload rules with the cabin implied by their container."""
    yield from (("structure", rule) for rule in payload.structure)
    yield from (("style", rule) for rule in payload.style)
    yield from (("layout", rule) for rule in payload.layout)


def row_to_schema(row: DnaRule) -> DnaRuleSchema:
    """Convert a persisted DNA rule row to API schema."""
    updated_at = row.updated_at or datetime.now(timezone.utc)
    return DnaRuleSchema(
        rule_id=row.rule_id,
        cabin_id=row.cabin_id,
        title=row.title,
        preview=row.preview,
        source=row.source,
        enabled=row.enabled,
        pinned=row.pinned,
        usage_count=row.usage_count,
        updated_at=updated_at.isoformat(),
    )


def rows_to_payload(rows: list[DnaRule], project_id: str | None) -> DnaRulesPayload:
    """Group DNA rules into their API cabin lists."""
    payload = DnaRulesPayload(project_id=project_id)
    for row in rows:
        schema = row_to_schema(row)
        if row.cabin_id == "structure":
            payload.structure.append(schema)
        elif row.cabin_id == "style":
            payload.style.append(schema)
        elif row.cabin_id == "layout":
            payload.layout.append(schema)
    return payload
