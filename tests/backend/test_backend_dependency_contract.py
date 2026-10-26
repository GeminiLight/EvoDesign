from __future__ import annotations

import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower()


def _backend_extra_dependencies() -> set[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = pyproject["project"]["optional-dependencies"]["backend"]
    return {_requirement_name(requirement) for requirement in requirements}


def _requirements_file_dependencies() -> set[str]:
    requirements = set()
    for line in (REPO_ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8",
    ).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.add(_requirement_name(line))
    return requirements


def test_backend_extra_includes_direct_backend_runtime_dependencies():
    """CI installs backend tests with .[backend,test], so direct imports must live there."""
    assert {
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "asyncpg",
        "aiosqlite",
        "pydantic-settings",
        "python-jose",
        "passlib",
        "httpx-oauth",
        "stripe",
        "loguru",
        "python-multipart",
        "email-validator",
        "slowapi",
        "alembic",
    } <= _backend_extra_dependencies()


def test_backend_requirements_do_not_add_backend_only_packages_missing_from_extra():
    """Keep the deployment requirements and packaging extras from drifting apart."""
    backend_extra = _backend_extra_dependencies()
    requirements = _requirements_file_dependencies()
    project_core = {
        _requirement_name(requirement)
        for requirement in tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["dependencies"]
    }
    test_extra = {
        _requirement_name(requirement)
        for requirement in tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["optional-dependencies"]["test"]
    }

    assert requirements <= backend_extra | project_core | test_extra
