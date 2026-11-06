# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
# Sends one request per config in fixtures/wp25/provider_configs.json to the
# LOCAL fake server (tools/wp25/fake_llm_server.py <port> <log>) through the
# production LLMFactory; the server logs the HTTP body. No external traffic.
import json, os, sys
for k in list(os.environ):
    if k.startswith(('OPENAI', 'LLM_', 'ANTHROPIC', 'NVIDIA')): del os.environ[k]
from langchain_core.messages import SystemMessage, HumanMessage
from evodesign.core.llm_factory import LLMFactory
port = sys.argv[1]
IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
for cfg in json.load(open(sys.argv[2])):
    cfg = dict(cfg); tag = cfg.pop('tag')
    m = LLMFactory.create(base_url=f'http://127.0.0.1:{port}/{tag}/v1', **cfg)
    m.invoke([SystemMessage(content='sys 中文'), HumanMessage(content=[{'type': 'text', 'text': 'hi'}, {'type': 'image_url', 'image_url': {'url': IMG, 'detail': 'high'}}])])
print('ok')
