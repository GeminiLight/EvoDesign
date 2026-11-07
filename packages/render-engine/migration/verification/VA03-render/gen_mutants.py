import json, logging
from copy import deepcopy
from pathlib import Path
from evodesign.agentic_system.render_engine.state import WorkflowState
from evodesign.agentic_system.render_engine.workflow import RenderWorkflow
logging.disable(logging.CRITICAL)
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
fx=json.loads((ROOT/'fixtures/stages/configured-model__quickstart-service.json').read_text())
wf=RenderWorkflow(canvas_library='excalidraw')
cases=[]
for new_id in ['n_control', '__proto__', 'constructor', 'toString']:
 old=fx['input']['structure_instantiation']['nodes'][0]['id']
 def tr(v):
  if isinstance(v,str): return v.replace(old,new_id)
  if isinstance(v,list): return [tr(x) for x in v]
  if isinstance(v,dict): return {tr(k):tr(x) for k,x in v.items()}
  return v
 inp=tr(deepcopy(fx['input']))
 state=WorkflowState(**deepcopy(inp),canvas_library='excalidraw')
 snaps=[]; error=None
 for node,run in wf._excalidraw_nodes():
  try: state=run(state)
  except Exception as e: error={'node':node,'name':type(e).__name__,'message':str(e)};break
  snaps.append({'node':node,'layout_instantiation':deepcopy(state.layout_instantiation),'diagram_manifest':deepcopy(state.diagram_manifest),'validation_report':deepcopy(state.validation_report)})
 cases.append({'case':new_id,'input':inp,'snapshots':snaps,'error':error})
(OUT/'mutants-python.json').write_text(json.dumps(cases,ensure_ascii=False,indent=1)+'\n')
print([(x['case'],len(x['snapshots']),x['error']) for x in cases])
