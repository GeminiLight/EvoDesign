"""The render engine must run unchanged where langchain, langgraph and Pillow
are unavailable (the browser build), with identical output.

python-dotenv is imported only when a .env file exists, which the browser
build never ships, so it is not blocked here (a developer checkout has one).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evodesign.agentic_system.render_engine.state import WorkflowState
from evodesign.agentic_system.render_engine.workflow import RenderWorkflow

from .fixtures.new_type_scenes import ALL

REPO = Path(__file__).resolve().parents[3]


def _render(name, *, sequential):
    structure, layout = ALL[name]()
    state = WorkflowState(structure_instantiation=structure, layout_instantiation=layout,
                          canvas_library="excalidraw")
    return RenderWorkflow("excalidraw", sequential=sequential).run(state).diagram_manifest


def _digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize("name", sorted(ALL))
def test_sequential_chain_matches_the_langgraph_chain(name):
    assert _digest(_render(name, sequential=True)) == _digest(_render(name, sequential=False))


_BLOCKED_RUN = r"""
import hashlib, importlib.abc, json, sys
BLOCKED = ("langchain", "langchain_core", "langgraph", "langsmith", "PIL")
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"blocked for the browser build: {name}")
sys.meta_path.insert(0, Block())
from evodesign.agentic_system.render_engine.state import WorkflowState
from evodesign.agentic_system.render_engine.workflow import RenderWorkflow
from evodesign.tests.render_engine.fixtures.new_type_scenes import ALL
out = {}
for name, build in ALL.items():
    structure, layout = build()
    state = WorkflowState(structure_instantiation=structure, layout_instantiation=layout, canvas_library="excalidraw")
    manifest = RenderWorkflow("excalidraw").run(state).diagram_manifest
    out[name] = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
loaded = sorted({m.split(".")[0] for m in sys.modules} & set(BLOCKED))
print(json.dumps({"digests": out, "loaded": loaded}))
"""


def test_render_engine_runs_without_agent_and_imaging_dependencies():
    result = subprocess.run([sys.executable, "-c", _BLOCKED_RUN], cwd=REPO, capture_output=True, text=True,
                            timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["loaded"] == []
    assert report["digests"] == {name: _digest(_render(name, sequential=False)) for name in ALL}
