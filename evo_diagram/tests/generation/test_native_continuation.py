import json
from copy import deepcopy

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from evo_diagram.agentic_system.generation_stage.unified.continuation import (
    complete_scene_prefix,
    invoke_native_scene,
)
from evo_diagram.agentic_system.generation_stage.unified.state import UnifiedWorkflowState
from evo_diagram.agentic_system.generation_stage.unified.transport_journal import NativeStreamJournal
from evo_diagram.agentic_system.generation_stage.unified.workflow import UnifiedGeneratorWorkflow
from evo_diagram.utils.llm_output import get_text_from_response


def _scene():
    return {
        "type": "excalidraw/clipboard",
        "elements": [{
            "id": "node", "type": "rectangle", "x": 100, "y": 100,
            "width": 160, "height": 52, "strokeColor": "#334155",
            "backgroundColor": "#ffffff",
        }],
        "files": {}, "appState": {"viewBackgroundColor": "#ffffff"},
        "_meta": {
            "structure_instantiation": {"chart_type": "flowchart", "nodes": [
                {"id": "semantic", "label": "One", "class": "process"},
            ], "edges": [], "groups": []},
            "id_map": {"semantic": "node"},
        },
    }


def test_checkpoint_keeps_complete_elements_and_escaped_text_verbatim():
    first = '{"id":"一","text":"a, b \\"quoted\\""}'
    text = '{"type":"excalidraw/clipboard","elements":[' + first + ',{"id":"cut'
    prefix = complete_scene_prefix(text)
    assert prefix == text[:text.index(',{"id":"cut')]
    assert json.loads(prefix + ']}')["elements"] == [{"id": "一", "text": 'a, b "quoted"'}]


def test_checkpoint_handles_finished_array_and_interrupted_sidecar():
    text = json.dumps(_scene(), ensure_ascii=False)
    partial = text[:text.index('"flowchart"') + 5]
    prefix = complete_scene_prefix(partial)
    assert json.loads(prefix + '}')["elements"] == _scene()["elements"]
    assert '"_meta"' not in prefix
    assert complete_scene_prefix('{"type":"excalidraw/clipboard"') == ""


class InterruptedAgent:
    def __init__(self, journal, partial, suffix):
        self.journal, self.partial, self.suffix = journal, partial, suffix
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(deepcopy(prompt))
        if len(self.prompts) == 1:
            self.journal.last_output = self.partial
            raise ConnectionError("provider disconnected")
        return {"messages": [AIMessage(content=self.suffix)]}


def test_full_unified_workflow_resumes_then_runs_normalization_and_validation(tmp_path):
    scene = _scene()
    text = json.dumps(scene)
    partial = text[:text.index('"flowchart"') + 5]
    prefix = complete_scene_prefix(partial)
    workflow = UnifiedGeneratorWorkflow(FakeListChatModel(responses=['{}']))
    interrupted = InterruptedAgent(workflow.agent.stream_journal, partial, text[len(prefix):])
    workflow.agent._agent = interrupted
    state = workflow.run(UnifiedWorkflowState(
        text_content="One step", diagram_type="flowchart",
        validation_report_path=str(tmp_path / "validation.json"),
    ))
    assert state.diagram_manifest["elements"][0]["x"] == 100
    assert "version" in state.diagram_manifest["elements"][0]
    assert state.generation_attempts == [{"attempt": 1, "stage": "complete", "error": None}]
    assert len(interrupted.prompts) == 2
    assert interrupted.prompts[1]["messages"][:-2] == interrupted.prompts[0]["messages"]
    assert interrupted.prompts[1]["messages"][-2].content == prefix
    assert (tmp_path / "transport/continuation_01_prefix.txt").read_text() == prefix


def test_completed_json_survives_missing_final_transport_event():
    text = json.dumps(_scene())
    journal = NativeStreamJournal()
    agent = InterruptedAgent(journal, text, "unused")
    result = invoke_native_scene(agent, {"messages": []}, journal)
    assert get_text_from_response(result) == text
    assert len(agent.prompts) == 1


def test_continuation_budget_and_original_prompt_are_preserved():
    journal = NativeStreamJournal()
    original = {"messages": [{"role": "user", "content": "original source"}]}
    before = deepcopy(original)

    class AlwaysInterrupted:
        count = 0

        def invoke(self, prompt):
            self.count += 1
            journal.last_output = (
                '{"elements":[{"id":"one"},'
                if self.count == 1 else ',{"id":"next' + str(self.count) + '"},'
            )
            raise ConnectionError("interrupted")

    agent = AlwaysInterrupted()
    with pytest.raises(ConnectionError):
        invoke_native_scene(agent, original, journal)
    assert agent.count == 3
    assert original == before


def test_programming_errors_do_not_trigger_continuation():
    journal = NativeStreamJournal()

    class BrokenAgent:
        def invoke(self, prompt):
            journal.last_output = '{"elements":[{"id":"one"},'
            raise KeyError("application bug")

    with pytest.raises(KeyError):
        invoke_native_scene(BrokenAgent(), {"messages": []}, journal)


def test_scene_repair_continuations_preserve_prior_prefix_evidence(tmp_path):
    journal = NativeStreamJournal()
    journal.configure(tmp_path, new_scene=True)
    for node in ("first", "repaired"):
        partial = '{"elements":[{"id":"' + node + '"},'
        agent = InterruptedAgent(journal, partial, ']}')
        invoke_native_scene(agent, {"messages": []}, journal)
        journal.configure(tmp_path, new_scene=False)
    assert '"first"' in (tmp_path / "continuation_01_prefix.txt").read_text()
    assert '"repaired"' in (tmp_path / "continuation_02_prefix.txt").read_text()
    assert len(json.loads((tmp_path / "continuations.json").read_text())) == 2
    journal.configure(tmp_path / "another", new_scene=True)
    assert journal.continuations == []
