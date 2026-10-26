"""DiagramAgent internals: code extraction, compile diagnostics, self-repair."""

from __future__ import annotations

import types

import pytest


# --- 6. Fenced code must be returned without its fences --------------------

def test_code_agent_strips_the_markdown_fence():
    from baselines.diagramagent.CodeAgent import CodeAgent

    extract = CodeAgent._extract_code_block
    text = "Sure:\n```latex\n\\documentclass{standalone}\n\\begin{document}x\\end{document}\n```\n"

    code = extract(None, text)

    assert not code.lstrip().startswith("```")
    assert code.lstrip().startswith("\\documentclass")
    assert "```" not in code


def test_code_agent_falls_back_to_group_zero_for_ungrouped_patterns():
    from baselines.diagramagent.CodeAgent import CodeAgent

    extract = CodeAgent._extract_code_block
    code = extract(None, "prefix digraph {A->B} suffix")

    assert code.startswith("digraph")


# --- 12a. pdflatex writes diagnostics to stdout, not stderr ----------------

def test_latex_diagnostics_read_stdout():
    from baselines.diagramagent.CheckAgent import CheckAgent

    stdout = (
        "This is pdfTeX, Version 3.14\n"
        "(./diagram.tex\n"
        "! Undefined control sequence.\n"
        "l.3 \\undefinedcommand\n"
        "                     \n"
        "! Emergency stop.\n"
    )

    diagnostics = CheckAgent._latex_diagnostics(stdout, "")

    assert "Undefined control sequence" in diagnostics
    assert diagnostics.strip() != ""


def test_latex_diagnostics_is_bounded():
    from baselines.diagramagent.CheckAgent import CheckAgent

    stdout = "\n".join(f"! Error number {i}" for i in range(5000))
    assert len(CheckAgent._latex_diagnostics(stdout, "")) <= 4000


def test_latex_diagnostics_still_reports_stderr_when_present():
    from baselines.diagramagent.CheckAgent import CheckAgent

    diagnostics = CheckAgent._latex_diagnostics("", "pdflatex: command failed")
    assert "pdflatex: command failed" in diagnostics


# --- 12b. Verifier suggestions must actually be applied --------------------

def _check_agent_without_network():
    from baselines.diagramagent.CheckAgent import CheckAgent

    agent = CheckAgent.__new__(CheckAgent)
    agent.use_gpt4o = True
    agent.llm_model = "test-model"
    agent.client = None
    return agent


def _fake_client(reply: str):
    def create(**kwargs):
        message = types.SimpleNamespace(content=reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def test_apply_suggestions_returns_the_revised_code():
    agent = _check_agent_without_network()
    agent.client = _fake_client("```latex\nREVISED\n```")

    assert agent._apply_suggestions("ORIGINAL", "add the missing node") == "REVISED"


def test_apply_suggestions_is_a_no_op_without_a_client_or_suggestions():
    agent = _check_agent_without_network()
    assert agent._apply_suggestions("ORIGINAL", "something") == "ORIGINAL"

    agent.client = _fake_client("REVISED")
    assert agent._apply_suggestions("ORIGINAL", "") == "ORIGINAL"
    assert agent._apply_suggestions("ORIGINAL", None) == "ORIGINAL"


def test_check_adopts_a_revision_that_compiles(monkeypatch):
    agent = _check_agent_without_network()
    agent.client = _fake_client("REVISED")
    monkeypatch.setattr(agent, "_verify_with_gpt4o", lambda code, q: {"is_complete": False, "suggestions": "fix it"})
    monkeypatch.setattr(agent, "_compile_code", lambda code, t: {"success": True, "errors": [], "output_path": "/tmp/x.png"})

    result = agent.check("ORIGINAL", "question")

    assert result["success"] is True
    assert result["code"] == "REVISED"


def test_check_keeps_working_code_when_the_revision_breaks(monkeypatch):
    agent = _check_agent_without_network()
    agent.client = _fake_client("BROKEN")
    monkeypatch.setattr(agent, "_verify_with_gpt4o", lambda code, q: {"is_complete": False, "suggestions": "fix it"})

    def compile_code(code, code_type):
        ok = code == "ORIGINAL"
        return {"success": ok, "errors": [] if ok else ["boom"], "output_path": "/tmp/x.png" if ok else None}

    monkeypatch.setattr(agent, "_compile_code", compile_code)

    result = agent.check("ORIGINAL", "question")

    assert result["success"] is True
    assert result["code"] == "ORIGINAL"
    assert result["image_path"] == "/tmp/x.png"
