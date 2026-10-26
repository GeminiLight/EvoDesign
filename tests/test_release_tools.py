import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_setup_creates_matching_secrets_and_preserves_existing(tmp_path):
    (tmp_path / "frontend").mkdir()
    for rel in (".env.example", "frontend/.env.example"):
        (tmp_path / rel).write_text((ROOT / rel).read_text())
    setup = load("setup_local")
    setup.setup(tmp_path)
    env = (tmp_path / ".env").read_text()
    token = next(line.split("=", 1)[1] for line in env.splitlines() if line.startswith("GUEST_TOKEN="))
    assert len(token) >= 32
    assert f"VITE_GUEST_TOKEN={token}" in (tmp_path / "frontend/.env").read_text()
    with pytest.raises(FileExistsError):
        setup.setup(tmp_path)
    assert (tmp_path / ".env").read_text() == env
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_memory_roundtrip_preserves_existing_and_removes_identity():
    module = load("design_memory")
    import json
    document = json.loads((ROOT / "examples/design-memory/blue-violet.json").read_text())
    rules = module.validate(document)
    existing = {cabin: [] for cabin in module.CABINS}
    existing["project_id"] = "private-project-id"
    merged, count = module.merge_rules(existing, rules)
    assert count == 8
    repeated, count = module.merge_rules(merged, rules)
    assert count == 0
    assert repeated == merged
    exported = module.export_rules(merged)
    assert module.validate(exported) == rules
    assert "private-project-id" not in json.dumps(exported)
    assert "rule_id" not in json.dumps(exported)
    document["rules"][0]["user_id"] = "must-not-import"
    with pytest.raises(ValueError):
        module.validate(document)


def test_memory_rejects_remote_plaintext_before_sending_token():
    with pytest.raises(ValueError, match="HTTPS"):
        load("design_memory").api_request("http://example.com", "secret")


def test_environment_model_name_fails_clearly_when_missing(monkeypatch):
    from evo_diagram.config.model_loader import ModelConfig, _DEFAULT_PATH
    monkeypatch.delenv("LLM_MODEL_NAME", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-config-key")
    with pytest.raises(ValueError, match="LLM_MODEL_NAME"):
        ModelConfig(_DEFAULT_PATH).get_model_config("generator")
