from __future__ import annotations

import pytest

from evo_diagram.agentic_system.generation_stage.router.agent import (
    RouterAgent,
    RouterClassificationError,
)


def _agent_with_result(result):
    agent = object.__new__(RouterAgent)
    agent.invoke = lambda payload: result
    return agent


def test_router_agent_accepts_valid_routing_payload():
    agent = _agent_with_result({
        "diagram_type": " flowchart ",
        "palette_key": "blush_sage",
        "reasoning": "fits a process",
        "retrieval_query": "process flow",
    })

    result = agent.run("Start then finish", "make a flowchart")

    assert result == {
        "diagram_type": "flowchart",
        "palette_key": "blush_sage",
        "reasoning": "fits a process",
        "retrieval_query": "process flow",
    }


def test_router_agent_canonicalizes_supported_diagram_aliases():
    agent = _agent_with_result({
        "diagram_type": "flow",
        "palette_key": "blush_sage",
    })

    assert agent.run("Start then finish", "make a flow")["diagram_type"] == "flowchart"


def test_router_agent_rejects_non_object_output():
    agent = _agent_with_result(["not", "json", "object"])

    with pytest.raises(RouterClassificationError, match="expected a JSON object"):
        agent.run("text", "query")


def test_router_agent_rejects_missing_diagram_type():
    agent = _agent_with_result({"palette_key": "blush_sage"})

    with pytest.raises(RouterClassificationError, match="missing diagram_type"):
        agent.run("text", "query")


def test_router_agent_rejects_unsupported_diagram_type():
    agent = _agent_with_result({
        "diagram_type": "unknown_diagram",
        "palette_key": "blush_sage",
    })

    with pytest.raises(RouterClassificationError, match="Unsupported diagram_type"):
        agent.run("text", "query")


def test_router_agent_rejects_invalid_palette_key():
    agent = _agent_with_result({
        "diagram_type": "flowchart",
        "palette_key": "not_a_palette",
    })

    with pytest.raises(RouterClassificationError, match="not in the palette catalog"):
        agent.run("text", "query")


def test_router_agent_propagates_model_failures_as_router_errors():
    agent = object.__new__(RouterAgent)

    def fail(_payload):
        raise TimeoutError("provider timed out")

    agent.invoke = fail

    with pytest.raises(RouterClassificationError, match="Router classification failed"):
        agent.run("text", "query")
