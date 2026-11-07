import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'backend'))
from app.schemas.diagram_generate import DiagramGenerateRequest
results=[]
for case in json.loads(Path(sys.argv[1]).read_text()):
    try:
        value=DiagramGenerateRequest.model_validate(case['body']).model_dump(mode='json')
        results.append({'id':case['id'],'ok':True,'value':value})
    except Exception as exc:
        results.append({'id':case['id'],'ok':False,'errors':[{'type':e['type'],'loc':list(e['loc']),'msg':e['msg']} for e in exc.errors()] if hasattr(exc,'errors') else [{'type':type(exc).__name__,'msg':str(exc)}]})
print(json.dumps(results,ensure_ascii=False))
