"""WP33 real backend smoke; credentials remain in .env / process memory."""
import asyncio,json,os,sys,time
from pathlib import Path
from dotenv import load_dotenv
import httpx
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
load_dotenv(ROOT/'.env')
os.environ['EXCALIDRAW_RENDER_URL']='http://127.0.0.1:3001/renderers/excalidraw'
from app.config import Settings
from app.core.sse import parse_sse_event
from app.services.workflow_generate_service import WorkflowGenerateService
from evodesign.core import llm_factory
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
calls=0
original=llm_factory.init_chat_model
def count_request(request):
 global calls
 calls+=1
 if calls>40: raise RuntimeError('WP33 model call cap reached')
client=httpx.Client(event_hooks={'request':[count_request]})
def counted(**kwargs):
 kwargs['http_client']=client
 return original(**kwargs)
llm_factory.init_chat_model=counted
settings=Settings(_env_file=ROOT/'.env',results_dir=str(out/'artifacts'), design_memory_enabled=False,
 design_memory_learning=False,retain_generation_artifacts=True,llm_temperature=0.0,llm_max_tokens=8192,
 auto_refine_enabled=True,auto_refine_max_iterations=1)
service=WorkflowGenerateService(settings=settings)
prompt='A customer submits an order. The payment service authorizes payment. If payment fails, ask the customer to retry. If payment succeeds, the warehouse ships the parcel and the customer receives a confirmation.'
events=[];started=time.monotonic()
async def main():
 async for chunk in service.generate_without_render_streaming(context=prompt,requirements='Create a clear flowchart with every branch.',locked_nodes=[],current_schema=None,canvas_library='excalidraw',use_icons=False,diagram_type='flow'):
  event=parse_sse_event(chunk)
  if event: events.append({'event':event.event,'data':event.data})
asyncio.run(main())
result=next((e['data'] for e in events if e['event']=='result'),None)
(out/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=1))
summary={'side':'python','seconds':round(time.monotonic()-started,2),'model_calls':calls,'ok':result is not None,
 'generation':(result or {}).get('metrics_scores',{}).get('generation',{}),'errors':[e['data'] for e in events if e['event']=='error']}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=1))
print(json.dumps({k:v for k,v in summary.items() if k!='generation'}))
client.close()
