"""AgenticSystemConfig precedence tests."""

from types import SimpleNamespace

import pytest
import yaml


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    from evo_diagram.config.settings import AppSettings

    AppSettings._instance = None
    AppSettings._override_path = None
    yield
    AppSettings._instance = None
    AppSettings._override_path = None


def _args(
    tmp_path,
    *,
    settings_canvas="tldraw",
    settings_mode="multiagent",
    settings_enable_refiner=False,
    settings_use_icons=True,
    settings_full_domain_knowledge=True,
    **overrides,
):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(yaml.dump({
        "canvas": {"library": settings_canvas},
        "generation": {
            "mode": settings_mode,
            "enable_refiner": settings_enable_refiner,
            "use_icons": settings_use_icons,
            "full_domain_knowledge": settings_full_domain_knowledge,
        },
    }))
    data = {
        "model_config": None,
        "settings": str(settings_path),
        "role": "generator",
        "model": None,
        "no_save_intermediate": False,
        "tag": None,
        "variant": None,
        "refiner_iterations": 3,
        "enable_verifier": True,
        "verification_only": False,
        "enable_critic": True,
        "enable_user_memory": False,
        "user_id": "default_user",
        "session_id": None,
        "memory_db_path": None,
        "learn_from_edit": False,
        "task_json": None,
        "model_manifest": None,
        "model_image": None,
        "user_manifest": None,
        "user_image": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_settings_defaults_apply_when_variant_is_omitted(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    config = build_config(
        _args(
            tmp_path,
            settings_canvas="excalidraw",
            settings_mode="oneshot",
            settings_enable_refiner=False,
            settings_use_icons=False,
            settings_full_domain_knowledge=False,
        )
    )

    assert config.variant == "evodiagram"
    assert config.mode == "oneshot"
    assert config.enable_refiner is False
    assert config.use_icons is False
    assert config.full_domain_knowledge is False


def test_explicit_variant_mode_overrides_settings_default(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    config = build_config(
        _args(tmp_path, settings_canvas="excalidraw", variant="evodiagram_wo_multiagent")
    )

    assert config.mode == "oneshot"
    assert config.enable_refiner is False


def test_unknown_variant_is_rejected(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    with pytest.raises(ValueError, match="Unknown variant"):
        build_config(_args(tmp_path, variant="typo_variant"))


def test_parse_arguments_rejects_unknown_variant(monkeypatch):
    from evo_diagram.agentic_system.main import parse_arguments

    monkeypatch.setattr(
        "sys.argv",
        ["evodiagram", "--example", "1", "--variant", "typo_variant"],
    )

    with pytest.raises(SystemExit):
        parse_arguments()


def test_cli_mode_overrides_variant_and_settings(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    config = build_config(
        _args(
            tmp_path,
            settings_canvas="excalidraw",
            variant="evodiagram_wo_refiner",
            mode="oneshot",
        )
    )

    assert config.mode == "oneshot"


def test_programmatic_full_domain_knowledge_is_not_overridden_by_settings(tmp_path):
    from evo_diagram.agentic_system.config import AgenticSystemConfig
    from evo_diagram.config.settings import AppSettings

    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(yaml.dump({
        "generation": {"full_domain_knowledge": True},
    }))
    AppSettings.init(settings_path)

    config = AgenticSystemConfig(full_domain_knowledge=False)

    assert config.full_domain_knowledge is False


def test_user_memory_settings_resolution_fail_fast_when_enabled(monkeypatch):
    from evo_diagram.agentic_system.config import AgenticSystemConfig
    from evo_diagram.config.settings import AppSettings

    monkeypatch.setattr(
        AppSettings,
        "get_default",
        classmethod(lambda cls: (_ for _ in ()).throw(FileNotFoundError("missing settings"))),
    )

    with pytest.raises(RuntimeError, match="Could not resolve user preference memory path"):
        AgenticSystemConfig(enable_user_memory=True)


def test_user_memory_settings_resolution_can_degrade_when_disabled(monkeypatch):
    from evo_diagram.agentic_system.config import AgenticSystemConfig
    from evo_diagram.config.settings import AppSettings

    monkeypatch.setattr(
        AppSettings,
        "get_default",
        classmethod(lambda cls: (_ for _ in ()).throw(FileNotFoundError("missing settings"))),
    )

    config = AgenticSystemConfig(enable_user_memory=False)

    assert config.memory_db_path is None


def test_workflow_config_like_defaults_full_domain_knowledge_to_true(monkeypatch):
    from evo_diagram.agentic_system import workflow as workflow_module

    captured = {}

    class FakeGenerator:
        def run(self, **kwargs):
            return {}

    def fake_create_generator(mode, model, **kwargs):
        captured["full_domain_knowledge"] = kwargs["full_domain_knowledge"]
        return FakeGenerator()

    monkeypatch.setattr(workflow_module, "create_generator", fake_create_generator)

    config_like = SimpleNamespace(
        mode="multiagent",
        canvas_library="excalidraw",
        enable_refiner=False,
        refiner_iterations=1,
        enable_verifier=False,
        verification_only=False,
        enable_critic=False,
        use_icons=False,
        enable_user_memory=False,
        user_id="alice",
        memory_db_path=None,
    )

    workflow_module.Text2DiagramWorkflow(object(), config=config_like)

    assert captured["full_domain_knowledge"] is True


def test_canvas_library_defaults_to_settings(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    config = build_config(_args(tmp_path))

    assert config.canvas_library == "tldraw"
    assert config.enable_refiner is False


def test_settings_tldraw_refiner_request_is_rejected(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    with pytest.raises(ValueError, match="iterative refiner.*Excalidraw"):
        build_config(_args(tmp_path, settings_enable_refiner=True))


def test_cli_canvas_library_overrides_settings(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    config = build_config(_args(tmp_path, canvas_library="excalidraw"))

    assert config.canvas_library == "excalidraw"


def test_tldraw_refiner_request_is_rejected():
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    with pytest.raises(ValueError, match="iterative refiner.*Excalidraw"):
        AgenticSystemConfig(
            canvas_library="tldraw",
            enable_refiner=True,
        )


def test_cli_memory_db_path_is_preserved_in_config(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    memory_db_path = str(tmp_path / "user-memory")
    config = build_config(_args(tmp_path, memory_db_path=memory_db_path))

    assert config.memory_db_path == memory_db_path


def test_workflow_passes_memory_db_path_to_user_memory_system(tmp_path, monkeypatch):
    import evo_diagram.user_memory.main as user_memory_main
    from evo_diagram.agentic_system import workflow as workflow_module

    captured = {}

    class FakeUserPreferenceMemorySystem:
        def __init__(self, *, user_id, memory_db_path=None):
            captured["user_id"] = user_id
            captured["memory_db_path"] = memory_db_path

    monkeypatch.setattr(workflow_module, "create_generator", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        user_memory_main,
        "UserPreferenceMemorySystem",
        FakeUserPreferenceMemorySystem,
    )

    memory_db_path = str(tmp_path / "user-memory")
    workflow_module.Text2DiagramWorkflow(
        object(),
        enable_user_memory=True,
        user_id="alice",
        memory_db_path=memory_db_path,
    )

    assert captured == {
        "user_id": "alice",
        "memory_db_path": memory_db_path,
    }


def test_tldraw_workflow_requires_external_icon_assets_when_icons_enabled(monkeypatch):
    import pytest
    from evo_diagram.agentic_system import workflow as workflow_module
    from evo_diagram.agentic_system.config import AgenticSystemConfig

    monkeypatch.setattr(
        workflow_module,
        "require_icon_assets_available",
        lambda: (_ for _ in ()).throw(RuntimeError("missing icon assets")),
    )
    monkeypatch.setattr(
        workflow_module,
        "create_generator",
        lambda *args, **kwargs: pytest.fail("generator must not initialize without icon assets"),
    )

    with pytest.raises(RuntimeError, match="missing icon assets"):
        workflow_module.Text2DiagramWorkflow(
            object(),
            config=AgenticSystemConfig(use_icons=True, canvas_library="tldraw", enable_refiner=False),
        )


def test_packaged_settings_default_icons_are_disabled_for_clean_checkout():
    from evo_diagram.config.settings import AppSettings

    assert AppSettings.get_default().generation_use_icons is False


def test_programmatic_excalidraw_icons_use_packaged_assets(monkeypatch):
    from evo_diagram.agentic_system import workflow as workflow_module
    seen = {}
    monkeypatch.setattr(workflow_module, "require_icon_assets_available", lambda: pytest.fail("No download needed"))
    def generator(*args, **kwargs):
        seen.update(kwargs)
        return object()
    monkeypatch.setattr(workflow_module, "create_generator", generator)
    workflow = workflow_module.Text2DiagramWorkflow(object(), use_icons=True, enable_verifier=False)
    assert workflow.use_icons and seen["use_icons"] is True


def test_oneshot_rejects_tldraw_canvas(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    with pytest.raises(ValueError, match="oneshot.*Excalidraw"):
        build_config(_args(tmp_path, variant="evodiagram_wo_multiagent"))


def test_invalid_canvas_library_rejected(tmp_path):
    from evo_diagram.agentic_system.main import build_config

    with pytest.raises(ValueError, match="Unknown canvas_library"):
        build_config(_args(tmp_path, canvas_library="unknown-canvas"))


def test_workflow_state_base_rejects_unknown_canvas_library():
    from evo_diagram.agentic_system.common.workflow_state_base import WorkflowStateBase

    assert WorkflowStateBase(canvas_library=" TLDraw ").canvas_library == "tldraw"
    with pytest.raises(ValueError, match="Unknown canvas_library"):
        WorkflowStateBase(canvas_library="unknown-canvas")
