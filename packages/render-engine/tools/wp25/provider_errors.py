# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, os
for k in list(os.environ):
    if k.startswith(('OPENAI','LLM_','ANTHROPIC')): del os.environ[k]
from evodesign.core.llm_factory import LLMFactory
from evodesign.core import base_agent as ba
out={}
for sc in ['s429q','s429','s503','s401','s400','s404','slow','badsse','cut','empty','s500']:
    m=LLMFactory.create(model='m', model_provider='openai', base_url=f'http://127.0.0.1:18765/{sc}/v1', timeout=1)
    try:
        r=m.invoke('hi'); out[sc]={'ok':True,'content':r.content}
    except BaseException as e:
        out[sc]={'type':type(e).__name__,'retryable':ba._is_retryable_exception(e),'permanent':ba._is_permanent_http_error(e),'quota':ba._is_provider_quota_exhausted(e),'status':ba._status_code_from_exception(e)}
print(json.dumps(out,indent=0))
