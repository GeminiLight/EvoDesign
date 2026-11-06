# 第三期计划：浏览器模式跑真正的流水线

## 0. 目标与边界

**目标**：前端浏览器模式（`VITE_RUNTIME_MODE=browser`，即 Vercel 上的版本）的出图，从 `frontend/src/services/browser/` 的简化流程（`diagramPlan.ts` + `scene.ts renderPlan` + `edgeRouting.ts`，单次模型调用）换成第二期迁好的 TS 流水线，**在用户浏览器里运行**。

行为基准是 backend 完整模式的 `/diagram/stream`：同样的阶段顺序、校验、修复轮次、进度事件和最终结果。浏览器版应当等于"backend 完整模式去掉持久化、账号、记忆之后"的效果。

**硬约束**
1. 用户自己的 API key 只在浏览器里使用，不发往我们的任何服务器（和现在 `modelConfig.ts` 的承诺一致）。
2. 共享 glm 额度：`/api/model` 改为"按次出图"的通用转发（§4）。
3. Python 仍是基准，不改 `evodesign/` 和 `backend/` 的 Python 代码。
4. 第一、二期对照必须保持全绿：`parity`（函数向量）、`parity:stages` 112/112、`parity:runs` 36/36、`tsc` 0 错误。
5. 不部署、不 push、不 commit；不碰 3000 端口的旧渲染服务，渲染服务用 3001。

**不在本期**：局部编辑（`editBrowserDiagram`）、tldraw、design_memory / user_memory、账号与云端项目、backend 本身的迁移。

## 1. 工作包

| WP | 内容 | 依赖 |
|---|---|---|
| WP26 | 对照数据：录制 backend 网页出图流程的事件流 | — |
| WP27 | 运行时 IO 抽象：去掉流水线对 `node:*` 的直接依赖 | — |
| WP28 | 渲染器接口 + 浏览器渲染实现（Excalidraw 导出 PNG） | WP27 |
| WP29 | 迁移 backend 出图编排层（web runtime） | WP26, WP27 |
| WP30 | 浏览器端模型调用 + 共享额度按次转发 | WP27 |
| WP31 | 浏览器打包：资源内嵌、Web Worker、包体积 | WP28, WP29, WP30 |
| WP32 | 前端接入，删除简化流程 | WP31 |
| WP33 | 真实模型冒烟（Python backend vs 浏览器版对比） | WP32 |
| WP34 | 独立验收，写 `PHASE3_REPORT.md` | 全部 |

### WP26 对照数据
- 找到 backend 完整模式出图的真实入口：前端 `apiDiagramService.streamDiagram` 请求的路由 → `WorkflowGenerateService` / `WorkflowEngineAdapter.stream_without_render` → `workflow_runtime/*`。
- 用第二期的 cassette 替身模型（`tools/llm_cassette.py`）在进程内驱动这个入口，录下每个用例的：
  - 请求体；
  - cassette；
  - SSE 事件序列（事件名 + payload）；
  - 最终 result payload；
  - 前端会用到的产物。
- 录制条件：设计记忆关、持久化关（DB 用临时 sqlite，或者直接调用 adapter 层；二者择一并写明）、渲染服务用 3001。
- 用例数 ≥ 20，复用第二期 run 的输入，并覆盖：
  - 多 agent / unified 两种模式；
  - router；
  - 校验通过；
  - 校验失败 → 修复成功 / 修复后仍未解决 / 修复失败；
  - critic 开 / 关；
  - 生成阶段出错时的错误事件。
- 每个用例录两次，归一化后必须完全一致。
- 产出：
  - `fixtures/web_runs/<case>/`
  - `tools/record_web_runs.py`
  - `test/harness/web_runs.ts`
  - `tools/parity-web.ts`（`npm run parity:web`）：逐个用例报告第一处分歧（第几次模型调用的哪个字段 / 第几个事件的哪个路径 / result 的哪个路径）。

### WP27 运行时 IO 抽象
- 新增 `src/py/fs.ts`（`RuntimeFS`：读写文本/字节、exists、mkdirp、list、remove、stat）和 `src/py/path.ts`（posix 语义的 join/dirname/basename/resolve），提供两种实现：
  - `NodeFS`：默认；
  - `MemoryFS`：内存实现，路径语义与 Node 一致。
- 同时提供：
  - 临时目录：内存下给出确定的伪路径；
  - home 目录；
  - 哈希（纯 TS 实现）；
  - gzip（选一个纯 JS 库，版本精确锁定）。
- 流水线路径上的所有模块改为只通过这些接口访问文件系统。
- 只有以下位置允许 import `node:*`：
  - `src/py/assets.ts` 的 Node provider；
  - `src/node/` 目录（新建，放 Node 专用实现）；
  - 各 `__main__.ts`；
  - `main.ts` 的命令行部分。
- PNG 编解码（`pngjs` 依赖 Buffer/zlib）改为纯 JS 实现，例如 `fast-png`，版本精确锁定：
  - 解码必须逐像素一致；
  - 编码字节不要求一致，按第二期图片比较规则比较。
- 验收：
  - 现有全部对照保持全绿；
  - 新增 `parity:runs -- --fs memory`，36/36 一致；
  - 新增检查脚本：用 esbuild 以 `platform=browser` 打包浏览器入口（WP31 之前先用 `src/agentic_system/workflow.ts` 等编排入口），不得出现任何 node 内置模块。

### WP28 渲染器
- 定义 `PngRenderer` 接口，输入输出语义与现在 `canvas_render.ts` 调用渲染页一致：
  - 输入：scene/manifest、scale、margin、viewport、timeout；
  - 输出：PNG 字节和元数据。
- Node 实现保留 playwright 方案，放进 `src/node/`，现有对照不变。
- 浏览器实现放在前端：`frontend/src/services/browser/pipelineRenderer.ts`。
  - 用 `@excalidraw/excalidraw` 的 `exportToBlob` / `exportToCanvas`，逐项复刻 `evodesign/agentic_system/tool_services` 里渲染页的导出参数：背景、padding、scale、字体加载等待、暗色模式、裁剪。
  - 先确认两边 excalidraw 版本一致（都是 ^0.18.0，以 lock 文件为准）。
- 验收：
  - 用 headless chromium 打开一个前端测试页，对 112 个阶段用例的最终 manifest 分别用浏览器实现和渲染服务出图，计算像素差；
  - 阈值写进 notes：建议逐像素差 >16 的像素占比 ≤ 0.5%，尺寸完全一致；
  - smart crop 在两边产物上结果一致；
  - 超阈值的用例逐个解释。

### WP29 web runtime
- 迁移 backend 出图编排到 `src/web_runtime/`：
  - `workflow_engine_adapter.py` 的流式部分；
  - `workflow_runtime/*`；
  - `workflow_engine_port.py`；
  - `workflow_generate_service.py` 中构造请求的部分；
  - `diagram_generation_contract.py`；
  - `schemas/diagram_generate.py` 中需要的校验；
  - SSE payload 模型；
  - `quality.py`、`refiner.py`。
- 不迁移：DB 持久化（`diagram_stream_service.persist_stream_result`）、鉴权、访客额度、设计记忆和学习任务。记忆相关做成可注入的接口，默认关闭，行为和 backend 关闭记忆时完全一致。
- 对外 API：
  - 签名：`streamDiagram(request, { chatModelFactory, renderer, fs, signal, onEvent })`；
  - `onEvent(name, payload)` 的序列必须与 backend SSE 完全一致；
  - 返回值等于 backend 最终 result payload。
- 验收：`parity:web` 全部一致；新增代码 `tsc` 0 错误。

### WP30 模型调用
- 浏览器端模型：
  - 用户自己的模型：OpenAI 兼容接口（`baseUrl` + `apiKey` + `model`，与 `modelConfig.ts` 一致），在浏览器里直接请求服务商；
  - 共享模型：一个 `BaseChatModel`，把 OpenAI 格式的请求发给 `/api/model`，并带上本次出图的令牌。
- 修复第二期验收遗留的 HTTP 差异：
  - `max_tokens` / `max_completion_tokens`、`stream_options`、`reasoning_effort` 被丢弃等参数差异；
  - 重试判断：超时是否重试、空流异常类型。
  - 对照方法：Python 用 httpx mock transport 截获 `langchain_openai` 发出的请求体，TS 用自定义 fetch 截获，对一组配置（含 vision、tools、json mode）比较请求体，必须一致（User-Agent 等传输层头除外，列出）。
- 视觉能力：模型不支持图片时，以 backend `enable_critic=false` 的语义跳过看图评审，并在结果里给出提示。不允许 silently 改变其它行为。
- `api/model.mjs`：
  - 新增 `POST /api/model/run`：签发一次出图令牌，HMAC 签名，TTL 15 分钟，Redis 记录调用次数上限（建议 40）和 token 上限（建议 400k），复用现有的预算、并发、访客限额逻辑。
  - `POST /api/model` 带令牌时，转发 OpenAI chat 请求，只放行白名单字段：
    - `messages`：图片只允许 `data:image/png|jpeg;base64`，限制大小；
    - `tools`、`tool_choice`、`response_format`、`temperature`、`max_tokens`（设上限）。
    - 强制使用服务器端的 model，`stream=false`。
  - 保留 `edit` / `check` 任务（局部编辑仍在用），删除 `plan` 任务。
- 测试：扩展 `frontend/scripts/test-demo-model.mjs`，覆盖以下情况：
  - 无令牌；
  - 令牌过期 / 伪造；
  - 次数或 token 用完；
  - 跨域；
  - 超大请求；
  - 非 data URL 图片；
  - 多余字段被丢弃；
  - 正常流程。

### WP31 浏览器打包
- 浏览器入口 `src/browser.ts`：导出 `streamDiagram`、`MemoryFS`、各类型，以及资源 provider 的安装函数。
- 资源内嵌：
  - `tools/build-browser-assets.ts` 把流水线运行时读取的 `evodesign/agentic_system` 资源（提示词、yaml、json、type_patterns 等）生成一个模块；
  - 完整性用 `parity:runs` / `parity:web` 运行时记录到的资源访问清单校验，缺一个都不行。
- 配置：`ModelConfig` / `AppSettings` 在浏览器下不读 `.env` 和 yaml 文件，由调用方传入，默认值与 backend 一致。
- Web Worker：流水线在 Worker 里运行；渲染请求通过 postMessage 转到主线程的 `pipelineRenderer`；取消通过 AbortSignal 传递。
- 前端依赖接入：
  - 包以 `file:../packages/render-engine` 方式接入；
  - 确认 Vercel 的 `installCommand` / `buildCommand` 能装好它的依赖并完成构建（只改 `vercel.json` 和 package 配置，不部署）。
- 记录包体积（gzip 前后）。Worker 包按需加载，不进首屏。
- 验收：
  - `npm --prefix frontend run build:browser` 通过；
  - bundle 中没有 node 内置模块；
  - 在 headless chromium 中用 cassette 回放 3 个 `web_runs` 用例，事件和结果与 `parity:web` 期望一致。图片输入因渲染器不同，按 WP28 的阈值规则比较。

### WP32 前端接入
- `generateBrowserDiagram` 改为调用 Worker 中的 `streamDiagram`：
  - 事件映射复用完整模式的处理代码：把 `apiDiagramService` 里 SSE 事件 → callbacks 的逻辑抽成共享函数，两种模式共用；
  - 结果按完整模式的方式转成 `DiagramResponse`。
- 删除：
  - `diagramPlan.ts`、`edgeRouting.ts`、`scene.ts` 的 `renderPlan`；
  - `PLAN_PROMPT`，以及只被它们使用的代码。
- 保留：`editBrowserDiagram` 和它依赖的 `scene.ts` 函数。
- 界面：
  - `StageProgress` 的阶段列表与完整模式一致；
  - 模型不支持图片时显示提示；
  - 取消按钮有效。
- 测试：
  - `npm --prefix frontend run lint`、`build:browser`、`test:browser`、`test:editor` 全绿；
  - 新增 e2e：playwright 打开 `dev:browser`，拦截模型请求，用 cassette 应答，跑 3 个用例，校验画布上的元素与期望结果一致（按 WP28 规则）。

### WP33 真实模型冒烟
- 用仓库 `.env` 里配置的真实模型，最多 8 个用例，总调用不超过 150 次。分别跑：
  - Python backend 完整模式（本地起 backend）；
  - 浏览器版（真实 chromium，用户模型模式）。
- 记录：耗时、模型调用次数、是否报错、校验与修复结果；两边的最终图并排放进 `migration/wp33/` 供人工查看。
- 真实模型输出有随机性，不要求两边一致；只要求流程走通、没有浏览器特有的错误。发现的问题当场修复，并记入 `ISSUES.md`。

### WP34 验收
- 由一个没参与实现的 agent 独立复跑全部检查：
  - 第一、二期对照；
  - `--fs memory`；
  - `parity:web`；
  - 渲染像素对照；
  - 前端全部测试和 e2e；
  - bundle 检查；
  - `/api/model` 安全测试；
  - 抽查 WP33 的产物。
- 用中文写 `PHASE3_REPORT.md`，列出遗留问题和严重程度。

## 2. 调试顺序（出现分歧时）
1. `parity:web` 第一处分歧在模型请求上 → 先看第二期 `parity:runs` 同类用例是否一致：一致则问题在 web runtime 拼装的参数；不一致则在流水线本身。
2. 分歧在事件 payload 上 → 对照 `workflow_runtime/events.py` / `event_payloads.py` 的字段顺序和默认值。
3. 只在 `--fs memory` 下出现 → 问题在 `MemoryFS` 的路径语义（相对路径、尾部斜杠、目录列举顺序）。
4. 只在浏览器里出现 → 依次检查资源清单、配置默认值、渲染器、Worker 消息序列化（Map/Set/类实例丢失）。
