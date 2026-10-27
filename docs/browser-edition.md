# EvoDesign in your browser

[Open the online workspace](https://evodesign.vercel.app/) · [Project website](https://tianfu.wang/EvoDesign/) · [Paper](https://arxiv.org/abs/2604.09568)

The online edition runs entirely in your browser. Bring an **OpenAI-compatible Chat Completions endpoint**, its model identifier and your own API key. Open **Model settings**, fill in those three fields, test the connection, then save. No EvoDesign account or backend is needed.

Describe a diagram, choose optional icons, and generate. Select an object before asking for a local edit. Projects and snapshots stay on this browser and origin; export an editable `.excalidraw` copy as a backup, or PNG/SVG for sharing. In **Design memory**, add a preference in your own words and enable the rules you want included in subsequent requests.

## Choose the edition that fits

| | Browser edition | Full local edition |
| --- | --- | --- |
| Setup | API settings in the page | Python, Node.js and model configuration |
| Generation | Model-generated graph plan + local Dagre layout; dedicated sequence layout | Python structure, styling, layout and rendering agents |
| Review | Optional second model call for semantic content review | Verification and optional visual refinement |
| Editing | Native Excalidraw tools; selected-object AI text, color, size, position or deletion edits | Full workspace and backend editing pipeline |
| Memory | Locally managed preferences included in prompts | Personal memory plus retrieval and expertise evolution |
| Storage | This browser only; no account or cross-device sync | Local backend or your own hosted database |

Browser diagrams are limited to 60 nodes and 120 connections. AI edits update existing selected objects and bound labels; use canvas tools to add new objects. The online edition is a lightweight product path, **not a reproduction of the paper's full pipeline or evaluation**. It does not assign visual quality scores or claim automatic expertise learning.

## Keys and provider compatibility

- Requests go directly to the endpoint you specify. EvoDesign and Vercel do not receive your model key or model request body.
- The key is kept in the current tab's session storage by default. “Remember the key on this device” explicitly opts into local storage. This is browser storage, not an encrypted vault; use a limited provider key and avoid remembering it on shared devices.
- “Forget saved key” removes both copies. Changing the endpoint in the form clears the entered key. Keys are not included in diagram snapshots or exports.
- Your provider must allow cross-origin browser requests (**CORS**) from the app's origin, including `Authorization` and `Content-Type` headers. OpenAI-compatible protocol support alone does not guarantee this. Some coding-plan endpoints only support their approved clients.
- A network/CORS error cannot be fixed by changing an API key. Use an endpoint that permits browser access, or run the full local edition. There is no public CORS proxy or shared fallback key.
- HTTPS endpoints are required. Loopback HTTP endpoints are allowed for local development, subject to the browser's local-network permissions. Redirects are rejected to avoid forwarding credentials to another destination.
- Usage is billed by your provider. Generating with review uses two model calls; local editing uses one. “Test connection” also makes a small model call.

## Run or deploy the browser edition

From the repository root:

```sh
npm ci --prefix frontend
npm --prefix frontend run dev:browser
# Open http://127.0.0.1:5176

npm --prefix frontend run build:browser
```

Deploy `frontend/dist` to a static host with SPA fallback. The repository-root `vercel.json` builds this edition automatically. Import the public repository into Vercel with the **repository root** selected; the bundled icon catalog is shared with the engine outside `frontend/`.

**Do not add model API keys to Vercel environment variables, `VITE_*` variables or tracked files.** Users configure their own credentials in the page. Ordinary `npm run dev` / `npm run build` still use the full backend mode; the `browser` build mode selects the browser adapter.

## 中文简要说明

打开[在线工作区](https://evodesign.vercel.app/)，在“模型设置”中填写 API 地址、模型 ID 和自己的 key。服务商必须支持浏览器跨域请求；仅有 OpenAI 兼容格式还不够。密钥默认保存在当前标签页会话，可主动选择在本机记住，也可以随时清除。

在线版支持生成、可选图标、内容评审、选中对象的局部修改、本机项目保存、重新打开和 PNG / SVG / 可编辑文件导出。设计偏好可以手动添加、编辑和启停。项目保存在当前浏览器，不跨设备同步，清理网站数据会删除本机项目，请及时导出备份。

在线版使用模型生成结构、浏览器完成布局，是轻量体验路径。论文中的多智能体算法、视觉评审、自动经验学习和评测工具仍包含在完整本地版中。
