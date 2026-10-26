"""Contracts that keep the baselines comparable to EvoDiagram.

Each test here guards one of the comparison-fairness defects found in the
2026-09 baseline audit: the model must receive the same inputs and run under
the same decoding/robustness settings as the EvoDiagram generator.
"""

from __future__ import annotations

import inspect

import pytest

from evo_diagram.core.base_agent import _render_template


# --- 1. Mermaid: the user intent must reach the model -----------------------

def test_mermaid_process_single_passes_query_as_a_template_variable():
    from baselines.programmic.mermaid import main as mermaid_main

    captured = {}

    class FakeAgent:
        def invoke(self, payload):
            captured.update(payload)
            return "```mermaid\ngraph TD\n  A --> B\n```"

    code = mermaid_main.process_single(FakeAgent(), "Alice calls Bob", "Show the handshake")

    assert captured == {"content": "Alice calls Bob", "query": "Show the handshake"}
    # `custom_task_prompt` was a dead parameter: no template referenced it.
    assert "custom_task_prompt" not in captured
    assert code == "graph TD\n  A --> B"


def test_mermaid_rendered_prompt_contains_the_query_text():
    from baselines.programmic.mermaid.prompts import TASK_PROMPT

    content = "Alice calls Bob"
    query = "Show the handshake"
    rendered = _render_template(TASK_PROMPT, {"content": content, "query": query})

    assert query in rendered
    assert content in rendered
    # str.format() treats `{{query}}` as an escape and emits a literal
    # `{query}`; the template renderer must not leave either behind.
    assert "{query}" not in rendered
    assert "{{query}}" not in rendered
    assert "{content}" not in rendered
    assert "{{content}}" not in rendered


def test_mermaid_str_format_would_drop_the_query():
    """Pins the root cause so the .format() path cannot be reintroduced."""
    from baselines.programmic.mermaid.prompts import TASK_PROMPT

    formatted = TASK_PROMPT.format(content="C", query="REAL QUERY")
    assert "REAL QUERY" not in formatted
    assert "{query}" in formatted


def test_mermaid_agent_run_forwards_content_and_query():
    from baselines.programmic.mermaid.mermaid_agent import MermaidAgent

    source = inspect.getsource(MermaidAgent.run)
    assert '"query": query' in source
    assert "custom_task_prompt" not in source


# --- 3. DiagramAgent: both intent and source text must be sent --------------

def test_diagramagent_generation_input_contains_both_query_and_content():
    from baselines.diagramagent.DiagramAgentEvaluator import _compose_generation_input

    composed = _compose_generation_input("Show the pipeline", "Stage one does X. Stage two does Y.")

    assert "Show the pipeline" in composed
    assert "Stage one does X. Stage two does Y." in composed


@pytest.mark.parametrize(
    "query,content,expected",
    [
        ("", "only content", "only content"),
        ("only query", "", "only query"),
        ("  ", "  ", ""),
    ],
)
def test_diagramagent_generation_input_degrades_gracefully(query, content, expected):
    from baselines.diagramagent.DiagramAgentEvaluator import _compose_generation_input

    assert _compose_generation_input(query, content) == expected


# --- 4. Pixel: --model must reach the generator that actually runs ----------

def test_pixel_process_dataset_applies_the_model_override(monkeypatch, tmp_path):
    from baselines.pixel import gemini_image_generator as gig

    dataset = tmp_path / "data.json"
    dataset.write_text('[{"id": "s1", "content": "text", "query": "q"}]', encoding="utf-8")

    seen = {}

    class FakeGenerator:
        def __init__(self, env_path=None):
            self.model_name = "gemini-2.5-flash-image"  # the env default

        def generate_image(self, content, query=None, output_path=None):
            seen["model_name"] = self.model_name
            return True

    monkeypatch.setattr(gig, "GeminiImageGenerator", FakeGenerator)
    gig.process_dataset(str(dataset), str(tmp_path / "out"), model="gpt-5.2")

    assert seen["model_name"] == "gpt-5.2"


# --- 5. TiKZ: the agent must be instantiable --------------------------------

def test_tlkz_agent_implements_the_abstract_run():
    from baselines.programmic.tlkz.tlkz_agent import TlkzAgent

    assert not inspect.isabstract(TlkzAgent)
    assert TlkzAgent.__abstractmethods__ == frozenset()


def test_tlkz_agent_run_forwards_content_and_query():
    from baselines.programmic.tlkz.tlkz_agent import TlkzAgent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    agent = TlkzAgent(FakeMessagesListChatModel(responses=[AIMessage(content="tikz")]))

    captured = {}
    agent.invoke = lambda payload: captured.update(payload) or "ok"
    assert agent.run({"content": "C", "query": "Q"}) == "ok"
    assert captured == {"content": "C", "query": "Q"}


# --- 2. Decoding / robustness parity ----------------------------------------

EVO_MAX_TOKENS = 16384
EVO_MAX_RETRIES = 6


def test_direct_llm_excalidraw_runner_pins_max_tokens_and_retries(monkeypatch):
    from baselines.direct_llm import runner_excalidraw

    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runner_excalidraw.LLMFactory, "create", staticmethod(fake_create))
    runner_excalidraw._build_model({"model_name": "m", "base_url": "u", "api_key": "k"})

    # Without max_tokens the provider default (commonly 4096) truncates large
    # scenes, so complex samples failed more often than simple ones.
    assert captured["max_tokens"] == EVO_MAX_TOKENS
    assert captured["max_retries"] == EVO_MAX_RETRIES


def test_direct_llm_workflow_pins_max_tokens_and_retries(monkeypatch):
    from baselines.direct_llm import workflow as workflow_mod

    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(workflow_mod.LLMFactory, "create", staticmethod(fake_create))
    workflow_mod.BaselineWorkflow({"model_name": "m"})._initialize_model()

    assert captured["temperature"] == 0
    assert captured["max_tokens"] == EVO_MAX_TOKENS
    assert captured["max_retries"] == EVO_MAX_RETRIES


def test_openai_client_baselines_declare_explicit_retry_settings():
    """These baselines do not inherit BaseAgent, so they carry their own."""
    from baselines.diagramagent import CheckAgent as check_agent_mod
    from baselines.diagramagent import CodeAgent as code_agent_mod
    from baselines.scisketch.src import foundation_model_util

    for module in (check_agent_mod, code_agent_mod):
        assert module.LLM_MAX_RETRIES == EVO_MAX_RETRIES
        assert module.LLM_MAX_TOKENS == EVO_MAX_TOKENS
        assert module.LLM_TEMPERATURE == 0

    assert foundation_model_util._MAX_RETRIES == EVO_MAX_RETRIES
    assert foundation_model_util._MAX_TOKENS == EVO_MAX_TOKENS
