# 第二期迁移计划：生成 / 校验 / 修复 / 编排 → TypeScript（LangGraph.js）

本文件是第二期每个子 agent 的**约束性工作规则**。第一期的 `MIGRATION_PLAN.md` 仍然有效：§2 命名规则、§4 翻译规则、§6 流程与完成标准、§7 排查顺序全部沿用。本文件只写第二期新增或不同的部分；两者冲突时以本文件为准。

## 1. 范围

| WP | 内容（Python 路径，均相对 `evodesign/`） | 依赖 |
|---|---|---|
| WP12 | 对照基础设施：大模型录制回放（cassette）、端到端录制、第二期函数向量、TS 回放工具、依赖安装、`modules.json` 第二期条目。**不写产品代码** | — |
| WP13 | 基础层：`config/{settings,model_loader}`、`utils/{llm_output,path_manager,env_loader,io_utils}`、`core/{llm_factory,base_agent,experiment}`、`agentic_system/{config,quality_policy}`、`canvas_runtime`、`agentic_system/common/{base_workflow,workflow_state_base,task_prompts,skill_loader,domain_knowledge_loader,self_consistency}` | WP12 |
| WP14 | 出图与画布环境：`agentic_system/render_engine/{canvas_render,service}`、`render_engine/shared/{image_cropper,png_validation}`、`canvas_environment/*` | WP13 |
| WP15 | 生成·结构：`generation_stage/structure/*`、`generation_stage/router/*`、`generation_stage/compact_decisions` | WP13 |
| WP16 | 生成·样式：`generation_stage/styling/*`（含 `contracts/`、`colorful`、`icon_colors`） | WP13 |
| WP17 | 生成·布局与多智能体编排：`generation_stage/layout/*`（`element_shape_estimator` 第一期已完成）、`generation_stage/workflow` | WP15, WP16 |
| WP18 | 生成·一体化（unified/native）：`generation_stage/unified/*` | WP17 |
| WP19 | 校验·确定性检查：`verification_stage/checks/*`、`verification_stage/reports/*` | WP13 |
| WP20 | 校验·评审与流程：`verification_stage/{critic/*,workflow,state,__main__}` | WP14, WP19 |
| WP21 | 修复·确定性修复器：`refinement_stage/fixers/*` | WP13, WP19 |
| WP22 | 修复·大模型修复与流程：`refinement_stage/{agent/*,reports/*,state,__main__}` | WP20, WP21 |
| WP23 | 总编排：`agentic_system/{workflow,iterative_workflow,main,__main__}` | 全部 |
| WP24 | 集成：端到端回放对照全部通过 | WP23 |
| WP25 | 独立验收，写 `migration/PHASE2_REPORT.md` | WP24 |

不在本期：`user_memory/`、`design_memory/`、`knowledge_evolution/`、`render_engine/tldraw/`、`scripts/`。编排代码里对它们的调用保留为**可注入接口**，默认关闭（与 Python 在这些功能关闭时的行为一致），并在 notes 里列出。

## 2. 对规则的调整

1. **TS 路径**：`evodesign/agentic_system/X/Y.py` → `src/X/Y.ts`（与第一期一致，去掉 `agentic_system/`）；`evodesign/{config,utils,core,canvas_environment}/Y.py` → `src/{config,utils,core,canvas_environment}/Y.ts`；`agentic_system/{workflow,iterative_workflow,main,config,quality_policy}.py` → `src/agentic_system/*.ts`；`evodesign/canvas_runtime.py` → `src/canvas_runtime.ts`。以 `modules.json` 为准。
2. **依赖**：第二期允许使用 WP12 安装并锁定版本的依赖：`@langchain/core`、`@langchain/langgraph`、`langchain`（`createAgent`、`initChatModel`）、`@langchain/openai`、`playwright`、`pngjs`。其他 WP 不得再加依赖。
3. **node: 模块**：只允许在"只跑在服务端"的模块里使用（文件读写、路径、出图、环境变量），并在文件头注明 `// server-only`。纯计算模块仍然不得使用。
4. **LangChain 对应关系**：`langgraph.graph.StateGraph` → `@langchain/langgraph` 的 `StateGraph`（节点名、边、条件边与 Python 完全一致）；`langchain.agents.create_agent` → `langchain` 的 `createAgent`；`init_chat_model` → `initChatModel`；`SystemMessage/HumanMessage/AIMessage` → `@langchain/core/messages` 同名类。消息内容（含多模态 parts）必须与 Python 发出的**逐字一致**——这由 cassette 对照强制检查。
5. **pydantic 模型**：翻译成 TS 类或接口 + 显式校验函数，校验错误的触发条件与 Python 相同（错误文本若会进入提示词或产物，也必须相同）。
6. **异步**：LangChain.js 是异步的。Python 的同步调用链在 TS 中变成 `async`/`await`，但调用顺序必须与 Python 相同（不得把串行改成并行，否则 cassette 顺序会乱）。

## 3. 一致性如何保证

第一期的函数级对照照旧，另外新增**端到端回放对照**：

- **大模型录制（cassette）**：Python 侧用一个替身聊天模型代替 `init_chat_model` 的返回值。每次模型调用记录：调用序号、调用方（agent 类名/角色）、**完整请求**（消息列表：角色、文本、图片 part 的 sha256、绑定的工具、模型参数）和**回复**。
- **回复从哪来**：优先由 `examples/configured-model/<case>/` 下已有的各阶段产物合成（结构、样式、布局、评审报告、修复报告），按对应 agent 期望的输出格式拼成回复文本；另外故意加入少量非法 JSON 回复，覆盖 JSON 修复重试路径。合成不了的路径（例如评审/修复的特定分支）允许用本机已配置的模型**真实调用**，总数不超过 15 个样例，回复全部录入 cassette；除此之外不得向任何外部服务发送数据。
- **端到端录制**：对每个录制样例，用 cassette 跑完整的 Python 流水线（多智能体模式、一体化模式、迭代校验修复各有覆盖；设计记忆/用户记忆关闭），出图走 3001 端口的渲染服务。记录：输入、cassette、每个顶层 LangGraph 节点后的状态快照、流水线写出的全部产物文件（时间戳、临时路径等不确定字段按固定规则归一化，规则写在 `tools/` 里并在 notes 中列出）。**同一样例录两次必须完全相同**。
- **TS 回放**：`test/harness/cassette.ts` 提供回放聊天模型（`@langchain/core` 的 `BaseChatModel` 子类）：第 N 次调用时，把 TS 发出的请求与 cassette 第 N 条比较，不同就报出 JSON 路径并失败；相同就返回录制的回复。`npm run parity:runs` 跑全部录制样例，输出 `reports/runs.json`：每个样例第一个分歧点（第几次大模型调用的哪个字段 / 哪个节点快照 / 哪个产物文件的哪个路径）。
- **出图**：TS 用 Node 版 playwright 打开同一个渲染页面。若 PNG 字节与 Python 不同，比较解码后的像素；cassette 中图片 part 的比较方式由 WP12 确定并写入本节附录。

## 4. 完成标准（在 MIGRATION_PLAN.md §6 之上增加）

- 本 WP 模块的函数向量失败数 = 0。
- 从 WP17 起，凡是本 WP 负责的节点出现在端到端回放里，`npm run parity:runs` 不得在本 WP 的代码里出现第一个分歧（用 `--case`、`--until` 定位）。
- WP24 完成时：全部录制样例端到端回放 100% 一致，第一期对照（16430 向量、112 阶段样例）保持全部通过。

## 5. 出问题时怎么定位

1. `npm run parity:runs`：看每个样例的**第一个分歧点**。
   - 分歧在"第 N 次大模型请求"：提示词拼装不同。按请求里的调用方找到对应 agent，比较 TS 与 Python 的模板渲染、消息顺序、图片 part。
   - 分歧在"节点快照"：该节点的逻辑不同。用节点输入（上一个快照）单独跑该节点。
   - 分歧在"产物文件"：写文件或归一化的问题。
2. 进入模块函数向量：`PARITY_MODULE=<模块> npm run parity`，按 JSON 路径定位到函数。
3. 用 `fixtures/functions/<模块>/<函数>.jsonl` 第 N 行在 Python 侧复现，逐行对比。
4. 跨 WP 修复登记在 `migration/notes/ISSUES.md`。

## 附录：WP12 填写

### A. 录制样例（36 个，`fixtures/runs/<run>/`）

全部样例都**录两次、归一化后逐字节相同**（36/36），Python 回放模式（`record_runs.py --replay`）也 36/36 相同。cassette 里共有 158 次大模型调用，全部是合成回复，**真实调用 0 次**（第 3 节允许最多 15 个样例真实调用，这里没有用到）。

| 样例 | 模式 | diagram_type | 修复 | LLM 调用 | 快照 | 产物 | 说明 |
|---|---|---|---|---|---|---|---|
| `big_en_aes__refine` | multiagent | architecture | 修复 ×3 | 5 | 27 | 20 | architecture; refinement loop with recorded LLM edits |
| `concept_ml__multi` | multiagent | concept_map | — | 4 | 24 | 13 | concept_map (hand-authored case in tools/run_cases) |
| `cy_flywheel_ty2__multi` | multiagent | cycle | — | 4 | 24 | 13 | cycle |
| `dg_pkgs_ty1__noverify` | multiagent | dependency_graph | — | 3 | 20 | 11 | dependency_graph, --no-verifier |
| `dp_k8s_ty1__multi` | multiagent | deployment | — | 4 | 24 | 13 | deployment |
| `ecommerce_aes__unified` | oneshot | architecture | — | 2 | 12 | 12 | architecture, native scene |
| `flow_h1__router` | multiagent + router | （router 判定） | — | 5 | 24 | 13 | flowchart through RouterAgent |
| `flow_leave_aes__compact` | multiagent | flowchart | — | 4 | 24 | 13 | flowchart with compact layout tuples (expand_layout_output) |
| `flow_x1__multi` | multiagent | flowchart | — | 4 | 24 | 13 | flowchart, explicit diagram_type, verifier+critic |
| `flow_x2__unified_router` | oneshot + router | （router 判定） | — | 3 | 12 | 12 | flowchart, router + native scene |
| `hcai_demo__refine` | multiagent | flowchart | 修复 ×2 | 5 | 27 | 19 | flowchart; critic 6.5 → refinement, report LLM edits |
| `iot_aes__unified_refine` | oneshot | architecture | 修复 ×2 | 3 | 15 | 18 | native scene + refinement loop |
| `kb_sprint_ty1__multi` | multiagent | kanban | — | 4 | 24 | 13 | kanban |
| `ls_web_ty2__multi` | multiagent | layer_stack | — | 4 | 24 | 13 | layer_stack |
| `ne_saas_ty1__refine` | multiagent | nested | 修复 ×1 | 6 | 32 | 20 | nested; one iteration |
| `paper_full_f2__multi` | multiagent | architecture | — | 4 | 24 | 13 | architecture |
| `paper_method_x2__refine` | multiagent | architecture | 修复 ×2 | 6 | 32 | 20 | architecture; refinement + final verification |
| `plain_ecommerce__icons` | multiagent | architecture | — | 4 | 24 | 13 | architecture with groups, icons on |
| `quickstart_service__router` | multiagent + router | （router 判定） | — | 5 | 24 | 13 | architecture with groups, router |
| `rag_aes__unified_stream` | oneshot | architecture | — | 3 | 12 | 15 | native stream interrupted → continuation suffix request |
| `sm_course_ty1__nocritic` | multiagent | story_map | — | 3 | 24 | 13 | story_map, --no-critic |
| `t_class_tz__refine_forced` | multiagent | class_diagram | 修复 ×2 | 6 | 32 | 20 | class_diagram; low critic score forces refinement, candidate re-verified |
| `t_er_ty__multi` | multiagent | er_diagram | — | 4 | 24 | 13 | er_diagram |
| `t_er_tz__refine_regress` | multiagent | er_diagram | 修复 ×2 | 6 | 32 | 20 | er_diagram; candidate scores lower → refined candidate rejected |
| `t_fishbone_ty__multi` | multiagent | fishbone | — | 4 | 24 | 13 | fishbone |
| `t_funnel_ty__repair` | multiagent + router | （router 判定） | — | 9 | 24 | 13 | funnel; malformed router/structure/layout/critic answers exercise JSON repair and resampling |
| `t_matrix_ty__multi` | multiagent | matrix | — | 4 | 24 | 13 | matrix |
| `t_mindmap_ty__router` | multiagent + router | （router 判定） | — | 5 | 24 | 13 | mindmap via router |
| `t_orgchart_ty__multi` | multiagent | orgchart | — | 4 | 24 | 13 | orgchart |
| `t_orgchart_ty__unified_repair` | oneshot | orgchart | — | 3 | 13 | 13 | native scene fails sidecar validation once → repair turn |
| `t_sequence_tz__multi` | multiagent | sequence_diagram | — | 3 | 24 | 13 | sequence_diagram |
| `t_state_tz__multi` | multiagent | state_diagram | — | 4 | 24 | 13 | state_diagram |
| `t_state_tz__refine_multi` | multiagent | state_diagram | 修复 ×3 | 5 | 27 | 19 | state_diagram; scripted LLM edits: iteration 1 regresses objectively → rolled back, stops at fixed point |
| `t_swimlane_ty__multi` | multiagent | swimlane | — | 4 | 24 | 13 | swimlane |
| `t_swot_ty__refine` | multiagent | swot | 修复 ×2 | 7 | 32 | 20 | swot; refiner resample after non-JSON, schema-drifted edit rejected |
| `t_timeline_ty__repair` | multiagent | timeline | — | 5 | 24 | 13 | timeline; empty styling answer → repair turn with the empty-response echo |

覆盖情况：
- 多智能体（Structure → Styling → Layout）：31 个；一体化（oneshot/native）：5 个；走 Router：5 个（`flow_h1`、`quickstart_service`、`t_mindmap_ty`、`t_funnel_ty`、`flow_x2`，最后一个是 oneshot）。
- 校验 + 评审：34 个（`dg_pkgs_ty1__noverify` 关闭校验，`sm_course_ty1__nocritic` 关闭评审）。迭代校验修复：9 个，覆盖采纳候选（resolved）、fixed point、回滚、复检后拒绝候选（`t_er_tz__refine_regress`）、一体化场景上的修复，以及质量门失败（`big_en_aes__refine` → `VerificationQualityError`）。
- 图表类型 22 种：architecture、flowchart、concept_map（手写样例 `tools/run_cases/concept_ml`）、er_diagram、mindmap、orgchart、sequence_diagram、state_diagram、swimlane、matrix、fishbone、cycle、layer_stack、deployment、kanban、story_map、dependency_graph、funnel、timeline、swot、class_diagram、nested。
- 注入的故障（JSON 修复/重采样/续写）：trailing_comma、fenced_prose、truncated、not_json、empty、invalid_scene、stream_interrupted + continuation、edit_schema_drift，另有脚本化的修复编辑。逐项见 `notes/WP12.md`。
- 设计记忆、用户记忆一律关闭（`--no-design-memory`，不加用户记忆参数）；出图走 `http://127.0.0.1:3001/renderers/excalidraw`。

每个样例目录里有：`input.json`（spec、数据集条目、CLI 参数、环境变量）、`cassette.jsonl`、`images/`（发给模型的图片，按 sha256 命名）、`snapshots.jsonl`（每个顶层阶段和每个 LangGraph 节点之后的快照）、`artifacts/`（流水线写出的全部文件，已归一化）+ `artifacts.json`（索引）、`result.json`（`process_example` 的返回值）。

运行方式与生产相同：`main.parse_arguments → build_config → validate_config → load_dataset → determine_items → initialize_model / initialize_router_model → process_example → Text2DiagramWorkflow.run`。只替换两处：模型换成 cassette；输出目录换成临时目录（不写进 `examples/`）。

### B. 归一化规则（`tools/run_normalize.py`，TS 版在 `test/harness/runs.ts`）

对所有字符串（JSON 值、文本产物）按顺序处理：
1. 本次运行的临时目录 → `<OUT>`（包括它的 realpath）；
2. 仓库根目录 → `<REPO>`；
3. 系统临时目录（`tempfile.gettempdir()`、`/tmp` 及其 realpath）→ `<TMP>`；前缀为 `evodesign_`、`evodesign-render-`、`tmp` 的 8 位随机后缀改成 `XXXXXXXX`；
4. ISO-8601 时间戳 → `<TIMESTAMP>`；
5. UUID → `<UUID>`。

按 JSON 键处理：`duration_ms`、`elapsed_seconds` 的数值改为 0。

PNG 不做改写：先比 sha256，不同时再比解码后的 RGBA（尺寸加像素 sha256）。录制环境固定：`LLM_*` 用不含机密的占位值，`.env` 里的变量全部显式置空，`PYTHONHASHSEED=0`，`api_key` 记为 `<redacted>`。

### C. 图片 part 的比较方式

cassette 中的图片记为 `{"__image__": {mime, sha256, bytes, width, height, rgba_sha256, file}}`，原图保存在 `images/<sha256>.png`。TS 判定规则（`test/harness/cassette.ts compareImages`）：
1. mime 必须相同；
2. 字节 sha256 相同 → 一致；
3. 否则尺寸必须相同；解码后 RGBA 完全相同 → 一致（允许 PIL 与 pngjs/Chromium 的 PNG 编码不同）；
4. 否则逐通道比较，最大差值 ≤ `IMAGE_CHANNEL_TOLERANCE`（默认 1，可用环境变量 `PARITY_IMAGE_TOLERANCE` 调整）→ 算作一致，但计入 `toleratedImages`；超过就报分歧（报告最大差值和不同通道数）。

`detail` 等其他字段逐字比较。已验证 pngjs 解码出的 RGBA 与 PIL `convert("RGBA")` 的 sha256 相同。出图产物 PNG 的规则同上，但不设容差。

### D. 依赖版本（`package.json` 精确锁定）

`@langchain/core 1.2.20`、`@langchain/langgraph 1.5.1`、`langchain 1.5.18`、`@langchain/openai 1.6.3`、`playwright 1.58.2`、`pngjs 7.0.0`、`@types/pngjs 6.0.5`（均发布于 2026-10-21 之前）。

Python 出图实际调用的是 `tool_services/scripts/render-excalidraw.ts`，用的是 Node 版 playwright 1.58.2 和 chromium-headless-shell r1208（Chrome 145.0.7632.6），venv 里没有装 Python 版 playwright。TS 锁定同一个 playwright 版本，所以用的是同一个浏览器构建。Python 侧版本：langchain 1.4.7、langchain-core 1.7.3、langgraph 1.2.19、langchain-openai 1.7.3、pydantic 2.14.2。

### E. 命令

| 命令 | 作用 |
|---|---|
| `npm run record:runs [-- --run <子串>] [--jobs N]` | 录制（每个样例录两次并比较）→ `fixtures/runs/`，索引在 `_index.json` |
| `npm run record:runs -- --replay` | Python 从 cassette 回放并断言输出相同 → `_replay.json` |
| `npm run record:runs -- --list` | 列出样例 |
| `npm run fixtures:phase2` | 第二期函数向量：带追踪回放全部样例（必须与录制相同）+ pytest（7 个测试目录，必须全部通过）。只重写第二期模块的目录，`_summary`/`_signatures` 合并 |
| `npm run parity:runs [-- --case X]... [--until <node>]` | TS 端到端回放 → `reports/runs.json`，报告每个样例的第一个分歧点（llm / snapshot / artifact / result / error） |
| `PARITY_MODULE=<模块> npm run parity` | 函数向量对照（第一期、第二期通用） |
| `npm run ledger` | 台账（新增"End-to-end runs (phase 2)"一节） |
| `PYTHONPATH=. .venv/bin/python packages/render-engine/tools/run_cases/build_cases.py` | 重新生成手写样例 |

TS 入口约定（WP23 实现）：`src/agentic_system/main.ts` 导出 `runRecordedPipeline(input, {chatModelFactory, outputDir, datasetPath, argv, env, rendererUrl})`，返回 `process_example` 的结果。`chatModelFactory(params, role)` 接收 Python `init_chat_model` 的参数名。快照由 `test/harness/runs.ts instrumentSnapshots()` 自动采集（给 LangGraph.js 的 `StateGraph.addNode` 和 `Text2DiagramWorkflow` 的 7 个阶段方法打补丁）。详见 `tools/parity-runs.ts` 文件头。

### F. 第二期函数向量

18532 条向量，来自 36 个样例回放（16858 条）和 pytest（1674 条，805 个测试）。第二期 96 个模块里有 70 个有向量；611 个被追踪的函数/方法中 388 个有向量。没有向量的 26 个模块基本是常量/提示词模块、只有类方法而 `self` 是 agent/workflow（无法编码）的模块、或者录制中没有执行到的模块（`core.llm_factory`、`common.{base_workflow,task_prompts,skill_loader,self_consistency}`、`render_engine.shared.image_cropper`、`canvas_environment.{constants,editing,environment}`、`structure.{prompts,workflow}`、`router.agent`、`styling.{contracts.base,contracts.excalidraw,contracts.tldraw,state,styling_agent,workflow}`、`layout.{prompts,state,workflow}`、`unified.{generator,state,workflow}`、`critic.comparison`、`agentic_system.__main__`），这些模块靠端到端回放覆盖。新增编码：`__message__`、`__path__`、`__enum__`。
