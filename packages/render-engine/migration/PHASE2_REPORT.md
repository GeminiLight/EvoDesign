# 第二期独立验收报告（WP25）

> 验收人：WP25（独立验收，没有采信实现者的 notes 和台账，所有数字都是本人从干净状态重跑得到的）
> 日期：2026-11-05（UTC 2026-11-04 17:54 至 18:10）
> 范围：生成 / 校验 / 修复 / 总编排迁移到 TypeScript（LangGraph.js），见 `PHASE2_PLAN.md`

## 1. 结论

**有条件通过（accepted with issues）。**

- 录制回放场景下，TS 流水线与 Python **完全一致**：36 个端到端样例全部相同；大模型请求、节点快照和产物逐项对上，没有用到任何数值容差或图片容差。
- 第一期对照仍然全部通过。
- 没有发现 TS 偷读 fixture 而"假通过"的情况。
- 剩余问题集中在**cassette 覆盖不到的那一层**：TS 通过 `@langchain/openai` 发出的真实 HTTP 请求，以及真实服务商报错时的重试判定。用本地假服务器对比后，发现 2 个中等严重度的偏差（第 4 节 #1、#2）。录制回放的设计本身测不到它们，**接入真实大模型之前必须修复**。
- 验收中补了 5 批 Python 生成的向量（共 5,130 条：修复器/原语 4,968、终止逻辑 50、条件边 100、裁剪 12），覆盖之前 0 向量或从未执行到的关键函数，全部通过。

## 2. 数字（全部为本次重跑结果）

清理命令：`rm -rf reports/functions reports/runs.json reports/stages.json`。之后依次执行下表命令。

| 项目 | 命令 | 结果 |
|---|---|---|
| 类型检查 | `npx tsc --noEmit` | 0 错误（158 个 src 文件，含 `tools/wp25/`） |
| 全量单测 | `npx vitest run` | 4 个文件，**1142/1142** 通过 |
| 第一期函数级 | `npx vitest run test/parity/functions.test.ts test/parity/wp04-converter.test.ts test/parity/integer-ids.test.ts` | **1123/1123** 通过；第一期向量 **16430/16430** |
| 第一期阶段级 | `npm run parity:stages` | **112/112**（串联模式全部阶段一致） |
| 第二期函数向量 | 同上（`functions.test.ts` 含第二期 96 个模块） | 18532 条：通过 **18074**，失败 **0**，跳过 **458**（异步/出图/调模型的函数，改由端到端回放覆盖，见 §3.2） |
| 端到端回放 | `EXCALIDRAW_RENDER_URL=http://127.0.0.1:3001/renderers/excalidraw npm run parity:runs` | **36/36 一致**：大模型调用 158/158，快照 853/853，产物 525/525，容差图片 0，耗时 2 分 24 秒 |
| 台账 | `npm run ledger` | 34504/34962 通过，0 失败，458 跳过 |
| WP25 补充向量 | `npx tsx tools/wp25/run_vectors.ts` 等，见 §3.3 | 生成时全量 5018/5018；存盘的精简集 1256/1256。另有裁剪 12/12、条件边 100/100、异常向量 93 条（见 §3.1） |

所有命令都在 `packages/render-engine` 目录下执行。出图只用了 3001 端口，没有碰 3000 端口。除 §3.4 中发往本机 `127.0.0.1` 假服务器的请求外，没有任何对外网络调用。

## 3. 验证了什么、怎么验证的

### 3.1 对照工具本身的审计

**cassette 比较（`test/harness/cassette.ts`）：严格。**
- 逐字比较的内容：消息角色（type）、文本（逐字符，报告第一个不同字符的位置）、消息顺序和条数、tool_calls、`tool_call_id`、`name`、绑定的工具（经 `convertToOpenAITool` 转换）、调用参数（stop 等）、模型初始化参数，以及 LLMFactory 的 role。
- 数字用 `!==` 精确比较，没有容差。
- 图片：先比 sha256，不同时比尺寸和解码后的 RGBA，最后才看逐通道 ≤1 的容差。本次实际 **0 张**图片用到容差。
- 第一个不一致会保存在 session 上，所以 TS 的重试循环吞掉异常也藏不住。
- **调用方（caller）有时不比较**：TS 通过 JS 调用栈推断 agent 类名。经过 `createAgent` 的异步调用栈会丢帧，此时不比较 caller。158 次调用中有 **13 次**属于这种情况（Router/Unified 路径），见问题 #6。这些调用的 role、模型参数和消息仍然逐字比较。

**归一化规则（`tools/run_normalize.py` / `test/harness/runs.ts`）：没有掩盖实际差异。**
- 替换的内容只有：临时目录 → `<OUT>/<TMP>`、仓库根目录 → `<REPO>`、ISO 时间戳 → `<TIMESTAMP>`、UUID → `<UUID>`，以及 `duration_ms`、`elapsed_seconds` 置 0。
- cassette 请求本身**不做任何归一化**，所以提示词里如果出现路径或时间，会直接报分歧。

**比较方式中可能掩盖差异的两处，本人另做了逐项核对：**
1. **快照和 JSON 产物按结构比较**（`test/harness/compare.ts`）：数值误差 ≤1e-6 可通过，key 顺序不同只记录不判失败，`120` 和 `120.0` 无法区分。
   - 核对方法：`tools/wp25/audit_runs.ts` 重放 36 个样例并统计，853 个快照中 **tolerated = 0，key 顺序不同 = 0**。
   - `tools/wp25/artifact_bytes.py` 把 TS 写出的 431 个 JSON/文本产物，按录制时的规则用 Python 重新序列化（保留 key 顺序和 int/float），再与录制文件逐字节比较：**431/431 相同**。
   - TS 写出的 JSON 格式全部是 `indent=2, ensure_ascii=False`，与 Python 的 `json.dump` 写入点一致。
2. **函数向量里的异常只检查"抛没抛"**（`test/parity/functions.test.ts:86`），不检查异常类型和消息。
   - 核对方法：`tools/wp25/raises.ts` 检查第二期全部 93 条异常向量。**92 条异常类名相同。** 剩下 1 条是 pytest 故意少传参数触发的 Python `TypeError`，属于调用约定差异，不是逻辑差异。
   - 消息不同的只有 1 条，原因是导出器把 Python 消息截断在 300 字符，实际消息相同。

**TS 有没有可能靠读取 fixture 通过：没有。**
- `grep -rn "fixtures|cassette|test/harness|examples/configured-model|run_cases" src/` 只命中 `src/core/llm_factory.ts:37` 的一行注释。
- `runRecordedPipeline` 的第一个参数 `_input` 在函数体内没有被使用（`src/agentic_system/main.ts:1056`）。它只读取 parity 工具写入临时目录的 `dataset.json`，再像生产环境一样走 `parse_arguments → … → process_example`。
- 产物比较的对象是 TS 写进新临时目录的文件。
- 函数向量中按路径读文件的适配器（`test/adapters/…iterative_workflow.ts`）只存在于测试代码里。

### 3.2 覆盖情况

- 第二期 611 个被追踪的函数中，**388 个有向量**，147 个被调用过但没有向量（大多是 `self` 为 agent/workflow 的方法，无法编码），76 个在录制中**从未被调用**。
- 458 条跳过的向量分布在 21 个函数上，原因都是"异步 / 驱动渲染页 / 调用模型"，例如 `iterative_workflow._run_one_iteration`、`main.process_example`、`verification_stage.workflow._node_run_subjective_critic`、`canvas_render.render_canvas`。这些函数的行为由端到端快照覆盖。
- 端到端样例只用了**一种模型配置**：`openai` 兼容接口、`streaming=true`、`max_tokens=16384`、`temperature=1`、`max_retries=0`。thinking、reasoning_effort、nvidia、anthropic 等分支没有被任何录制样例走到。
- 本人重点阅读的高风险代码，以及发现的未覆盖分支：

| 代码 | Python 与 TS 对读结论 | 录制覆盖 | WP25 补充 |
|---|---|---|---|
| `BaseAgent._transport_call` / `_invoke_parsed` / `_invoke_with_history_parsed`（`evodesign/core/base_agent.py:507-700` ↔ `src/core/base_agent.ts:635-880`） | 逐行一致：预算检查、退避、重试计数共享、JSON 修复轮、最后一次宽松解析、空回复回显文本都相同 | 端到端覆盖了 JSON 修复和重采样（`t_funnel_ty__repair`、`t_timeline_ty__repair`、`t_swot_ty__refine`）、流中断续写（`rag_aes__unified_stream`） | 用本地假服务器生成真实服务商异常，比较重试判定，发现 2 处偏差，见 #2 |
| `preprocess_response` 等（`utils/llm_output`） | 一致 | 108 + 120 + 77 条向量 | — |
| LangGraph 条件边（verifier、unified、iterative 三张图） | 节点名、映射表、`set_entry_point → addEdge(START)` 全部对应；`prepared_iteration` 默认 `null`；`recursionLimit` 与 Python 相同 | 走到的分支由快照顺序（scope:graph:node）逐个校验 | `_after_iteration` 的 100 条向量：finalize ×74、run_iteration ×26，覆盖 failed、终止原因已设、converged、达到 max_iterations 四个出口，**100/100** |
| 迭代修复的终止逻辑 `_mark_convergence` | 一致 | 录制中只走到 `resolved` 和 `fixed_point_unresolved`；`stagnant`、`no_edits_resolved`（只有 pytest 向量）、`max_iterations_exhausted` 没有走到 | 50 条 `stagnant` 向量 **50/50**；`max_iterations_exhausted` 由上一行的 `_after_iteration` 向量覆盖 |
| 图片裁剪 `smart_crop`（`render_engine/shared/image_cropper`，**0 条向量**） | TS 用 pngjs 逐位复现 OpenCV 的 imread、BGR2GRAY、Otsu、形态学和 boundingRect | 41 次出图后裁剪，结果由 PNG 像素和 critic 图片 part 间接验证 | 12 个合成样例：excalidraw 阈值边界、全空白、RGBA、灰度、调色板、16 位、底部裁剪超过图片高度（Python `IndexError`）、负 padding、tldraw/其它引擎的 Otsu + 形态学路径。**12/12 像素和消息完全一致** |
| 确定性修复器与编辑原语（`fix_missing_back_refs`、`fix_swimlane_lane_membership`、`fix_group_bbox_escape`、`op_*` 共 12 个函数**从未执行**，原因是 `_FIXERS`/`OPS` 表在追踪器打补丁之前已经绑定） | 一致 | 只通过 `run_all_deterministic_fixers` 的 15 条向量间接覆盖 | 用 36 个录制样例的最终 manifest，做 6 类破坏（删除反向引用、悬空绑定、移出分组框、重叠、低对比度、图层倒序），再由 Python 真实检查器生成 findings。共 4,968 条向量（存盘精简为 1,206 条），**全部通过** |

### 3.3 WP25 新增的工具和数据

新增内容只在 `tools/wp25/` 和 `fixtures/wp25/`（后者已被 gitignore 忽略）。没有修改 Python 代码、harness 或任何产品代码。临时追加到 `fixtures/functions` 的向量，跑完后已逐个文件恢复原状。

| 文件 | 作用 | 运行方式 |
|---|---|---|
| `tools/wp25/run_vectors.ts` | 回放 `fixtures/wp25/vectors/` 下的补充向量。规则和适配器与 `functions.test.ts` 相同，并且不会被 `fixtures:phase2` 覆盖 | `npx tsx tools/wp25/run_vectors.ts` |
| `tools/wp25/gen_fixers.py`、`gen_loop.py` | 生成上述修复器、原语和终止逻辑向量（Python 真值） | `PYTHONPATH=<repo> .venv/bin/python tools/wp25/gen_fixers.py <输出目录>` |
| `tools/wp25/gen_crop.py` + `crop.ts` | 裁剪向量与对照 | `npx tsx tools/wp25/crop.ts` |
| `tools/wp25/after_iteration.ts` | 条件边 `_after_iteration` 对照 | `npx tsx tools/wp25/after_iteration.ts` |
| `tools/wp25/raises.ts` | 异常类名和消息对照 | `npx tsx tools/wp25/raises.ts` |
| `tools/wp25/audit_runs.ts` + `artifact_bytes.py` | 快照容差和 key 顺序统计；产物逐字节核对 | 先跑前者，再跑 `python artifact_bytes.py <dir>` |
| `tools/wp25/fake_llm_server.py` + `provider_errors.{py,ts}` + `provider_requests.{py,ts}` + `provider_requests_diff.py` | 本机假 OpenAI 兼容服务器：返回各类错误、记录请求体，用来比较两端真实发出的 HTTP 请求和异常判定 | `python fake_llm_server.py <port> <log>`，然后分别运行 py 和 ts 脚本 |
| `tools/wp25/design_memory_default.ts` | 不加 `--no-design-memory` 时的默认行为 | `npx tsx tools/wp25/design_memory_default.ts` |

### 3.4 不在本期范围的功能是否可注入、默认是否关闭

| 功能 | Python 默认 | TS 实现 | 结论 |
|---|---|---|---|
| user_memory | `enable_user_memory=False` | `src/agentic_system/workflow.ts:110` 的 `user_memory_hooks.UserPreferenceMemorySystem` 默认 `null`；开启但没有注入时，等同于 Python ImportError 的处理：警告并关闭 | 可注入，默认关闭，干净 |
| design_memory | **`enable_design_memory=True`（默认开启）** | `design_memory_hooks`（`workflow.ts:92`）默认 `null` | 本机没有向量库，此时两端都在同一处检查后降级，错误文本相同：`design memory vector store not found: …/data/knowledge`。验证方法：去掉 `--no-design-memory` 重放 `flow_x1__multi`，4 次大模型请求与 cassette 完全一致。**向量库存在时**，TS 没有注入 hook 会记录 `dependencies unavailable` 并降级，而 Python 会真正检索并改写提示词。见 #9 |
| knowledge_evolution | — | `canvas_environment/capabilities.ts` 只保留能力判定 | 编排代码里没有调用，干净 |
| tldraw | — | `validate_tldraw_manifest`、`normalize/audit/repair` 抛 `NotImplementedError`（`canvas_environment/_render_engine_adapter.ts:130`、`validation.ts:130/166/190`） | 明确失败，不会静默产出错误结果 |

## 4. 剩余问题

严重度定义：**高**：录制场景下就会出错；**中**：接入真实模型或生产部署后会与 Python 行为不同；**低**：工具链或覆盖面的缺口。定位格式为：样例 → 调用/节点/产物 → 模块 → 函数 → 向量或命令。

### #1【中】真实 HTTP 请求与 Python 不同（cassette 测不到）
- **现象**：同一组 LLMFactory 参数（`fixtures/wp25/provider_configs.json` 中的 9 种配置），发往本机假服务器后，两端的请求体和请求头有以下差异（请求消息本身，包括中文和图片 part，完全相同）：
  - Python 发送 `max_completion_tokens`，TS 发送 `max_tokens`。默认配置 `models.yaml` 的 `max_tokens: 16384` 就会触发。
  - TS 流式请求多带了 `stream_options: {"include_usage": true}`。
  - Python 的 `User-Agent: EvoDesign/diagnostic` 在 TS 里被 langchainjs 换成 `langchainjs-openai/1.0.0 (...)`。Python 源码注释写明"有些网关会拒绝 SDK 默认的 User-Agent"。
  - `reasoning_effort`：模型名不被 langchainjs 认作"推理模型"时，TS 会**直接丢掉**这个参数。
- **定位**：录制样例无法定位（cassette 截在 `init_chat_model` 这一层）→ `src/core/llm_factory.ts:62 _init_chat_model_fields`（`case 'reasoning_effort'` 在 :88，`case 'default_headers'` 在 :81）↔ `evodesign/core/llm_factory.py:55 LLMFactory.create`（:124 User-Agent）→ 复现：`python tools/wp25/fake_llm_server.py 18766 /tmp/x.jsonl`，然后运行 `tools/wp25/provider_requests.py` 和 `provider_requests.ts`，最后用 `provider_requests_diff.py fixtures/wp25/echo_py.jsonl fixtures/wp25/echo_ts.jsonl` 比较。
- **建议**：TS 端显式设置 `maxCompletionTokens`、`streamUsage:false`；通过 `modelKwargs` 写入 `reasoning_effort`；用自定义 `fetch` 覆盖 `User-Agent`。改完后把上面的请求体比较做成自动测试。

### #2【中】真实服务商异常的重试判定有两处与 Python 不同
- **现象**（本机假服务器，11 种场景，9 种相同）：
  - **请求超时**：Python 中 langchain-openai 抛出的 `OpenAITimeoutError` 属于 `openai.APIError`，消息里不含任何"可重试"标记，因此 Python **不重试**。TS 中 `@langchain/openai` 把它包装成 `name='TimeoutError'` 的普通 Error，命中 `_RETRYABLE_EXCEPTIONS`，因此 TS **会重试**。默认 timeout 是 1200 秒，单次调用截止是 1800 秒，两边的总耗时会明显不同。
  - **流里没有任何 chunk**（只有 `[DONE]`）：Python 抛 `ValueError("No generations found in stream.")`，判定为可重试。TS 在 `@langchain/core` 里抛 `TypeError: Cannot read properties of undefined (reading 'message')`，判定为不可重试，直接失败。
  - 429 限流和额度耗尽、401/400/404/500/503、坏 SSE、连接拒绝：两端相同。
- **定位**：录制样例无法定位（cassette 只录制了 `ConnectionError/TimeoutError/ValueError` 这类合成异常）→ `src/core/base_agent.ts:211 _is_retryable_exception`、`:148 _is_stream_transport_error`、`:635 _call_model_once` ↔ `evodesign/core/base_agent.py:178`、`:109`、`:490` → 复现：`python tools/wp25/fake_llm_server.py 18765 /dev/null`，然后运行 `tools/wp25/provider_errors.py`（输出 `fixtures/wp25/provider_errors_py.json`）和 `npx tsx tools/wp25/provider_errors.ts`。
- **备注**：Python"超时不重试"很可能本身就是 Python 的 bug，但 Python 是真值。修 TS 还是修 Python，需要项目负责人决定；改完后两端都要重跑这个对照。

### #3【中，维护风险】int/float 标记只覆盖录制走到的路径
- WP24 用 `src/py/float_marks.ts` 的旁路标记来模拟 Python 的 `120.0`（ISSUES.md WP24-1）。录制样例和第一期 112 个阶段样例走到的路径已经逐一核对。
- 没走到的分支如果写入整数值的浮点数，JSON 文本会变成 `120`。这会影响提示词文本，以及 `analysis_manifest_fingerprint` 之类的哈希。
- 这个问题对数值对照不可见：§3.3 的修复器向量只比较数值，没有验证标记。
- **定位**：`src/py/float_marks.ts` → 写入点见 `migration/notes/ISSUES.md` WP24-1 → 检查方法：WP24 的 `floatcheck` 思路（scratchpad 脚本，未入库）。
- **建议**：把"浮点路径集合"比较并入 `parity:runs`；以后修改 manifest 的代码一律使用 `pyDeepcopy`、`assignF` 等工具。

### #4【低】真实流式路径和其它服务商没有任何回放覆盖
- 录制样例的回复是一次性返回的（`_generate`），而 `transport_journal.NativeStreamJournal.on_llm_new_token` 在真实流式下会被多次调用。这条路径只有"流中断"一种合成情形（`rag_aes__unified_stream` 的 LLM call 1）。
- anthropic 和 nvidia 分支、thinking、reasoning_effort 都没有端到端覆盖。
- 真实调用次数为 0：计划允许 ≤15 个真实样例，但 WP12 没有使用。
- **定位**：`fixtures/runs/*/cassette.jsonl`（只有 1 种 `model_params`）→ `src/generation_stage/unified/transport_journal.ts`。
- **建议**：上线前用真实模型补录 3–5 个样例（multiagent、unified 流式、refine 各一个）。

### #5【低】`parity:runs` 对 JSON 产物按结构比较
- key 顺序、`120` 与 `120.0`、缩进都不会被发现。本次另行核对 431/431 逐字节等价，**目前没有实际问题**，但工具本身不能防止以后出现回退。
- **定位**：`tools/parity-runs.ts:210`（`entry.kind === 'json'` 分支）→ 核对命令：`tools/wp25/audit_runs.ts` + `tools/wp25/artifact_bytes.py`。
- **建议**：把 `artifact_bytes.py` 的规则（重新序列化后逐字节比较）并入 `compareArtifacts`。

### #6【低】13/158 次大模型调用没有比较调用方
- **定位**：`reports/runs.json` → `runs[*].llm.unverifiedCallers`（`ecommerce_aes__unified`、`flow_h1__router`、`flow_x2__unified_router`、`iot_aes__unified_refine`、`quickstart_service__router`、`rag_aes__unified_stream`、`t_funnel_ty__repair`、`t_mindmap_ty__router`、`t_orgchart_ty__unified_repair`）→ `test/harness/cassette.ts:140 stackCallerResolver`。
- 这些调用的 role、参数和消息都已逐字比较，调用方弄错的可能性很低。
- **建议**：在 BaseAgent 调用前用 AsyncLocalStorage 写入类名，替代从调用栈推断。

### #7【低】函数向量的异常只比较"抛没抛"
- 已用 `tools/wp25/raises.ts` 核对：92/93 类名相同，剩下 1 条是调用约定差异，见 §3.1。
- **定位**：`test/parity/functions.test.ts:86`。
- **建议**：把类名比较并入 harness。

### #8【低】仍未覆盖的第二期代码
以下代码没有向量，录制也没有走到：
- `core.base_agent` 的截止时间路径（`LLMBudgetExceeded`）
- `main.learn_from_user_edit`
- `quality_policy.verified_learning_gain`
- `refinement_stage.agent.llm_agent.refine_with_llm`
- `GeneratorWorkflow.run`
- `canvas_environment.editing.apply_operations` / `assert_preserves_locks`
- `CanvasEnvironment.*`
- `styling.colorful` 调色板目录加载（`_load_catalog`、`_parse_palette_markdown`）
- `skill_loader._locate_skill_dir`
- `canvas_render` 的 tldraw 分支

完整清单（76 个从未调用、147 个调用过但没有向量）的生成方法：用 `fixtures/functions/_signatures.json` 减去 `_summary.json` 中 `vectors>0` 的项，按 `migration/modules.json` 中 WP12–WP23 的模块过滤。

### #9【信息】design memory 默认开启，生产环境需要注入 hook
- Python 默认 `enable_design_memory=True`。TS 在没有注入 `design_memory_hooks` 时会降级，并在 `result.design_memory_errors` 里记录原因。
- 只要生产环境配置了向量库，TS 就必须注入实现，否则提示词会比 Python 少一段 `=== RETRIEVED DESIGN KNOWLEDGE ===`。
- **定位**：`src/agentic_system/workflow.ts:92`、`:131 _load_design_memory_retriever` → 复现：`npx tsx tools/wp25/design_memory_default.ts`。

## 5. 上线 Vercel 需要做什么（下一步）

1. **真实大模型放进 Vercel Function**
   - 运行时必须用 **Node.js**，不能用 Edge。原因是代码里用到 `node:async_hooks`（`_CALL_BUDGET`）、`node:fs`、`node:crypto` 和 playwright，相关文件都标了 `// server-only`。
   - 先修 #1 和 #2，然后用真实模型补录 3–5 个样例（#4）。API Key 放在 Vercel 环境变量里，不要放 `.env`。`LLMFactory` 现在通过 `ensure_env_loaded()` 读仓库根目录的 `.env`，部署时应改为只读 `process.env`。
   - **时长**：Python 默认单次请求 timeout 1200 秒、单次调用截止 1800 秒，一次多智能体加迭代修复的运行包含 3–9 次大模型调用和多次出图。这远远超过一次函数调用通常允许的时长（具体上限取决于套餐，以 Vercel 文档为准）。需要把流水线拆成多个可以续跑的步骤：用 LangGraph checkpointer 加队列或后台任务，按阶段（生成 → 校验 → 每一轮修复）分别调用，同时下调 `EVO_LLM_CALL_DEADLINE_SECONDS`。
   - 配置文件（`evodesign/config/defaults/*.yaml`）、图标和资源（`py/assets.ts`）目前都从仓库路径读取，部署时要打包进函数，或改成构建期导入。
2. **替换渲染和截图**
   - 现在的做法是：用 playwright 启动本机 Chromium，打开 `http://127.0.0.1:3001/renderers/excalidraw`，再截图，然后用 pngjs 裁剪。
   - Vercel 上可以选的方案：
     - (a) 前端在用户浏览器里用 Excalidraw `exportToBlob` 出图并上传，critic 拿上传的 PNG。好处是不需要服务端浏览器；缺点是必须保证导出参数与现在的渲染页完全一致，并用现有的 PNG 像素对照验证。
     - (b) 在函数里运行无头 Chromium（例如 playwright-core 配合精简版 Chromium），需要注意包体积和冷启动。
     - (c) 使用外部无头浏览器服务。注意截图数据可能包含用户内容，需要做隐私评估。
   - 无论选哪种，都要保证"同一个 manifest 得到同一份像素"，可以用 `parity:runs` 的 PNG 比较规则来验收。
   - 函数里只有 `/tmp` 可写，而且是临时的，所以产物（manifest、PNG、报告）要写入 Blob 或对象存储。现在 `outputDir` 和 `EXPERIMENTS_DIR` 的用法需要改造。
3. **记忆存储**
   - design_memory（Python 用 chromadb 和 sentence-transformers）：换成托管向量库，embedding 改用 API，通过 `design_memory_hooks` 注入。注入后必须跑一次"开启状态"的对照，确保检索结果和提示词片段与 Python 一致。
   - user_memory：换成数据库或 KV，通过 `user_memory_hooks` 注入。
   - knowledge_evolution 是离线任务，继续留在 Python 或单独迁移。
4. **持续保持一致**：建议把 `parity:runs`、§3.3 的补充向量、#1 的请求体对照和 #2 的异常对照加入 CI。Python 侧每次修改后，都要重新执行 `record:runs` 和 `fixtures:phase2`。

## 6. 相关文件

- 本报告：`packages/render-engine/migration/PHASE2_REPORT.md`
- 本次重跑生成：`reports/runs.json`、`reports/stages.json`、`reports/functions/*.json`、`migration/LEDGER.md`
- WP25 工具：`packages/render-engine/tools/wp25/`；WP25 数据：`packages/render-engine/fixtures/wp25/`（已被 gitignore 忽略，约 76 MB，可用生成脚本重新生成）
