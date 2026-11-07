import copy, itertools, json, random, subprocess
from pathlib import Path
from types import SimpleNamespace
from evodesign.agentic_system import quality_policy as q
from evodesign.agentic_system.verification_stage.critic.critic_agent import _coerce_critique
from evodesign.agentic_system.verification_stage.state import VerifierState
from evodesign.agentic_system.refinement_stage.state import VerifierRefinerState,IterationLog,EditOp
from evodesign.agentic_system.iterative_workflow import IterativeRefinerWorkflow,_mark_convergence
from evodesign.agentic_system.verification_stage.checks.finding import Finding
from evodesign.agentic_system.verification_stage.checks.aggregator import run_all_checks
from evodesign.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
D=Path(__file__).resolve().parent
R=D.parents[4]
cs=[]
def add(op,**x): cs.append({'id':len(cs),'op':op,**x})
def ns(v):
 if isinstance(v,dict): return SimpleNamespace(**{k:ns(x) for k,x in v.items()})
 if isinstance(v,list): return [ns(x) for x in v]
 return v
for score in [None,False,True,0,6.499999,6.5,6.999999,7,7.000001,10,11]:
 for findings in [{},{'minor':1},{'major':1},{'critical':1},{'info':9},{'critical':0,'major':0,'minor':0}]:
  for violations in [[],['visible constraint']]:
   a={'score':score,'findings':findings,'constraint_violations':violations}
   add('quality',fn='needs_refinement',args=[a]);add('quality',fn='quality_status',args=[a])
for old,new in itertools.product([None,False,True,0,6.5,7,7.5,8,10],repeat=2):
 a={'score':old,'findings':{'major':0,'minor':1},'constraint_violations':[]}
 b={'score':new,'findings':{'major':0,'minor':0},'constraint_violations':[]}
 add('quality',fn='quality_regressed',args=[a,b]);add('quality',fn='verified_learning_gain',args=[a,b])
for value in [None,False,True,-1,0,1,6.99999,7,10,11,'',' ','7','7.0','7_','_7','7__0','nan','Infinity','١',[],{},[7]]:
 dim={'score':value}
 add('critique',data={'structure':dim,'styling':dim,'layout':dim,'overall_score':value})
for key, values in {'max_iterations':['1.0','2.0','20.0',1,20,0,21,True,'1e0','1_0'], 'best_findings_score':['NaN','Infinity','-Infinity','1_0','١','0x10','0b10',None,2], 'current_iteration':['1.0','-1.0',1,-1]}.items():
 for value in values: add('refiner_state',data={'manifest_path':'m','image_path':'i',key:value})
for v in ['oops','1.0','1',1.5,None,{},[],False]:
 add('verifier_state',data={'manifest_path':'m','image_path':'i','objective_summary':{'major':v},'status':'reported'})
for score in [None,6.9,7]:
 for edits in [False,True]:
  for sev in [None,'minor','major','critical','info']:
   findings=[] if sev is None else [{'category':'test','severity':sev,'message':'a'}]
   add('convergence',data={'manifest_path':'m','image_path':'i','initial_report':{'subjective':{'overall_score':score}}},before={'critical':0,'major':0,'minor':1},findings=findings,edits=edits,iteration=1)
for status,current,maximum,termination,converged in [('init',0,3,None,False),('failed',0,3,None,False),('init',1,3,'stagnant',False),('init',1,3,None,True),('init',3,3,None,False),('init',20,20,None,False),('init',19,20,None,False)]:
 add('after_iteration',data={'manifest_path':'m','image_path':'i','status':status,'current_iteration':current,'max_iterations':maximum,'termination_reason':termination,'converged':converged})
for edits in [True,False]:
 for sev in [None,'minor','major']:
  add('convergence',data={'manifest_path':'m','image_path':'i'},before={'critical':0,'major':0,'minor':1},findings=[] if sev is None else [{'category':'test','severity':sev,'message':'a'}],edits=edits,iteration=1,repeat=True)
# Semantic protections and the dispatcher's invalid-payload path.
node={'id':'n','type':'rectangle','x':0,'y':0,'width':100,'height':80,'opacity':100,'strokeColor':'#000000','backgroundColor':'#ffffff'}
for op,payloads in {'set_position':[{'x':1,'y':2},{'x':'','y':0},{'x':None,'y':0},{'x':True,'y':False},{'x':'1__0','y':2}], 'set_size':[{'width':0,'height':80},{'width':'','height':80},{'width':-1,'height':80}], 'set_style':[{'opacity':0},{'opacity':'25'},{'opacity':''},{'strokeWidth':0},{'strokeColor':'transparent'},{'backgroundColor':'#000000'}], 'set_text':[{'text':''},{'text':'A B'},{'text':'A\nB'},{'text':None}], 'delete_element':[{}], 'set_icon':[{'name':'outline_globe'}]}.items():
 for payload in payloads:
  for semantic in [False,True]:
   m={'elements':[{**node, 'text':'A B','originalText':'A B'}],'_meta':{'id_map':{'source':'n'} if semantic else {}}}
   add('edits',manifest=m,edits=[{'op':op,'id':'n','payload':payload,'source':'llm'}])
# Realistic geometry and binding/check order; fixed seed for replay.
rng=random.Random(611)
for i in range(50):
 nodes=[]
 for j in range(rng.randint(1,5)):
  nodes.append({**node,'id':f'n{j}','x':rng.choice([0,20,100,100.000001,-10]),'y':rng.choice([0,20,80,100]),'width':rng.choice([0,50,100]),'height':rng.choice([0,30,80])})
 add('checks',manifest={'type':'excalidraw','version':2,'elements':nodes,'files':{}},skip=['schema','render_audit','layout_audit'])
(D/'boundary-input.json').write_text(json.dumps(cs,ensure_ascii=False,indent=1)+'\n')
def execute(c):
 try:
  op=c['op']
  if op=='quality': value=getattr(q,c['fn'])(*c['args'])
  elif op=='critique':value=_coerce_critique(c['data'],None).model_dump(mode='json')
  elif op=='refiner_state':value=VerifierRefinerState(**c['data']).model_dump(mode='json')
  elif op=='verifier_state':
   state=VerifierState(**c['data']);value={'state':state.model_dump(mode='json'),'quality_passed':state.quality_passed,'cli_exit_code':state.cli_exit_code}
  elif op=='after_iteration':
   state=VerifierRefinerState(**c['data']);workflow=object.__new__(IterativeRefinerWorkflow);value={'route':workflow._after_iteration(state),'state':state.model_dump(mode='json')}
  elif op=='convergence':
   s=VerifierRefinerState(**c['data']);l=IterationLog(iteration=c['iteration'],findings_before=c['before'])
   _mark_convergence(s,log=l,findings_after_iter=[Finding(**x) for x in c['findings']],edits_applied=c['edits'],iteration=c['iteration'])
   if c.get('repeat'):_mark_convergence(s,log=IterationLog(iteration=2,findings_before=c['before']),findings_after_iter=[Finding(**x) for x in c['findings']],edits_applied=c['edits'],iteration=2)
   value=s.model_dump(mode='json')
  elif op=='edits':
   m,o=apply_edits(c['manifest'],[EditOp(**e) for e in c['edits']],allow_icons=c.get('allow_icons',True));value={'manifest':m,'outcomes':[x.model_dump(mode='json') for x in o]}
  elif op=='checks':value=[x.to_dict() for x in run_all_checks(c['manifest'],c.get('structure'),c.get('layout'),skip_categories=c.get('skip'))]
  return {'id':c['id'],'ok':True,'value':value}
 except Exception as e:return {'id':c['id'],'ok':False,'error':type(e).__name__,'message':str(e)}
py=[execute(copy.deepcopy(c)) for c in cs]
# JSON canon is used only for non-finite pydantic outputs, not algorithm comparisons.
def encode(x):
 if isinstance(x,float) and not __import__('math').isfinite(x): return {'__nonfinite__':str(x).replace('nan','NaN').replace('inf','Infinity')}
 if isinstance(x,list):return [encode(v) for v in x]
 if isinstance(x,dict):return {k:encode(v) for k,v in x.items()}
 return x
py=encode(py)
(D/'boundary-python.json').write_text(json.dumps(py,ensure_ascii=False,indent=1)+'\n')
node='/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
subprocess.run([node,str(R/'packages/render-engine/node_modules/tsx/dist/cli.mjs'),str(D/'boundary_runner.ts')],cwd=R,check=True)
ts=json.loads((D/'boundary-ts.json').read_text())
def equal(a,b):
 if isinstance(a,bool) or isinstance(b,bool):return type(a) is bool and type(b) is bool and a==b
 if isinstance(a,(int,float)) and isinstance(b,(int,float)):return a==b
 if type(a) is not type(b):return False
 if isinstance(a,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
 if isinstance(a,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
 return a==b
mismatches=[]
for c,a,b in zip(cs,py,ts):
 if a['ok'] and b['ok'] and equal(a['value'],b['value']):continue
 if not a['ok'] and not b['ok'] and a['error']==b['error'] and a['message']==b['message']:continue
 mismatches.append({'case':c,'python':a,'ts':b})
(D/'boundary-diffs.json').write_text(json.dumps(mismatches,ensure_ascii=False,indent=1)+'\n')
print(json.dumps({'cases':len(cs),'exact_equal':len(cs)-len(mismatches),'differences':len(mismatches),'by_op':{op:sum(c['case']['op']==op for c in mismatches) for op in set(c['op'] for c in cs)}}))
