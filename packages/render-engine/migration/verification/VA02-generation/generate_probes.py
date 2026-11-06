import ast, copy, hashlib, importlib, json, random, subprocess, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'packages/render-engine/migration/modules.json').read_text())
selected=[m for m in manifest['modules'] if m['wp'] in ['WP15','WP16','WP17','WP18'] or m.get('python') in ['evodesign.core.base_agent','evodesign.utils.llm_output','evodesign.agentic_system.common.self_consistency','evodesign.agentic_system.common.task_prompts','evodesign.agentic_system.common.skill_loader','evodesign.agentic_system.common.domain_knowledge_loader']]
modules={m['python']:importlib.import_module(m['python']) for m in selected}
cases=[]
def add(mod,fn,args,tag=''):
 initial_args=copy.deepcopy(args)
 args=copy.deepcopy(args)
 try:
  module=modules[mod]
  if fn=='StylingAgent._postprocess_styling_json': result=module.StylingAgent._postprocess_styling_json(object.__new__(module.StylingAgent),*args)
  elif fn=='StylingAgent.postprocess_validate':
   processed=module.StylingAgent._postprocess_styling_json(object.__new__(module.StylingAgent),args[0]); result=modules['evodesign.agentic_system.generation_stage.styling.schemas'].validate_styling_instantiation(processed,args[1],canvas_library='excalidraw')
  elif fn=='convert_json_output': result=module.convert_json_output(args[0],strict_response=args[1])
  else: result=getattr(module,fn)(*args)
  outcome={'result':result,'args_after':args}
 except Exception as e: outcome={'error':{'type':type(e).__name__,'message':str(e)},'args_after':args}
 case={'id':len(cases),'module':mod,'function':fn,'args':initial_args,'tag':tag,'expected':outcome}
 cases.append(case)
G='evodesign.agentic_system.generation_stage.'
for v in ['',None,False,True,0,1,1.5,'中文😀','{{runtime_directives}}',{},[],['a']]:
 add('evodesign.core.base_agent','_render_template',['{{ x }} / {{missing}} / {{runtime_directives}}',{'x':v,'runtime_directives':'LOCKED'}])
texts=['{}','[]','null','true','1','{"label":"中文😀"}','{"a":1,}','{"a": 1 "b":2}','{"a":true "b":2}','prefix {"x":1} suffix','```json\n{"x":1}\n```','{"broken":{"x":1},} [2,3]','{"a":"line\nraw"}','{"x":NaN}','{"x":Infinity}','{bad} {"good":1}']
for text in texts:
 for strict in [False,True]: add('evodesign.utils.llm_output','convert_json_output',[text,strict])
scenes=[{'type':'excalidraw','elements':[{'id':'中文😀','type':'rectangle','x':1.0}, {'id':'second','text':'a\\b"c'}],'files':{},'_meta':{'x':1}}, {'elements':[],'appState':{}}, {'elements':[{},4],'files':{}}]
for scene in scenes:
 text=json.dumps(scene,ensure_ascii=False)
 for i in range(len(text)+1): add(G+'unified.continuation','complete_scene_prefix',[text[:i]])
for n in range(0,37):
 for edge_count in [0,n,2*n]:
  for label in ['中😀'*7,'x'*15,'x'*96]:
   structure={'nodes':[{'id':f'n{i}','label':label} for i in range(n)],'edges':[{'id':f'e{i}'} for i in range(edge_count)],'groups':[]}
   add(G+'layout.viewport_profile','choose_layout_viewport',[structure],f'boundary_n{n}_e{edge_count}')
   cases[-1]['expected']['result']=vars(cases[-1]['expected']['result'])
for key in ['n','__proto__','constructor','toString','hasOwnProperty','中文😀']:
 for icon in [None,'outline_globe',{'name':'home'},False,{},['home']]:
  style={key:{'shape':'rectangle','label':{'text':'节点'},'strokeColor':'#333333','backgroundColor':'#ffffff','icon':icon}}
  structure={'chart_type':'flowchart','nodes':[{'id':key,'label':'节点','class':'step'}],'edges':[],'groups':[]}
  add(G+'structure.schemas','validate_structure_instantiation',[structure],'special_id')
  add(G+'styling.styling_agent','StylingAgent._postprocess_styling_json',[style],'special_id')
  add(G+'styling.styling_agent','StylingAgent.postprocess_validate',[style,structure],'special_id')

structure={'chart_type':'flowchart','nodes':[{'id':'a','class':'step','label':'节点😀'},{'id':'b','class':'step','label':'B'}], 'edges':[{'id':'edge:a2b','source':'a','target':'b','class':'transition'}], 'groups':[]}
style={'a':{'shape':'rectangle','label':{'text':'节点😀'},'strokeColor':'#333333','backgroundColor':'#ffffff'},'b':{'shape':'rectangle','label':{'text':'B'},'strokeColor':'#333333','backgroundColor':'#ffffff'},'edge:a2b':{'strokeColor':'#333333'}}
compact={'instantiation':{'format':'style_templates_v1','styles':{'s':{'shape':'rectangle','strokeColor':'#333333','backgroundColor':'#ffffff'}},'elements':{'a':'s','b':'s'},'edge_default':{'strokeColor':'#333333'}}}
layout={'instantiation':{'a':[80,80,160,64],'b':[80,220,160,64],'edge:a2b':['bottom','top']}}
r=random.Random(6209)
values=[None,False,True,0,1,-1,1.5,'', 'constructor', '中文😀',[],{},['a'],{'x':1}]
def mutate(x):
 x=copy.deepcopy(x); containers=[]
 def visit(o):
  if isinstance(o,(dict,list)):
   containers.append(o)
   for v in (o.values() if isinstance(o,dict) else o):visit(v)
 visit(x)
 o=r.choice(containers)
 if isinstance(o,dict):
  if not o: o['x']=r.choice(values)
  else:
   key=r.choice(list(o))
   if r.random()<.25:del o[key]
   else:o[key]=copy.deepcopy(r.choice(values))
 elif o:
  i=r.randrange(len(o))
  if r.random()<.25:del o[i]
  else:o[i]=copy.deepcopy(r.choice(values))
 return x
for i in range(550):
 add(G+'structure.schemas','validate_structure_instantiation',[mutate(structure)],'mutation')
for i in range(220):
 add(G+'compact_decisions','expand_styling_output',[mutate(compact),structure],'mutation')
 add(G+'compact_decisions','expand_layout_output',[mutate(layout),structure],'mutation')
for i in range(60):
 cells={'a':[i%2,0],'b':[(i//2)%2,1]}
 grid={'instantiation':{'format':'flow_grid_v1','nodes':cells,'edges':{'edge:a2b':['bottom','top']}}}
 add(G+'layout.flow_grid','expand_flow_grid',[grid,structure,style],'grid')
# Independently reconstruct every curated type/stage prompt and palette/flag combination.
knowledge=modules['evodesign.agentic_system.common.domain_knowledge_loader'].load_domain_knowledge()
for typ in list(knowledge)+[None,'','unknown_type']:
 add('evodesign.agentic_system.common.domain_knowledge_loader','build_diagram_context',[typ],'prompt_resource')
 for stage in ['structure','styling','layout',None,'unknown']:
  for full in [False,True]:
   add('evodesign.agentic_system.common.domain_knowledge_loader','build_stage_knowledge',[typ,stage,full],'prompt_resource')
for palette in list(modules[G+'styling.colorful'].PALETTE_KEYS)+[None,'','unknown']:
 for icon in [False,True]:
  for compact in [False,True]:
   add(G+'styling.prompts','build_styling_task_prompt',[icon,palette,'excalidraw',compact],'prompt_resource')
for canvas in ['tldraw','unknown','Excalidraw',None]:
 for compact in [False,True]:add(G+'styling.prompts','build_styling_task_prompt',[True,None,canvas,compact],'prompt_resource')
constants=[]
for m in selected:
 module=modules[m['python']]; tree=ast.parse((ROOT/m['source']).read_text())
 for node in tree.body:
  if isinstance(node,(ast.Assign,ast.AnnAssign)):
   targets=node.targets if isinstance(node,ast.Assign) else [node.target]
   for t in targets:
    if isinstance(t,ast.Name) and t.id.isupper() and isinstance(getattr(module,t.id,None),str):
     text=getattr(module,t.id); constants.append({'module':m['python'],'name':t.id,'sha256':hashlib.sha256(text.encode()).hexdigest(),'characters':len(text)})
def sanitize(x):
 if isinstance(x,float) and not math.isfinite(x):return {'__number__':str(x)}
 if isinstance(x,(list,tuple)):return [sanitize(v) for v in x]
 if isinstance(x,dict):return {k:sanitize(v) for k,v in x.items()}
 return x
(OUT/'probes.json').write_text(json.dumps(sanitize({'modules':selected,'cases':cases,'constants':constants}),ensure_ascii=False,default=str,indent=1)+'\n')
print(json.dumps({'cases':len(cases),'constants':len(constants),'selected_modules':len(selected)}))
