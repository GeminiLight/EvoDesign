# EvoDesign in your browser

[Open the online workspace](https://evodesign.vercel.app/) · [Project website](https://tianfu.wang/EvoDesign/) · [Paper](https://arxiv.org/abs/2604.09568)

Start directly with the shared **GLM-5.3-Flash** demo; no API key or EvoDesign account is required. To use your own model, open **Model settings → Your own model**, enter an **OpenAI-compatible Chat Completions endpoint**, model identifier and API key, read the model catalog with **Check connection**, then save. The model ID field supports searching the returned catalog and manual entry. The check uses only a metadata GET request: it sends no prompt and never falls back to a generation call. Directory access does not prove generation permissions, balance or Chat Completions compatibility. Providers without a catalog can still be configured manually. Previously configured custom models stay selected until you choose the shared demo.

Describe a diagram, choose optional icons, and generate. Select an object before asking for a local edit. Projects and snapshots stay on this browser and origin; export an editable `.excalidraw` copy as a backup, or PNG/SVG for sharing. In **DNA**, add a preference in your own words and enable the rules you want included in subsequent requests.

## Choose the edition that fits

| | Browser edition | Full local edition |
| --- | --- | --- |
| Setup | Shared demo or your own API settings | Python, Node.js and model configuration |
| Generation | Model-generated graph plan + local Dagre layout; dedicated sequence layout | Python structure, styling, layout and rendering agents |
| Review | Optional second model call for semantic content review | Verification and optional visual refinement |
| Editing | Native Excalidraw tools; selected-object AI text, color, size, position or deletion edits | Full workspace and backend editing pipeline |
| Memory | Locally managed preferences included in prompts | Personal memory plus retrieval and expertise evolution |
| Storage | This browser only; no account or cross-device sync | Local backend or your own hosted database |

Browser diagrams are limited to 60 nodes and 120 connections. AI edits update existing selected objects and bound labels; use canvas tools to add new objects. The online edition is a lightweight product path, **not a reproduction of the paper's full pipeline or evaluation**. It does not assign visual quality scores or claim automatic expertise learning.

## Shared demo and privacy

The default demo sends diagram content through `/api/model` on Vercel to BigModel's general API using `glm-5.3-flash`. The function supplies fixed diagram/edit prompts, bounds requests and output, and keeps the shared credential on the server. It is not a general API or CORS proxy. The application does not archive model request bodies or completions on the server. Projects, editable scenes and personal design preferences stay in your browser.

The shared service reserves a conservative token allowance before each call, with independent daily, concurrent and visitor limits. Its Redis namespace stores only counters, short-lived request leases and daily hashes of visitor IPs; it stores no prompts, raw IPs or diagrams. Generating with review uses two requests; an edit uses one. Connection checks use the status endpoint and do not reserve an inference allowance. If the demo is busy or reaches its allowance, retry later or switch to your own model. Turning off review reduces calls. There is no automatic switch from your own provider to the shared service.

## Your own model: keys and provider compatibility

- In **Your own model** mode, requests go directly to the endpoint you specify. EvoDesign and Vercel do not receive your model key or model request body.
- The key is kept in the current tab's session storage by default. “Remember the key on this device” explicitly opts into local storage. This is browser storage, not an encrypted vault; use a limited provider key and avoid remembering it on shared devices.
- “Forget saved key” removes both copies. Changing the endpoint in the form clears the entered key. Keys are not included in diagram snapshots or exports.
- Your provider must allow cross-origin browser requests (**CORS**) from the app's origin, including `Authorization` and `Content-Type` headers. OpenAI-compatible protocol support alone does not guarantee this. Some coding-plan endpoints only support their approved clients.
- A network/CORS error cannot be fixed by changing an API key. Use an endpoint that permits browser access, select the shared demo, or run the full local edition.
- HTTPS endpoints are required. Loopback HTTP endpoints are allowed for local development, subject to the browser's local-network permissions. Redirects are rejected to avoid forwarding credentials to another destination.
- Usage is billed by your provider. Generating with review uses two model calls; local editing uses one. “Test connection” also makes a small model call.

### Tested browser connection options

[OpenRouter](https://openrouter.ai/docs/quickstart) accepts browser requests at `https://openrouter.ai/api/v1` with your own key and an exact model ID from its catalog. The settings dialog includes a shortcut for this base URL; it does not supply a key or choose a paid model for you.

For a key-free experiment, the [Pollinations Classic API](https://github.com/pollinations/pollinations/blob/master/APIDOCS.md) exposes `https://text.pollinations.ai/v1` with model `openai-fast`. Its anonymous service is best effort, has a small output budget and a per-IP cooldown. Use **Advanced model options → Reasoning effort → Low** for this model; the default reasoning consumed the output budget in our complex-diagram test. Send only non-sensitive examples to this public experimental service. Availability and limits can change.

Reasoning effort is optional and omitted by default. Only set it for a provider/model that supports `reasoning_effort`. A successful connection check confirms reachability, not diagram quality or sufficient quota. When the provider returns an explicit `Retry-After` of up to 60 seconds with a rate-limit response, the app waits and retries once; cancellation interrupts the wait. Other failures are shown without automatic retries.

Kimi Coding's endpoints did not allow browser cross-origin requests in our check. A working key in a coding client does not make that endpoint usable directly from the public website. The [six-case validation record](browser-validation-2026-10-27.md) distinguishes four direct-browser workflows from two Kimi workflows tested with a temporary local development connection, and documents provider outages and measured timings.

## Run or deploy the browser edition

From the repository root:

```sh
npm ci --prefix frontend
npm --prefix frontend run dev:browser
# Open http://127.0.0.1:5176

npm --prefix frontend run build:browser
```

The local browser dev server also mounts `/api/model`. Put `DEMO_GLM_API_KEY`
in a **repository-root `.env.local`** and restart the dev server to enable
GLM-5.3-Flash locally. Optional `DEMO_GLM_BASE_URL` selects the BigModel general
API (`https://open.bigmodel.cn/api/paas/v4`, default) or your authorized Coding
API (`https://open.bigmodel.cn/api/coding/paas/v4`). Other destinations are rejected.
These values stay on the server and are never exposed through `VITE_*` or
bundled in the page. Only loopback connections can use this local endpoint.
The same fixed diagram/edit prompts and input/output limits are reused.
Local token, concurrency and visitor counters need no Redis and reset when the
dev server restarts; the deployed service keeps its distributed Redis budget.
Existing custom-model settings remain available; select the default demo in
Model settings to use GLM. On Node 24+, `DEMO_USE_ENV_PROXY=1` enables the
proxy already specified by your shell's `HTTPS_PROXY`/`HTTP_PROXY` settings.

Deploy `frontend/dist` to a static host with SPA fallback. The repository-root `vercel.json` builds this edition automatically. Import the public repository into Vercel with the **repository root** selected; the bundled icon catalog is shared with the engine outside `frontend/`.

For a static host, custom-model mode works without server secrets; shared-demo discovery falls back gracefully when `/api/model` is absent. For the Vercel demo, configure `DEMO_GLM_API_KEY`, `DEMO_REDIS_URL` and `DEMO_REDIS_TOKEN` as server-only secrets. Optional controls are `DEMO_DAILY_TOKENS` (default 2,000,000 reserved tokens), `DEMO_CONCURRENCY` (4) and `DEMO_VISITOR_REQUESTS` (40 requests per IP per UTC day). Missing budget configuration disables the shared service rather than permitting unbounded requests. These reservations are an upper bound, not a provider billing report.

**Never put secrets in `VITE_*` variables or tracked files.** The function uses the general BigModel API endpoint, not Coding Plan quota. Ordinary `npm run dev` / `npm run build` still use the full backend mode; the `browser` build mode selects the browser adapter.

## 中文简要说明

打开[在线工作区](https://evodesign.vercel.app/)，可以直接使用 GLM-5.3-Flash 默认体验，无需填写密钥。图表内容经 Vercel 转发给智谱通用 API，共享密钥仅留在服务端，并设有共享额度与并发上限。也可在“模型设置 → 自己的模型”中填写 API 地址、模型 ID 和 key。自定义接口须允许浏览器跨域请求；密钥默认保存在当前标签页，可主动选择在本机记住，也可以随时清除。已有的自定义模型不会被自动替换。

在线版支持生成、可选图标、内容评审、选中对象的局部修改、本机项目保存、重新打开和 PNG / SVG / 可编辑文件导出。设计偏好可以手动添加、编辑和启停。项目保存在当前浏览器，不跨设备同步，清理网站数据会删除本机项目，请及时导出备份。

在线版使用模型生成结构、浏览器完成布局，是轻量体验路径。论文中的多智能体算法、视觉评审、自动经验学习和评测工具仍包含在完整本地版中。

### Creation from Home

Choose a diagram type (Adaptive by default), optional node icons and model in the Home composer. Manage DNA from its page or **Preferences → DNA preferences**; enabled preferences are applied automatically to subsequent requests. **Start creating** launches generation in the workspace directly; it does not open another setup dialog. A missing model configuration opens Model settings on Home while preserving the input. The startup draft retains the icon choice for recovery and retry. Diagram creation and optional review still use the provider’s generation API and normal allowance.
