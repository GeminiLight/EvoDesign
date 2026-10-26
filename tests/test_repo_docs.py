from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "AGENTS.md"
ARCHIVED_SUPABASE_DESIGN = (
    REPO_ROOT / "backend" / "docs" / "archive" / "supabase" / "DATABASE_DESIGN.md"
)


def test_repository_guidelines_reference_existing_service_launcher():
    text = AGENTS.read_text(encoding="utf-8")

    assert "./start_dev.sh" not in text
    assert "./scripts/start_service.sh" in text
    assert (REPO_ROOT / "scripts" / "start_service.sh").is_file()
    assert (REPO_ROOT / "scripts" / "stop_service.sh").is_file()


def test_docs_do_not_reference_removed_backend_supabase_directory():
    docs = [
        AGENTS,
        ARCHIVED_SUPABASE_DESIGN,
    ]

    for doc_path in docs:
        text = doc_path.read_text(encoding="utf-8")
        assert "backend/supabase/" not in text, doc_path


def test_archived_supabase_design_is_marked_as_archive():
    text = ARCHIVED_SUPABASE_DESIGN.read_text(encoding="utf-8")

    assert "归档说明" in text
    assert "backend/app/db/bootstrap.py" in text
    assert "backend/docs/archive/supabase/002_complete_schema.sql" in text
