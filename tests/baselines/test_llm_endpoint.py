import pytest

from baselines.llm_endpoint import MissingLLMEndpointError, require_llm_endpoint


def test_missing_endpoint_fails_closed(monkeypatch):
    monkeypatch.delenv("LLM_ENDPOINT_URL", raising=False)

    with pytest.raises(MissingLLMEndpointError, match="LLM_ENDPOINT_URL"):
        require_llm_endpoint()
    with pytest.raises(MissingLLMEndpointError):
        require_llm_endpoint(None, "  ")


def test_explicit_endpoint_wins_over_environment(monkeypatch):
    monkeypatch.setenv("LLM_ENDPOINT_URL", "https://env.example/v1")

    assert require_llm_endpoint(None, "https://explicit.example/v1") == "https://explicit.example/v1"
    assert require_llm_endpoint() == "https://env.example/v1"


def test_no_baseline_or_evaluation_source_hardcodes_a_third_party_endpoint():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = [
        str(path.relative_to(root))
        for folder in ("baselines", "evaluation")
        for path in (root / folder).rglob("*.py")
        if "apis.iflow.cn" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []
