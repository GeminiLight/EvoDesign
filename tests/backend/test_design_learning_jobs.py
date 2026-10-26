import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import design_learning_jobs as jobs


def inputs(tmp_path):
    report = tmp_path / "original.json"
    report.write_text(json.dumps({"iterations": []}))
    return dict(memory_path=str(tmp_path / "memory"), embedding_model="test",
        report_path=str(report), request_id="req_test", diagram_type="flowchart",
        before={"score": 6}, after={"score": 8}, model=object(), retriever=object())


@pytest.mark.asyncio
async def test_delivery_does_not_wait_and_cleanup_cannot_remove_learning_inputs(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def learn(**kwargs):
        entered.set()
        assert release.wait(5)
        assert json.loads(open(kwargs["report_path"]).read()) == {"iterations": []}
        return {"status": "saved", "saved_count": 1}
    args = inputs(tmp_path)
    try:
        result = jobs.enqueue_learning(**args, learner=learn)
        assert result["status"] == "queued"
        assert await asyncio.to_thread(entered.wait, 5)
        (tmp_path / "original.json").unlink()
        assert jobs.read_status(args["memory_path"], "req_test")["status"] == "running"
    finally:
        release.set()
        await jobs.wait_for_learning()
    assert jobs.read_status(args["memory_path"], "req_test")["saved_count"] == 1


@pytest.mark.asyncio
async def test_no_verified_gain_does_not_schedule_or_call_a_model(tmp_path):
    args = inputs(tmp_path)
    args["before"] = args["after"]
    result = jobs.enqueue_learning(**args, learner=lambda **k: pytest.fail("No gain"))
    assert result["status"] == "skipped"
    assert not (tmp_path / "memory").exists()


@pytest.mark.asyncio
async def test_failed_learning_is_reported_without_affecting_the_diagram(tmp_path):
    def fail(**kwargs):
        raise RuntimeError("provider unavailable")
    args = inputs(tmp_path)
    jobs.enqueue_learning(**args, learner=fail)
    await jobs.wait_for_learning()
    result = jobs.read_status(args["memory_path"], "req_test")
    assert result["status"] == "unavailable"
    assert "provider" not in json.dumps(result)


def test_startup_recovers_queued_and_interrupted_jobs_only(tmp_path, monkeypatch):
    recovered = []
    for name, status in [("first", "queued"), ("second", "running"), ("done", "saved")]:
        directory = tmp_path / "private" / ".learning" / name
        directory.mkdir(parents=True)
        (directory / "status.json").write_text(json.dumps({"status": status}))
    monkeypatch.setattr(jobs, "_start", lambda path: recovered.append(path.name))
    jobs.resume_learning(str(tmp_path))
    assert set(recovered) == {"first", "second"}


@pytest.mark.asyncio
async def test_learning_status_is_account_scoped_and_rejects_path_traversal(tmp_path, monkeypatch):
    from app.api.v1.endpoints.diagram import get_design_learning_status
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(design_memory_path=str(tmp_path)))
    directory = jobs.private_memory_path(str(tmp_path), "alice") / ".learning" / "req_private"
    directory.mkdir(parents=True)
    (directory / "status.json").write_text('{"status":"saved","saved_count":1}')
    assert (await get_design_learning_status("req_private", SimpleNamespace(user_id="alice")))["status"] == "saved"
    for user, job_id in [("bob", "req_private"), ("alice", "../../req_private")]:
        with pytest.raises(HTTPException) as error:
            await get_design_learning_status(job_id, SimpleNamespace(user_id=user))
        assert error.value.status_code == 404
