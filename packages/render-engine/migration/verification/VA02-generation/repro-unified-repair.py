import copy,json
from pathlib import Path
from types import SimpleNamespace
from evodesign.agentic_system.generation_stage.unified.workflow import UnifiedGeneratorWorkflow
from evodesign.agentic_system.generation_stage.unified.generator import UnifiedGenerator
from evodesign.agentic_system.generation_stage.unified.state import UnifiedWorkflowState
ROOT=Path(__file__).resolve().parents[5]
raw=json.loads((ROOT/'packages/render-engine/fixtures/runs/ecommerce_aes__unified/artifacts/1_unified/transport/attempt_01_output.txt').read_text())
state=UnifiedWorkflowState(diagram_manifest=copy.deepcopy(raw),candidate_output=copy.deepcopy(raw),diagram_type='architecture')
workflow=object.__new__(UnifiedGeneratorWorkflow)
state=workflow._run_normalizer(state)
state.validation_error='controlled audit validation feedback'
state.generation_attempts=[{'stage':'validate','output':copy.deepcopy(state.diagram_manifest)}]
agent=object.__new__(UnifiedGenerator)
agent.stream_journal=SimpleNamespace(configure=lambda *args,**kwargs:None)
agent.full_domain_knowledge=False
agent._system_prompt='audit'
agent._task_prompt='{{text_content}}'
agent._last_raw_output=None
captured=[]
def invoke(messages):
 captured.extend(messages)
 return copy.deepcopy(raw)
agent.invoke_with_history=invoke
agent.run(state)
output={'assistant_repair_echo':next(m['content'] for m in captured if m['role']=='assistant')}
Path(__file__).with_name('unified-repair-python.json').write_text(json.dumps(output,ensure_ascii=False,indent=1)+'\n')
print(len(output['assistant_repair_echo']))
