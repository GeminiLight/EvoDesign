# 跨工作包问题登记

## WP17-1：解码模型 JSON 时整数值浮点（`80.0`）丢失类型，重新序列化时与 Python 不一致

- **登记者**：WP17。**涉及文件**：`src/py/json_decoder.ts`（WP13 新增的 CPython 解码器）。
- **现象**：模型回复的 JSON 里有 `"y": 80.0` 这类整数值浮点。Python `json.loads` 得到 `float`，Layout 阶段把合并后的布局用 `json.dumps` 写进 `conversation_history` 时仍是 `80.0`；TS 解码成 number，写出的是 `80`。布局节点快照的 `conversation_history[6].content` 因此不同。
- **复现**：`flow_x1__multi`、`hcai_demo__refine`、`flow_h1__router`、`flow_leave_aes__compact` 的 layout 节点快照（seq 3，`$.conversation_history[6].content`），例如 `flow_x1__multi` 的 cassette 第 2 条（LayoutAgent）回复中的 `"x": 668.5, "y": 80.0`。
- **修复（只增加内容，不改变解码结果）**：`json_decoder.ts` 新增导出 `PY_FLOAT_MARKS: WeakMap<object, Set<string>>`。解码对象或数组时，如果某个值的字面量是整数值浮点（数值是整数，且字面量含有 `.`/`e`/`E`），就在容器上记下它的键（数组记下标字符串）；重复键会清除旧标记。解码出的值本身不变，`pyJsonDumps` 也没有改动。只有需要重新序列化模型输出的地方读取这些标记：WP17 的 `layout_agent.ts` / `sequence_layout.ts` 通过 `_with_py_floats` 把被标记的字段包成 `PyFloat` 后再 dumps。
- **验证**：WP13 的 `utils.llm_output`、`core.base_agent` 函数向量全部通过；第一期 `parity:stages` 112/112；WP17 生成阶段 cassette 回放 31/31。
- **遗留**：标记挂在对象上。`structuredClone`、展开运算或 `{...}` 复制之后标记就没了，需要的地方要自己转移（WP17 用 `_deepcopy_with_py_floats`、`_transfer_py_floats`）。下游如果把这些坐标格式化成字符串（如 f-string、`json.dumps`），也会遇到同样的 `80.0` 与 `80` 差异，需要按同样的方法处理。

## WP22-1：Finding 的 `location.bbox` 整数值浮点（`190.0`）在 TS 中丢失，修复提示词里会打印成 `190`

- **登记者**：WP22。**涉及文件**：`src/verification_stage/checks/collision_detection.ts`、`src/verification_stage/checks/finding.ts`（WP19）、`src/py/pydantic.ts`（WP13）。
- **现象**：Python `check_edge_node_intersections` 的 `location={"bbox": list(bbox)}` 中 4 个值都来自 `float(...)`。修复提示词用 `json.dumps(location, sort_keys=True)` 打印，得到 `[666.9, 190.0, 202.0, 76.0]`；TS 是普通 number，打印成 `[666.9, 190, 202, 76]`。WP23 接入后，`big_en_aes__refine` 第 4 次大模型请求（RefinerLLMAgent）的文本会在 `location=` 这一行出现分歧。
- **复现**：`fixtures/functions/evodesign.agentic_system.refinement_stage.agent.prompts/build_refiner_user_prompt.jsonl` 第 1 行（`run:big_en_aes__refine`），以及该样例 cassette 第 4 条请求文本中的 `location={"bbox": [666.9, 190.0, ...`。
- **修复（只加标记，数值不变）**：沿用 WP17-1 的 `PY_FLOAT_MARKS`。`collision_detection.ts` 用 `_float_list(bbox)` 生成 location 中的 bbox 副本，并把 4 个下标都标记为 float。`pydantic.ts` 的 `dumpValue`（`model_dump`）和 `finding.ts` 的 `_json_mode`（`to_dict`）在重建数组/对象时把标记复制到新容器上。修复提示词打印 location 时先经过 `_with_py_floats`。
- **验证**：`PARITY_WP=WP13` 78/78、`WP19` 77/77、`WP20` 21/21、`WP21` 43/43 个测试全部通过（向量 0 失败）；第一期 `functions + wp04-converter + integer-ids` 1061/1061，`parity:stages` 112/112。`Finding({... location: {bbox: 已标记数组}}).to_dict()` 经过 `build_refiner_user_prompt` 后打印 `[666.9, 190.0, 202.0, 76.0]`。
- **遗留**：其他检查的 location 里如果也有 Python float 的整数值（目前录制的修复提示词里只出现了这一处），需要用同样的方法标记。`verifier_report.json` 按值比较，不受影响。

## WP23-1：verifier_report.json 里评审分数（`7.0`）写成了 `7`，修复提示词随之出现 `score=7`

- **登记者**：WP23。**涉及文件**：`src/verification_stage/reports/report_builder.ts`（WP19）。
- **现象**：Python 的 `DimensionCritique.score`、`Critique.overall_score` 是 pydantic `float`，`write_report` 写出 `"score": 7.0`。TS 写成 `7`。迭代修复读回 `verifier_report.json`（`pyJsonLoadsExact`）后没有浮点标记，`build_refiner_user_prompt` 打印 `Layout (score=7):`，Python 是 `score=7.0`。产物按值比较，所以只在提示词里暴露。
- **复现**：`npm run parity:runs -- --case big_en_aes__refine`（修复前）→ `llm @ LLM call 4 (RefinerLLMAgent) … expected "Layout (score=7.0)", got "Layout (score=7)"`；`iot_aes__unified_refine`、`ne_saas_ty1__refine`、`t_class_tz__refine_forced`、`t_er_tz__refine_regress` 相同。
- **修复（只加标记，数值不变）**：`_critique_to_dict` 给 `overall_score` 和 `structure/styling/layout.score` 打 `PY_FLOAT_MARKS` 标记；`write_report` 写 JSON 前经过 `_with_py_floats`（WP17 的工具）。这样 Finding bbox 已有的标记（WP22-1）在报告文件里也会打印成 `190.0`，与 Python 一致。
- **验证**：`PARITY_WP=WP19` 77/77、`WP20` 21/21、`WP22` 22/22 个测试通过；第一期 1123/1123，`parity:stages` 112/112；上述 5 个样例的修复请求全部一致（之后的第一个分歧见 WP23-2）。

## WP23-2（已由 WP24-1 解决）：`analysis_manifest_fingerprint` 依赖 Python 的 int/float 区分，TS 算出的哈希不同

- **登记者**：WP23。**涉及**：`iterative_workflow._manifest_fingerprint`（WP23）对 `json.dumps(manifest, sort_keys=True)` 取 sha256；manifest 来自第一期渲染引擎（WP01–WP10）写出的 `4_render/diagram_manifest.json`。
- **现象**：9 个修复样例全部在第一个 `run_iteration` 快照分歧：`$.analysis_manifest_fingerprint: expected "b7ee…", got "ce4f…"`（`hcai_demo__refine` 等）。Python manifest 里大量坐标是整数值浮点（`120.0`），也有真正的 int（`120`）；同一个键（`x`/`width`/`points`…）在不同元素上两种都有，取决于计算路径（统计见 WP23 notes）。TS 渲染引擎只有 JS number，写出的 manifest 全部是 `120`，`json.dumps` 文本不同，哈希就不同。
- **影响范围**：只影响这个字段的取值。该指纹只用于"分析图是否可以复用"的自比较（`_refresh_image_for_llm`），TS 内部前后一致，行为与 Python 相同。用临时脚本（`tools/parity-runs.ts` 的副本，只在快照比较时忽略 `analysis_manifest_fingerprint`，未入库）回放 9 个修复样例：**9/9 全部一致**（大模型请求、全部快照、产物、`process_example` 结果）。
- **可能的处理**：(a) 让第一期渲染引擎逐值记录 Python 的 float/int（工作量大，牵涉 WP01–WP10 全部模块）；(b) 在对照工具中把 `analysis_manifest_fingerprint` 列为与 `duration_ms` 同类的"按规则归一化字段"（需 WP12/WP24 决定，WP23 无权修改 harness/tools）。

## WP24-1：渲染引擎与修复流程按 Python 记录 int/float，解决 WP23-2 的指纹分歧

- **登记者**：WP24。**处理方式**：采用 WP23-2 中的方案 (a)。没有改 harness 或 tools，也没有把指纹列为归一化字段。
- **现象**：见 WP23-2。9 个修复样例在 `run_iteration` 快照的 `$.analysis_manifest_fingerprint` 处分歧，根因是 TS 写出的 manifest 里没有 Python 的整数值浮点（`120.0`）。
- **定位工具**（scratchpad 临时脚本，未入库）：
  - `floatcheck.mts`：回放 36 个样例，在每个快照处比较"值为整数值浮点的 JSON 路径集合"，TS 一侧按 `PY_FLOAT_MARKS` 取，Python 一侧从 `snapshots.jsonl` 原文取。
  - `stagefloatcheck.mts`：对第一期 112 个阶段样例逐节点做同样的比较。
  - `artfloatcheck.mts`：对 36 个样例写出的全部 JSON 产物做同样的比较。
  - 最早出问题的节点是 `excalidraw_add_icon_urls`（`structuredClone` 丢标记），之后依次修到每个节点都一致。
- **修复（只加标记，数值不变，因此值级对照不受影响）**：
  - 新增 `src/py/float_marks.ts`，提供以下工具：`markF/isF/copyF`、`pyDeepcopy`（`copy.deepcopy`，保留标记）、`pyUpdate/pyMerge`（`dict.update` / `{**a, **b}`）、`assignF`（字面量 update，非浮点键清除旧标记）、`orF`（`a or b or c` 取到的那个值的类型）、`withPyFloats`（写 JSON 前把标记转成 `PyFloat`）。
  - 每个写入位置都按 Python 表达式的结果类型标记：`float()`、`/`、浮点常量得到 float；`max/min` 取胜出的那个操作数的类型（并列时取第一个）；`math.ceil`、`int()`、`sum([])`、整数常量得到 int。
  - **第一期渲染引擎**：
    - `structuredClone` → `pyDeepcopy`，涉及 16 个文件（WP02/04/05/06/07/08/10/14）。
    - 按 Python 表达式标记的模块：
      - `converter`、`shape_size_fitter`（WP04）
      - `group_fitter`、`group_alignment_normalizer`、`layered_layout_compactor`（WP05）
      - `radial_concept_compactor`（WP06）
      - `arrow_adder`、`arrow_routing/{geometry,labels,passes}`、`sequence_layout`（WP07）
      - `architecture_design_system`（WP08）
      - `design_theme`、`caption_placer`（WP09）
      - `common/node_icons`、`element_shape_estimator._estimate_text_dimensions`（WP02）
  - **写文件**：`json.dump` 对应的写入点都经过 `withPyFloats`，涉及 `render_engine/service`（WP14）、`agentic_system/{workflow,main,iterative_workflow}`（WP23）、`generation_stage/workflow`（WP17）、`refiner_report`（WP22）、`utils/io_utils`（WP13）。迭代修复用 `pyJsonLoadsExact` 读回 manifest，标记随之恢复。
  - **修复流程**：
    - `fixers/primitives`：`set_position/set_size` 的 `float()` 结果、随宿主移动的文字、`set_style` 中照搬的值、`version`（int）。
    - `fixers/arrow_reroute`：`ArrowRouteGeometry` 全部是 float（WP21）。
    - `best_findings_score` 有两条规则：`sum` 遇到空列表结果是 int 0；`min` 取胜出操作数的类型（WP23）。`refiner_report.final` 照搬状态里的值（WP22）。
  - **pydantic**：`src/py/pydantic.ts` 的 `FieldSpec` 新增 `py_float`，经过校验的数值标记为 float；`model_dump`/`model_copy` 保留标记。用到它的字段有 `DimensionCritique.score`、`Critique.overall_score`（WP20）和 `VerifierRefinerState.best_findings_score`（WP22）。最后一个字段需要它，是因为 LangGraph 在节点之间会重新校验 pydantic 状态，`Optional[float]` 在这时被强制转成 float。
- **验证**：
  - `npm run parity:runs`：**36/36**。大模型请求 158/158，快照 853/853，产物 525/525，容差图片 0。
  - 浮点路径集合：36 个样例的全部快照一致；36 个样例的全部 JSON 产物一致；第一期 112 个阶段样例的每个节点都一致。
  - 函数向量：全部 138 个模块 34504 条通过，0 失败。
  - 第一期：`functions + wp04-converter + integer-ids` 1123/1123，`parity:stages` 112/112。
  - 全量 vitest 1142/1142，`tsc --noEmit` 0 错误。
- **遗留**：
  - 标记只覆盖录制样例和阶段样例实际走到的代码路径，这些路径已经逐一核对过。没走到的分支如果新写入整数值浮点，值不受影响，只会让 JSON 文本里的 `120.0` 变成 `120`；如果这个值被哈希，也会影响哈希。
  - 新代码写 manifest 数值时，要用 `markF/assignF/pyUpdate`；复制时用 `pyDeepcopy`/`pyDictCopy`，不要用 `structuredClone` 或 `{...}`。

## WP27-1：函数向量依赖 pytest 临时目录，被 pytest 轮转删除后 3 条向量失败（环境问题）

- **当前状态**：已由 WP34-1 的文件字节快照与 MemoryFS 回放解决；下文保留最初调查记录。

- **登记者**：WP27。**未修改**（fixtures 归 WP12/录制工具所有）。
- **现象**：`npx vitest run` 中 `test/parity/functions.test.ts` 有 3 条失败：
  - `refinement_stage.__main__._infer_canvas_library_from_manifest`（期望 `tldraw`，得到 `excalidraw`）
  - `iterative_workflow._input_fingerprint`
  - `iterative_workflow._node_load_inputs`
- **根因**：这些向量的参数是 pytest 的 `tmp_path` 绝对路径（`/private/var/folders/.../pytest-of-zhanyi/pytest-103/...`），函数在 TS 侧会去读这些文件。pytest 只保留最近 3 个 `pytest-N` 目录；同一台机器上有人再跑 pytest（当前已到 `pytest-108`），`pytest-103` 被删除，文件不存在，TS 走了"文件不存在"分支。与 WP27 的改动无关（NodeFS 直接调用 `node:fs`，读不存在的文件在改动前后行为一致）。
- **可能的处理**：录制时把 `__path__` 指向的文件内容一起存进 fixtures，回放前在临时目录（或 MemoryFS）里还原；或在 `export_fixtures.py` 中把 `tmp_path` 改到仓库内的固定目录。

## WP27-2：浏览器运行的后续事项（交给 WP28 / WP29 / WP31）

- **登记者**：WP27。WP27 只负责"没有 node 内置模块"，以下几点不影响 esbuild 检查，但浏览器里真正运行时需要处理：
  - 4 处 `await import(new URL('<相对路径>.ts', import.meta.url).href)`（为绕开循环依赖的可选/延迟导入）：`common/domain_knowledge_loader.ts`、`agentic_system/config.ts`、`verification_stage/reports/report_builder.ts`、`refinement_stage/fixers/apply_edits.ts`。打包后这些 URL 指向不存在的 `.ts`，前两处有 `.catch(() => null)` 兜底（行为会变成"模块不存在"），后两处会抛错。WP31 需要改成打包器能识别的静态/动态导入。
  - 浏览器平台的 `AsyncContext`（`src/py/platform_browser.ts`）是单线程替身：`run` 在同步部分和返回的 promise 结束前保持 store。严格嵌套时正确；同一个 context 上有并发、交错的 `run`（例如并行节点各自开 `_CALL_BUDGET`）时会互相看到对方的 store。WP29/WP31 需确认流水线在 Worker 中的并发形态，必要时改为显式传参。
  - `canvas_render.CanvasRenderBase._resolve_script_path` 会检查 `tool_services/scripts/render-excalidraw.ts` 是否存在；浏览器资源包（WP31）如果不包含它，渲染会在调用渲染器之前就报 FileNotFoundError。WP28 接入 `PngRenderer` 时一并处理。
  - 浏览器平台下 `spawn` / `renderExcalidrawPage` 为 null（调用时报错），由 WP28 通过 `setPlatform({ renderExcalidrawPage })` 或新的 `PngRenderer` 接口接管。

## WP26-1：`tools/parity-runs.ts` 当前版本启动即报 `ReferenceError: Cannot access 'nodeIO' before initialization`

- **当前状态**：已解决。`nodeIO` 改为可提升的函数声明，磁盘完整回放 36/36 通过；下文保留最初调查记录。

- **登记者**：WP26（只登记，未修改，该文件属于 WP27 正在进行的 `--fs memory` 改动，文件时间 2026-11-05 15:41）。
- **现象**：`npm run parity:runs` 在第一个样例就退出：`replay()`（第 164 行）用到 `nodeIO`，但 `const nodeIO` 声明在模块末尾（第 322 行），而顶层 `for … await replay(…)` 循环（第 133 行）先于它执行，触发 TDZ。
- **验证**：把 `nodeIO` 的声明挪到循环之前（临时拷贝，跑完已删除），`parity:runs` 结果为 36/36，说明流水线本身没有问题。
- **建议修复**：把 `const nodeIO` 移到顶层循环之前，或改成函数声明。
- **另**：`npx vitest run` 有 3 个函数向量失败，原因见 WP27-1（pytest 临时目录被轮转删除），与 WP26 无关。


## WP34-1：修复 pytest 临时文件依赖（解决 WP27-1）

- `tools/wp34/capture_runtime_inputs.py` 在原有 Python 测试的三个函数入口捕获文件字节，不改 Python 实现或期望结果。原测试 145/145 通过。
- 文件字节保存在 `test/fixtures/runtime_inputs.json`，按函数、测试目录名、调用次序索引。
- `test/harness/pytest_files.ts` 用一次性的 MemoryFS 覆盖录制路径；保留原始路径字符串，使指纹与错误文本仍可精确比较。每条向量结束恢复 FS。CLI 的内容读取也改走 RuntimeFS。
- `iterative_workflow` 26/26 已通过；完整函数对照随 WP34 一并复跑。

## WP31-1：本机默认 Node 版本低于 Vite 要求

- 默认 Node 20.11.1 缺少 `crypto.hash`，带 Worker 的 Vite 构建会失败。
- 使用 Codex 自带 Node 24.22.1 后构建通过；这是本机工具版本问题。验收脚本和构建要求 Node >=22.12。
- 浏览器包不包含 Node 内置模块。

## WP34-2：同步回放占用事件循环，触发 Vitest 状态 RPC 超时

- 全量运行的 1194 项断言全部通过，但 Vitest 记录两次 `Timeout calling "onTaskUpdate"` 并以失败退出；单 worker 同样复现。
- 大组函数向量会连续执行数十秒（箭头渲染组超过一分钟），整数 ID 回放也连续同步运行，Worker 无法及时消费状态回复。
- 函数测试在每条向量之前、整数 ID 测试在每个独立用例之前 `await setImmediate()`，让状态回复得到处理。生产逻辑、向量、断言和阈值均未调整；最终复跑结果见 `PHASE3_REPORT.md`。
