import json, subprocess, types
from pathlib import Path
from evodesign.agentic_system.generation_stage.styling.styling_agent import StylingAgent
from evodesign.agentic_system.generation_stage.structure.schemas import validate_structure_instantiation
from evodesign.agentic_system.generation_stage.styling.schemas import validate_styling_instantiation
ROOT=Path(__file__).resolve().parents[5]
source=subprocess.check_output(['git','show','1ac838f:evodesign/agentic_system/generation_stage/styling/styling_agent.py'],cwd=ROOT,text=True)
mod=types.ModuleType('evodesign.agentic_system.generation_stage.styling.audit_original')
mod.__package__='evodesign.agentic_system.generation_stage.styling'
exec(compile(source,'git:1ac838f/styling_agent.py','exec'),mod.__dict__)
old=object.__new__(mod.StylingAgent)
new=object.__new__(StylingAgent)
styles=[{'n':{'shape':'rectangle','strokeColor':'#333333','backgroundColor':'#ffffff','icon':'outline_globe'}},{'n':{'shape':'rectangle','strokeColor':'#333333','backgroundColor':'#ffffff','props':{'icon':'outline_globe'}}},{'__proto__':{'shape':'rectangle','label':{'text':'A'},'strokeColor':'#333333','backgroundColor':'#ffffff'}}]
results=[]
for raw in styles:
 before=old._postprocess_styling_json(raw)
 after=new._postprocess_styling_json(raw)
 results.append({'input':raw,'original_A':before,'current_B':after})
structure={'chart_type':'flowchart','nodes':[{'id':'__proto__','label':'A','class':'step'}],'edges':[],'groups':[]}
validated_structure=validate_structure_instantiation(structure)
validated_style=validate_styling_instantiation(results[-1]['current_B'],validated_structure,canvas_library='excalidraw')
output={'before_after':results,'prototype_structure':validated_structure,'prototype_style':validated_style}
Path(__file__).with_name('baseline-diff.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(output,ensure_ascii=False))
