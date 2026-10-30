"""Structure-stage graph contract tests."""

from __future__ import annotations

import pytest

from evo_diagram.agentic_system.generation_stage.structure.schemas import (
    StructureValidationError,
    validate_structure_instantiation,
)
from evo_diagram.agentic_system.generation_stage.structure.state import WorkflowState
from evo_diagram.agentic_system.generation_stage.structure.structure_agent import StructureAgent


def test_structure_validator_accepts_class_or_type_and_normalizes_defaults():
    instantiation = {
        "diagram_type": "flowchart",
        "nodes": [
            {"id": "n_start", "label": "Start", "class": "terminator"},
            {"id": "n_done", "label": "Done", "type": "process"},
        ],
        "edges": [
            {
                "id": "edge:n_start2n_done",
                "source": "n_start",
                "target": "n_done",
                "label": "ok",
            },
        ],
    }

    validated = validate_structure_instantiation(instantiation)

    assert validated["chart_type"] == "flowchart"
    assert "diagram_type" not in validated
    assert validated["groups"] == []
    assert validated["nodes"][1]["class"] == "process"
    assert "type" not in validated["nodes"][1]
    assert "semantic_class" not in validated["nodes"][1]
    assert validated["edges"][0]["id"] == "edge:n_start2n_done"


def test_structure_validator_accepts_legacy_from_to_edge_endpoints():
    validated = validate_structure_instantiation({
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n_start", "label": "Start", "class": "terminator"},
            {"id": "n_done", "label": "Done", "class": "process"},
        ],
        "edges": [{"id": "edge:n_start2n_done", "from": "n_start", "to": "n_done"}],
    })

    assert validated["edges"][0]["source"] == "n_start"
    assert validated["edges"][0]["target"] == "n_done"
    assert "from" not in validated["edges"][0]
    assert "to" not in validated["edges"][0]


def test_structure_validator_canonicalizes_chart_type_aliases():
    validated = validate_structure_instantiation({
        "diagram_type": "flow chart",
        "nodes": [{"id": "n_start", "label": "Start", "type": "process"}],
        "edges": [],
    })

    assert validated["chart_type"] == "flowchart"
    assert validated["nodes"][0]["class"] == "process"


def test_structure_validator_rejects_unsupported_chart_type():
    with pytest.raises(StructureValidationError, match="Unsupported chart_type"):
        validate_structure_instantiation({
            "chart_type": "unsupported",
            "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
        })


def test_structure_validator_rejects_conflicting_node_class_aliases():
    with pytest.raises(StructureValidationError, match="conflicting class/type values"):
        validate_structure_instantiation({
            "chart_type": "flowchart",
            "nodes": [
                {
                    "id": "n1",
                    "label": "Node",
                    "class": "process",
                    "semantic_class": "decision",
                },
            ],
            "edges": [],
        })


def test_structure_validator_rejects_conflicting_edge_endpoint_aliases():
    with pytest.raises(StructureValidationError, match="conflicting source/from values"):
        validate_structure_instantiation({
            "chart_type": "flowchart",
            "nodes": [
                {"id": "n1", "label": "One", "class": "process"},
                {"id": "n2", "label": "Two", "class": "process"},
                {"id": "n3", "label": "Three", "class": "process"},
            ],
            "edges": [
                {
                    "id": "edge:n12n2",
                    "source": "n1",
                    "from": "n3",
                    "target": "n2",
                },
            ],
        })


def test_structure_validator_enforces_canonical_edge_ids_and_parallel_suffixes():
    validated = validate_structure_instantiation({
        "chart_type": "flowchart",
        "nodes": [
            {"id": "n1", "label": "One", "class": "process"},
            {"id": "n2", "label": "Two", "class": "process"},
        ],
        "edges": [
            {"id": "edge:n12n2", "source": "n1", "target": "n2"},
            {"id": "edge:n12n2_2", "source": "n1", "target": "n2"},
        ],
    })

    assert [edge["id"] for edge in validated["edges"]] == [
        "edge:n12n2",
        "edge:n12n2_2",
    ]

    with pytest.raises(StructureValidationError, match="must use canonical id"):
        validate_structure_instantiation({
            "chart_type": "flowchart",
            "nodes": [
                {"id": "n1", "label": "One", "class": "process"},
                {"id": "n2", "label": "Two", "class": "process"},
            ],
            "edges": [{"id": "edge_custom", "source": "n1", "target": "n2"}],
        })


@pytest.mark.parametrize("chart_type", ["mindmap", "tree", "orgchart"])
def test_structure_validator_enforces_parent_hierarchy_fields(chart_type):
    validated = validate_structure_instantiation({
        "chart_type": chart_type,
        "nodes": [
            {"id": "root", "label": "Root", "class": "root", "parent_id": None},
            {"id": "child", "label": "Child", "class": "branch", "parent_id": "root"},
        ],
        "edges": [],
    })

    assert validated["nodes"][1]["parent_id"] == "root"

    with pytest.raises(StructureValidationError, match="must include parent_id"):
        validate_structure_instantiation({
            "chart_type": chart_type,
            "nodes": [{"id": "root", "label": "Root", "class": "root"}],
            "edges": [],
        })


def test_structure_validator_rejects_parent_hierarchy_cycles():
    with pytest.raises(StructureValidationError, match="parent_id hierarchy contains a cycle"):
        validate_structure_instantiation({
            "chart_type": "tree",
            "nodes": [
                {"id": "root", "label": "Root", "class": "root", "parent_id": None},
                {"id": "a", "label": "A", "class": "branch", "parent_id": "b"},
                {"id": "b", "label": "B", "class": "branch", "parent_id": "a"},
            ],
            "edges": [],
        })


def test_structure_validator_enforces_matrix_cell_coordinates():
    validated = validate_structure_instantiation({
        "chart_type": "matrix",
        "nodes": [{"id": "n1", "label": "Cell", "class": "cell", "row": 0, "col": 1}],
        "edges": [],
    })

    assert validated["nodes"][0]["row"] == 0
    assert validated["nodes"][0]["col"] == 1

    with pytest.raises(StructureValidationError, match="non-negative integer row"):
        validate_structure_instantiation({
            "chart_type": "matrix",
            "nodes": [{"id": "n1", "label": "Cell", "class": "cell", "row": -1, "col": 0}],
            "edges": [],
        })


def test_structure_validator_enforces_sequence_actor_and_order_fields():
    validated = validate_structure_instantiation({
        "chart_type": "sequence_diagram",
        "nodes": [
            {"id": "client", "label": "Client", "class": "actor", "actor_id": "client"},
            {"id": "api", "label": "API", "class": "actor", "actor_id": "api"},
        ],
        "edges": [
            {
                "id": "edge:client2api",
                "source": "client",
                "target": "api",
                "label": "Request",
                "sequence_idx": 0,
            },
        ],
    })

    assert validated["edges"][0]["sequence_idx"] == 0

    with pytest.raises(StructureValidationError, match="non-empty actor_id"):
        validate_structure_instantiation({
            "chart_type": "sequence_diagram",
            "nodes": [{"id": "client", "label": "Client", "class": "actor"}],
            "edges": [],
        })


def test_structure_validator_enforces_gantt_time_fields():
    validated = validate_structure_instantiation({
        "chart_type": "gantt",
        "nodes": [
            {
                "id": "task",
                "label": "Task",
                "class": "task",
                "start_ts": "2026-01-01",
                "end_ts": "2026-01-02",
            },
        ],
        "edges": [],
    })

    assert validated["nodes"][0]["start_ts"] == "2026-01-01"

    with pytest.raises(StructureValidationError, match="start_ts must not be after end_ts"):
        validate_structure_instantiation({
            "chart_type": "gantt",
            "nodes": [
                {
                    "id": "task",
                    "label": "Task",
                    "class": "task",
                    "start_ts": 10,
                    "end_ts": 5,
                },
            ],
            "edges": [],
        })


def test_structure_validator_rejects_duplicate_ids_across_categories():
    with pytest.raises(StructureValidationError, match="unique across nodes, edges, and groups"):
        validate_structure_instantiation({
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
            "edges": [],
            "groups": [{"id": "n1", "members": ["n1"]}],
        })


def test_structure_validator_rejects_dangling_edge_endpoint():
    with pytest.raises(StructureValidationError, match="target 'missing'.*existing node"):
        validate_structure_instantiation({
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
            "edges": [{"id": "edge:n12missing", "source": "n1", "target": "missing"}],
            "groups": [],
        })


def test_structure_validator_rejects_dangling_group_member_and_relation():
    with pytest.raises(StructureValidationError, match="member 'missing'.*existing node or group"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [{"id": "n1", "label": "API", "class": "service"}],
            "groups": [{"id": "g1", "members": ["missing"]}],
        })

    with pytest.raises(StructureValidationError, match="relation 'missing_edge'.*existing edge"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [{"id": "n1", "label": "API", "class": "service"}],
            "edges": [],
            "groups": [{"id": "g1", "members": ["n1"], "relations": ["missing_edge"]}],
        })


def test_structure_validator_rejects_member_in_multiple_groups():
    with pytest.raises(StructureValidationError, match="belongs to multiple groups"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [
                {"id": "n1", "label": "API", "class": "service"},
                {"id": "n2", "label": "DB", "class": "database"},
            ],
            "edges": [],
            "groups": [
                {"id": "g1", "members": ["n1"]},
                {"id": "g2", "members": ["n1", "n2"]},
            ],
        })


def test_structure_validator_rejects_group_cycles():
    with pytest.raises(StructureValidationError, match="contains a cycle"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [{"id": "n1", "label": "API", "class": "service"}],
            "edges": [],
            "groups": [
                {"id": "g1", "members": ["g2"]},
                {"id": "g2", "members": ["g1"]},
            ],
        })

    with pytest.raises(StructureValidationError, match="contains a cycle"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [{"id": "n1", "label": "API", "class": "service"}],
            "edges": [],
            "groups": [
                {"id": "g1", "parent_group_id": "g2", "members": []},
                {"id": "g2", "parent_group_id": "g1", "members": []},
            ],
        })


def test_structure_validator_rejects_conflicting_group_parent_sources():
    with pytest.raises(StructureValidationError, match="conflicting parents"):
        validate_structure_instantiation({
            "chart_type": "architecture",
            "nodes": [{"id": "n1", "label": "API", "class": "service"}],
            "edges": [],
            "groups": [
                {"id": "g1", "members": ["g2"]},
                {"id": "g2", "parent_group_id": "g3", "members": ["n1"]},
                {"id": "g3", "members": []},
            ],
        })


def test_structure_agent_fails_fast_on_invalid_instantiation():
    agent = object.__new__(StructureAgent)
    agent._system_prompt = "system"
    agent._read_self_consistency_n = lambda: 1
    agent.invoke_with_history = lambda messages: {
        "specification": {"diagram_paradigm": {"type_budget": "flowchart"}},
        "instantiation": {
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
            "edges": [{"id": "edge:n12missing", "source": "n1", "target": "missing"}],
        },
    }

    state = WorkflowState(text_content="A then B", user_query="flowchart")

    with pytest.raises(StructureValidationError, match="target 'missing'"):
        agent.run(state)

    assert state.status == "failed"
    assert state.structure_instantiation is None
    assert "target 'missing'" in state.errors[0]


def test_structure_agent_records_formatted_assistant_history():
    agent = object.__new__(StructureAgent)
    agent._system_prompt = "system"
    agent._read_self_consistency_n = lambda: 1
    agent.invoke_with_history = lambda messages: {
        "specification": {
            "diagram_paradigm": {
                "type_budget": "flowchart",
                "organizer": "linear flow",
            },
        },
        "instantiation": {
            "chart_type": "flowchart",
            "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
            "edges": [],
        },
    }

    state = WorkflowState(text_content="A", user_query="flowchart")
    result = agent.run(state)

    assistant_content = result.conversation_history[-1]["content"]
    assert "--- Structure Design Specification ---" in assistant_content
    assert "type_budget: flowchart" in assistant_content
    assert "--- Instantiation ---" in assistant_content
    assert '"chart_type": "flowchart"' in assistant_content


def test_structure_agent_self_consistency_votes_after_structure_normalization(monkeypatch):
    agent = object.__new__(StructureAgent)
    agent._system_prompt = "system"
    agent._read_self_consistency_n = lambda: 3
    agent.invoke_with_history = lambda messages: pytest.fail("sample_and_vote stub should own sampling")

    def fake_sample_and_vote(invoke_fn, input_dict, *, n_samples, vote_key, unwrap_fn=None):
        assert n_samples == 3
        assert vote_key == "chart_type"
        assert unwrap_fn is not None
        raw_output = {
            "specification": {"diagram_paradigm": {"type_budget": "flowchart"}},
            "instantiation": {
                "diagram_type": "flowchart",
                "nodes": [{"id": "n1", "label": "Node", "class": "process"}],
                "edges": [],
            },
        }
        specification, instantiation = unwrap_fn(raw_output)
        assert instantiation["chart_type"] == "flowchart"
        return specification, instantiation

    monkeypatch.setattr(
        "evo_diagram.agentic_system.common.self_consistency.sample_and_vote",
        fake_sample_and_vote,
    )

    state = WorkflowState(text_content="A", user_query="flowchart")
    result = agent.run(state)

    assert result.structure_instantiation["chart_type"] == "flowchart"


def test_sample_and_vote_rejects_unbounded_parallelism():
    from evo_diagram.agentic_system.common.self_consistency import sample_and_vote

    with pytest.raises(ValueError, match="n_samples must be <= 9"):
        sample_and_vote(
            lambda _input: {"instantiation": {"chart_type": "flowchart"}},
            {},
            n_samples=10,
        )
