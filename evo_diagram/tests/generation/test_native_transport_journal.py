import json
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackManager, BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from evo_diagram.agentic_system.generation_stage.unified.generator import UnifiedGenerator
from evo_diagram.agentic_system.generation_stage.unified.transport_journal import NativeStreamJournal


def test_interrupted_native_text_is_preserved_without_prompts_or_retry_mixing(tmp_path):
    journal = NativeStreamJournal()
    journal.directory = tmp_path
    first, second = uuid4(), uuid4()
    journal.on_chat_model_start({}, [["private source text"]], run_id=first)
    journal.on_llm_new_token('{"elements":[', run_id=first)
    journal.on_llm_new_token('{"id":"a"}', run_id=first)
    journal.on_llm_error(ConnectionError("disconnected"), run_id=first)
    journal.on_chat_model_start({}, [], run_id=second)
    journal.on_llm_error(TimeoutError("no authored output"), run_id=second)
    report = json.loads((tmp_path / "transport_attempts.json").read_text())
    assert [item["authored_characters"] for item in report["attempts"]] == [23, 0]
    assert (tmp_path / "attempt_01_output.txt").read_text() == '{"elements":[{"id":"a"}'
    assert (tmp_path / "attempt_02_output.txt").read_text() == ""
    assert not any("private source text" in p.read_text() for p in tmp_path.iterdir())
    assert not journal.active


def test_native_journal_runs_through_real_model_callbacks_without_mutating_model(tmp_path):
    existing = BaseCallbackHandler()
    model = FakeListChatModel(responses=['{"ok":true}'], callbacks=[existing])
    generator = UnifiedGenerator(model)
    generator.stream_journal.directory = tmp_path
    output = "".join(chunk.content for chunk in generator._model.stream("source"))
    assert output == '{"ok":true}'
    assert model.callbacks == [existing]
    assert existing in generator._model.callbacks
    assert (tmp_path / "attempt_01_output.txt").read_text() == output
    report = json.loads((tmp_path / "transport_attempts.json").read_text())
    assert report["attempts"][0]["status"] == "complete"
    assert generator.invoke({}) == {"ok": True}
    assert (tmp_path / "attempt_02_output.txt").read_text() == output


def test_native_journal_preserves_callback_manager_handlers():
    existing = BaseCallbackHandler()
    callbacks = BaseCallbackManager(handlers=[existing])
    model = FakeListChatModel(responses=['{}'], callbacks=callbacks)
    generator = UnifiedGenerator(model)
    assert model.callbacks.handlers == [existing]
    assert generator._model.callbacks.handlers == [existing, generator.stream_journal]


def test_responses_content_blocks_capture_only_authored_text(tmp_path):
    journal = NativeStreamJournal()
    journal.directory = tmp_path
    run_id = uuid4()
    journal.on_chat_model_start({}, [], run_id=run_id)
    journal.on_llm_new_token([
        {"type": "reasoning", "text": "private reasoning"},
        {"type": "text", "text": '{"elements":', "index": 0},
    ], run_id=run_id)
    journal.on_llm_new_token([{"type": "output_text", "text": "["}], run_id=run_id)
    journal.on_llm_error(ConnectionError("stream ended"), run_id=run_id)
    assert (tmp_path / "attempt_01_output.txt").read_text() == '{"elements":['
    assert not any("private reasoning" in p.read_text() for p in tmp_path.iterdir())
