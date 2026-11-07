import json
from pathlib import Path
from langchain_openai import ChatOpenAI
import httpx
content=[{"type":"reasoning","text":None},{"type":"text","text":"[]"}]
def respond(request):
 return httpx.Response(200,json={"id":"audit","choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}]})
model=ChatOpenAI(model="fake",api_key="audit-placeholder",base_url="https://example.invalid/v1",streaming=False,max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(respond)))
try:
 response=model.invoke("test")
 result={"sent_content":content,"received_content":response.content}
except Exception as e:
 result={"error":type(e).__name__,"message":str(e)}
Path(__file__).with_name("content-parts-python-transport.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
