import json
import os
import subprocess
import sys
import types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
PKG=ROOT/'packages/render-engine'
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(PKG/'tools'))
import record_web_runs as rec
SPEC=next(x for x in rec.WEB_SPECS if x['name']=='paper_full_f2__web')
if '--child' in sys.argv:
    kind=sys.argv[-1]
    if kind=='A':
        from evodesign.agentic_system.generation_stage.styling import styling_agent as current
        source=subprocess.check_output(['git','show','1ac838f:evodesign/agentic_system/generation_stage/styling/styling_agent.py'],cwd=ROOT,text=True)
        module=types.ModuleType('evodesign.agentic_system.generation_stage.styling._audit_original')
        module.__package__='evodesign.agentic_system.generation_stage.styling'
        sys.modules[module.__name__]=module
        exec(compile(source,'git:1ac838f/styling_agent.py','exec'),module.__dict__)
        # These are the only two production methods changed A→B, verified by git diff.
        for name in ('_postprocess_styling_json','_normalize_icon_name'):
            setattr(current.StylingAgent,name,getattr(module.StylingAgent,name))
    dest=OUT/f'paper-python-{kind}'
    sys.exit(rec.worker(SPEC,'replay',dest,PKG/'fixtures/web_runs/paper_full_f2__web'))
rows=[]
for kind in ('A','B'):
    env=rec.run_environment(SPEC,'http://127.0.0.1:3001/renderers/excalidraw')
    result=subprocess.run([sys.executable,str(Path(__file__)), '--child',kind],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/f'paper-python-{kind}.log').write_text(result.stdout)
    dest=OUT/f'paper-python-{kind}'
    mismatch=json.loads((dest/'mismatch.json').read_text()) if (dest/'mismatch.json').exists() else None
    outcome={'baseline':kind,'exit_code':result.returncode,'mismatch':mismatch}
    if dest.exists() and result.returncode==0:
        outcome['diff_vs_historical_fixture']=rec.compare_dirs(PKG/'fixtures/web_runs/paper_full_f2__web',dest)
    rows.append(outcome)
(OUT/'paper-baseline-comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(rows,ensure_ascii=False,indent=2)[:5000])
