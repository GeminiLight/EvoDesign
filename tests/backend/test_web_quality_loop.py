from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.workflow_generate_service import WorkflowGenerateService
from app.services.workflow_runtime.quality import quality_regressed, quality_summary


@pytest.mark.parametrize("tier", [None, "free", "pro", "enterprise"])
def test_memory_is_private_and_refinement_does_not_require_pro(tier, tmp_path):
    settings = Settings(_env_file=None, jwt_secret="test-jwt", session_secret="test-session",
                        design_memory_path=str(tmp_path))
    service = WorkflowGenerateService(settings)
    def request(user):
        return service._build_run_request(context="A to B", requirements=None,
            locked_nodes=[], current_schema=None, canvas_library="excalidraw",
            request_id="test", user_tier=tier, user_id=user)
    alice, bob, guest = request("alice"), request("bob"), request(None)
    assert alice.enable_refiner and bob.enable_refiner and guest.enable_refiner
    assert alice.enable_design_memory and alice.learn_design_memory
    assert guest.enable_design_memory and not guest.learn_design_memory
    assert len({alice.design_memory_path, bob.design_memory_path, guest.design_memory_path}) == 3
    assert "alice" not in alice.design_memory_path
    assert alice.design_memory_path == request("alice").design_memory_path


@pytest.mark.parametrize("before,after,regressed", [
    ({"score": 8}, {"score": 8.5}, False),
    ({"score": 8}, {"score": 7}, True),
    ({"score": 8, "findings": {"major": 1}}, {"score": None}, True),
    ({"score": 8, "findings": {"major": 1}}, {"score": 7}, True),
    ({"score": 8}, {"score": 9, "findings": {"major": 1}}, True),
])
def test_final_review_preserves_quality(before, after, regressed):
    assert quality_regressed(before, after) is regressed


def test_quality_report_does_not_emit_nonfinite_json_score():
    state = SimpleNamespace(critique=SimpleNamespace(overall_score=float("nan")))
    assert quality_summary(state)["score"] is None
