# 渲染引擎 Python → TypeScript 迁移计划

> 本文件既是给人看的计划，也是每个迁移子 agent 必须遵守的工作契约。
> 源码基线：`refactor/arrow-router` 分支（基于 main `735c548`，含 arrow_adder 拆分重构）。

## 1. 目标与范围

**目标**：把 `evodesign/agentic_system/render_engine` 的 Excalidraw 渲染流水线迁移成纯 TypeScript 包
`packages/render-engine`。迁移后，给定同样的 structure/layout 输入，TS 版产出的 Excalidraw manifest 与
Python 版**逐字段一致**（数值误差 ≤ 1e-6），从而出图一致。

**本次范围（今晚完成）**：

| 包含 | 不包含（后续阶段，见 §10） |
|---|---|
| Excalidraw 流水线 9 个阶段：图标 URL → 转换 → 尺寸适配 → 分组框 → 对齐/压缩 → 连线 → 设计系统/主题 → 图层顺序 → 校验 | tldraw 路径（线上只用 Excalidraw） |
| 这些阶段依赖的 `common/` 与 `generation_stage/layout/element_shape_estimator` | Router/Structure/Styling/Layout 四个 LLM 阶段 |
| 对照测试、台账、逐阶段对照、出图对比报告 | 前端接入（替换 `frontend/src/services/browser/scene.ts`） |

纯计算部分先迁，是因为它 100% 确定性、可以逐字段验证；LLM 阶段的"一致"只能做到提示词与解析逻辑一致，验证方式不同，放到第二阶段。

## 2. 包结构与命名规则（为了可追溯，刻意不按 TS 习惯命名）

```
packages/render-engine/
  src/
    py/                     Python 语义运行时（json.dumps、sha256、round、排序比较……）
    common/...              ← evodesign/agentic_system/common/...
    generation_stage/layout/element_shape_estimator.ts
    render_engine/
      shared/...            ← render_engine/shared/...
      excalidraw/...        ← render_engine/excalidraw/...（含 arrow_routing/）
      workflow.ts state.ts stages.ts
  test/
    harness/                fixtures 解码、结构比较、参数绑定（共享，勿改）
    parity/functions.test.ts 通用函数级对照
    adapters/<python模块>.ts 个别函数表示不同时的适配/跳过（需写原因）
  tools/
    export_fixtures.py      从 Python 导出对照数据
    parity-stages.ts        逐阶段对照
    ledger.ts               生成台账
  fixtures/                 （gitignore）函数向量 + 阶段快照
  migration/
    modules.json            模块 → TS 文件 → 工作包，唯一事实来源
    MIGRATION_PLAN.md       本文件
    LEDGER.md               自动生成的进度/一致性台账
    notes/WPxx.md           每个工作包的决策与偏差记录
    notes/ISSUES.md         跨工作包问题登记
```

规则：
1. **一个 Python 模块对应一个 TS 文件**，路径与 `modules.json` 完全一致。
2. **函数名、类名、常量名与 Python 完全相同**，包括前导下划线（`_avoid_node_intersections`）。对照测试按名字自动找函数。
3. **参数**：Python 的所有参数（包括 keyword-only）按声明顺序变成 TS 的位置参数；默认值与 Python 相同。
4. 每个 TS 文件第一行：`// Ported from evodesign/agentic_system/<path>.py — keep in sync.`
5. 不引入任何运行时依赖（以后要在浏览器里跑）。不使用 `node:` 模块，资源文件读取通过 `src/py/assets.ts` 统一入口。

## 3. 一致性如何保证：三层对照

| 层级 | 数据来源 | 判定 | 命令 |
|---|---|---|---|
| ① 函数级 | 112 个样例 + 551 个单元测试运行时，追踪 39 个模块 378 个函数的真实调用，共 16430 条向量（参数、返回值、调用后参数、异常） | 每条向量的返回值、原地修改后的参数、是否抛异常都一致 | `PARITY_WP=WP07 npm run parity` |
| ② 阶段级 | 112 个样例 × 9 个阶段的 manifest 快照 | **隔离模式**：用 Python 第 N-1 阶段的快照喂给 TS 第 N 阶段，只要不一致就一定是这个阶段的问题；**串联模式**：TS 从头跑到尾，每一阶段都要一致 | `npm run parity:stages` |
| ③ 出图级 | 同一个渲染器分别渲染 Python 和 TS 的最终 manifest | 像素差异报告（HTML 对比画廊） | `npm run render` |

**判定标准**（`test/harness/compare.ts`）：结构、类型、字符串、布尔、null 完全一致；数字误差 ≤ 1e-6（超过 1e-9 的计入 "tolerated" 单独统计）；Python 的 tuple 与 list 都视为数组；set 不比较顺序；dict 的 key 顺序不一致只记录、不判失败。

向量由 `tools/export_fixtures.py` 生成：追踪时 551 个 Python 单元测试必须全部通过，否则拒绝写出向量，保证追踪本身没有改变行为。

## 4. Python → TS 翻译规则（最容易出错的地方）

所有 Python 语义 helper 统一放在 `src/py/`（WP01 负责），其他工作包**必须使用**，不得各写各的。

| Python | TS 中必须这样做 | 原因 |
|---|---|---|
| `json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)` | `py/json.ts: pyJsonDumps` | 分隔符是 `", "`/`": "`；浮点用 repr（`1.0` 不是 `1`）；元素 ID 是对它做 sha256，错一个字符所有 ID 都变 |
| `hashlib.sha256/md5(...).hexdigest()` | `py/hash.ts`，纯 TS 实现，UTF-8 编码 | 浏览器可用，不能依赖 `node:crypto` |
| `x or y`、`if x:` | `py/truthy.ts: truthy(x)` | JS 里 `[]`、`{}` 是真值，Python 里是假值 |
| `a == b`（list/dict/tuple） | `pyEq(a, b)` 深比较 | JS `===` 比的是引用 |
| `x in list_of_tuples` | `pyIn(x, list)` | 同上 |
| `sorted(key=...)`、`min/max(key=...)`、tuple 比较 | `pySorted`、`pyMin/pyMax`（并列时取第一个）、`pyCmp` | Python 按 tuple 逐项比较；字符串按码点比较 |
| `round(x)`、`round(x, n)` | `pyRound`（银行家舍入，按 Python 的十进制规则） | `Math.round(2.5)=3`，Python `round(2.5)=2` |
| `a // b`、`a % b`、`int(x)` | `floorDiv`、`pyMod`、`Math.trunc` | 负数时语义不同 |
| `len(s)`、切片、`s[i]` | 按码点：`[...s]` | 中文、emoji 出现在标签里 |
| `str.split()`（无参）、`strip()`、`lower()` | `pySplit`、`pyStrip` | 无参 split 会合并空白、去掉首尾 |
| `str(float)`、f-string 中的浮点 | `pyStr`（repr 规则：`1.0`、`1e+16`） | JS `String(1.0)` 是 `"1"` |
| `dict`（字符串 key） | 普通对象，保持插入顺序 | — |
| `dict`（key 可能是数字字符串、tuple、非字符串） | `Map` | JS 对象会把类似整数的 key 排到前面 |
| `set` | `Set`；若迭代顺序影响输出，必须先排序，并在 notes 里说明 | Python set 的迭代顺序与插入顺序无关 |
| `None` | `null`（数据里不得用 `undefined` 代替） | manifest 里 key 存在且为 null 与 key 不存在是两回事 |
| `isinstance(x, int)` | 注意 `bool` 也是 int | — |
| `deepcopy` | `structuredClone` | — |
| `math.hypot/dist/copysign/log/ceil` | `py/math.ts` 统一封装 | 便于日后统一修正末位差异 |
| `raise ValueError(...)` | `py/errors.ts` 中同名 Error 子类 | 向量会校验"是否抛异常" |
| `logging` | `py/logging.ts` 空实现 | — |
| `os.environ` 开关 | `py/env.ts: getEnv(name)`，默认值与 Python 相同 | 浏览器里没有 `process.env` |
| `unicodedata.east_asian_width` | `py/unicodedata.ts`，只实现用到的函数 | — |
| 读取 `assets/*.json`、图标 SVG | `py/assets.ts` 统一入口（Node 下读文件，日后浏览器改为打包导入） | 单一来源，仍读 Python 侧的资源文件 |

## 5. 工作包、负责人与依赖

每个工作包（WP）由一个子 agent 负责。包内模块高度耦合，拆得更细反而会产生互相等待。

| WP | 内容 | 依赖 | 模块数 | Python 行数（约） |
|---|---|---|---|---|
| WP01 | `src/py/` 运行时 + semantic_ids、spec_utils、diagram_types、design_constraints、tldraw_utils（只迁用到的部分）、order_keys、label_geometry | — | 7+runtime | 1.2k |
| WP02 | node_icons、icon_assets、layout_contract、element_shape_estimator、icon_url_adder | WP01 | 5 | 1.2k |
| WP03 | edge_routing、edge_crossing_detector、normalization、render_audit | WP01 | 4 | 1.9k |
| WP04 | converter、normalizer、shape_size_fitter、validator | WP01-03 | 4 | 1.7k |
| WP05 | group_fitter、group_alignment_normalizer、layered_layout_compactor、zorder_repair | WP01-03 | 4 | 1.3k |
| WP06 | radial_concept_compactor | WP01-02 | 1 | 2.0k |
| WP07 | edge_router、arrow_routing/*（7 个）、arrow_adder、sequence_layout | WP01、03、04 | 10 | 3.9k |
| WP08 | architecture_style_normalizer、architecture_design_system | WP01-02 | 2 | 1.4k |
| WP09 | caption_placer、design_theme | WP02、08 | 2 | 0.5k |
| WP10 | workflow/state/stages 编排、逐阶段对照（112 个样例）、出图对比报告；修复联调问题 | WP04-09 | 3 | 0.4k |
| WP11 | 独立验收：不看实现者的结论，从零复跑全部对照，抽查翻译，写最终报告 | WP10 | — | — |

执行顺序（流水线，依赖满足就立即开工）：

```
WP01 ─┬─ WP02 ─┬─ WP06
      │        ├─ WP08 ── WP09 ─┐
      ├─ WP03 ─┼─ WP04 ── WP07 ─┼─ WP10 ── WP11
      │        └─ WP05 ─────────┘
```

关键路径：WP01 → WP02/WP03 → WP04 → WP07 → WP10 → WP11。

## 6. 每个子 agent 的工作流程与完成标准

**流程**
1. 读本文件 §2、§4，以及 `modules.json` 中自己负责的模块。
2. 逐个模块完整阅读 Python 源码，**逐函数忠实翻译**，保持控制流和计算顺序（浮点运算顺序不同，结果就可能不同）。不做优化、不改算法、不合并逻辑。
3. 每完成一个模块就跑：`PARITY_MODULE=<模块名> npx vitest run test/parity/functions.test.ts`，有失败时按报告里的 JSON 路径定位。
4. 全部完成后：`PARITY_WP=WPxx npm run parity`、`npm run typecheck`、`npm run ledger`。
5. 写 `migration/notes/WPxx.md`。

**完成标准（全部满足才算完成）**
- 本 WP 所有模块的 TS 文件存在，Python 顶层函数/类/常量全部有同名 TS 实现。没有向量覆盖的函数，要在 notes 里逐个列出。
- 本 WP 的函数级对照**失败数 = 0**。跳过只允许"表示方式无法比较"一类情况，必须在 adapter 里写明原因，并在 notes 里列出。
- `npm run typecheck` 通过。
- notes 包含：完成情况、偏差与原因、未覆盖函数、已知风险、给下游的提示。

**边界**
- 只能新建或修改自己负责的文件、自己模块的 adapter、自己的 notes。
- 不得修改 Python 代码、fixtures、harness、`modules.json`。
- 如果发现上游 WP 的 bug：先在 `notes/ISSUES.md` 登记（现象、复现命令、向量行号），再做最小修复，并确认上游 WP 的对照仍然全部通过。
- 不提交 git，不安装新依赖。

## 7. 出问题时怎么定位（排查顺序）

1. `npm run parity:stages`：看每个样例的**串联模式第一个分歧阶段**。
2. 看同一样例的**隔离模式**：哪个阶段失败，问题就在哪个阶段。如果隔离模式全部通过、只有串联模式失败，说明是数值误差在累积，检查报告里的 tolerated 计数。
3. 进入该阶段入口函数的向量：`PARITY_MODULE=<模块> npm run parity`，报告会给出类似 `$.elements[12].x: expected 340, got 352` 这样的精确路径。
4. 顺着调用链进入内层函数的向量（378 个函数大多有独立向量），逐层缩小到具体的函数。
5. 定位到函数后，在 Python 侧用同一条向量（`fixtures/functions/<模块>/<函数>.jsonl` 第 N 行）复现，逐行对比。
6. 修复后重跑该函数、该模块、阶段对照，再更新台账。所有跨 WP 的修复都要登记在 `ISSUES.md`。

## 8. 台账与可追溯

- `migration/LEDGER.md`（`npm run ledger` 自动生成）：每个模块的迁移状态、向量通过数/失败数/跳过数、阶段对照结果、各 WP 的 notes 链接。
- `reports/functions/<模块>.json`：每个函数的失败样例（前 5 条，带向量行号和 JSON 路径）。
- `reports/stages.json`：每个样例在串联和隔离两种模式下的结果。
- 任何人拿到一个不一致的结果，都能沿着"阶段 → 函数 → 向量行号 → Python 源码行"一路追查下去。

## 9. 今晚的执行安排与明早的交付物

由编排脚本按依赖顺序自动调度各 WP 的子 agent。每个 WP 结束后自动跑一次该 WP 的对照，失败数大于 0 时，带着失败报告交回同一个 WP 继续修复（最多 2 轮）。

**明早可以看的东西**
1. `migration/LEDGER.md`：整体进度和一致性数字。
2. `reports/visual/index.html`：112 个样例 Python 出图与 TS 出图并排对比，附像素差异。
3. `migration/FINAL_REPORT.md`：WP11 的独立验收结论、剩余问题清单，以及每个问题的定位路径。

## 10. 后续阶段（不在今晚范围内）

1. **浏览器接入**：`py/assets.ts` 改为打包导入；在 `frontend` 里用 `packages/render-engine` 替换 `services/browser/scene.ts` 的 `renderPlan`；放进 Web Worker 运行，避免卡顿。
2. **性能**：85% 的时间在可见性网格寻路 `_find_orthogonal_visibility_route`。V8 本身就会比 Python 快很多；之后可以再做增量网格、空间索引。每次优化都要用同一套对照数据保证输出不变。
3. **LLM 阶段**：迁移提示词组装、输出解析与校验逻辑（同样可以录制向量来对照），LLM 调用通过 Vercel Function 代理。
4. **单一实现**：TS 版稳定后，Python 后端改为通过 `npx tsx` 调用 TS 渲染引擎，删除 Python 渲染代码，两端只保留一份实现。
