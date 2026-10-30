"""Shared saved document and effective constraints, independent of clients."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.dna_rule import DnaRule
from app.services.agent_contract import AgentError


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


async def owned_project(db: AsyncSession, user_id: str, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.project_id == project_id, Project.user_id == user_id)
                               .execution_options(populate_existing=True))).scalar_one_or_none()
    if project is None:
        raise AgentError('project_missing', 'Project not found', 404)
    return project


async def effective_constraints(db: AsyncSession, project: Project) -> dict[str, Any]:
    rows = list((await db.execute(select(DnaRule).where(DnaRule.user_id == project.user_id,
                 (DnaRule.project_id == project.project_id) | (DnaRule.project_id.is_(None)))
                 .order_by(DnaRule.cabin_id, DnaRule.created_at, DnaRule.rule_id))).scalars())
    project_rules = [r for r in rows if r.project_id == project.project_id]
    chosen = project_rules or [r for r in rows if r.project_id is None]
    rules = [{'cabin': r.cabin_id, 'title': r.title, 'description': r.preview} for r in chosen if r.enabled]
    schema = project.latest_schema or {}
    locked = sorted(e['id'] for e in schema.get('elements', []) if e.get('locked') and not e.get('isDeleted'))
    value = {'dna': rules, 'locked_ids': locked, 'source': 'project' if project_rules else 'account'}
    return {**value, 'constraints_hash': 'sha256:' + digest(value)}


def node_index(schema: dict[str, Any]) -> list[dict[str, Any]]:
    elements = {e['id']: e for e in schema.get('elements', []) if isinstance(e, dict) and e.get('id') and not e.get('isDeleted')}
    result = []
    for e in elements.values():
        title = e.get('text', '')
        if not title:
            title = ' '.join(elements.get(b['id'], {}).get('text', '') for b in e.get('boundElements') or [] if b.get('type') == 'text')
        result.append({k: v for k, v in {'id': e['id'], 'type': e.get('type'), 'text': title,
                       'x': e.get('x'), 'y': e.get('y'), 'locked': bool(e.get('locked'))}.items() if v is not None})
    return result
