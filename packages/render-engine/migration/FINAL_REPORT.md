# 渲染引擎 Python → TypeScript 迁移：WP11 独立验收报告

验收人：WP11（独立验收）· 日期：2026-11-04 · 包：`packages/render-engine`

## 1. 结论

**有条件通过（accepted with issues）。**

在现有 112 个样例和 551 个单元测试覆盖到的输入上，TS 版和 Python 版的输出**逐位一致**：函数向量全部通过，每个阶段的快照没有一个数字差异，最终出图像素完全相同。实现者写的台账数字我都重新跑过，没有发现虚报。

验收中我自己补了一批 Python 对照向量，发现了 **1 个中等问题**：语义 ID 是纯数字（如 `"1"`、`"2"`）时，TS 和 Python 的输出不一致。现有 fixtures 里没有这种输入，所以台账显示不出来。另外还有几个低风险问题，见 §5。如果上线前能保证（或在 Structure 阶段强制）节点 ID 不是纯数字，这个迁移就可以作为 §10 后续工作的基础。

## 2. 关键数字（全部由 WP11 从干净状态重新跑出）

| 指标 | 结果 | 来源 |
|---|---|---|
| `tsc --noEmit` | 通过（0 个错误） | 命令退出码 0 |
| `vitest run` | 3 个测试文件，525/525 个测试通过 | 其中函数对照 393 个、转换器阶段对照 113 个、运行时 19 个 |
| **函数向量** | **16430/16430 通过**：失败 0、跳过 0、只在容差内相等的数字 0、key 顺序差异 0 | `reports/functions/*.json`（42 个模块）、`migration/LEDGER.md` |
| 有向量的函数 | 378 个被追踪函数中有 351 个有向量；27 个有调用但向量数为 0 | `fixtures/functions/_summary.json` |
| **阶段对照（串联）** | **112/112 个样例 × 9 个阶段全部一致** | `reports/stages.json` |
| 阶段对照（隔离） | 1008/1008 个阶段一致 | 同上 |
| 阶段数值误差 | 只在容差内相等的数字 0 个，最大绝对差 **0**，112 个样例全部逐位一致 | `migration/wp11/stage_tolerance.mts`（WP11 自写） |
| **出图** | **112/112 像素完全相同**（PNG 文件字节也相同，没有空白图） | `migration/wp11/visual_check.py` |
| 出图数据核对 | `ts.json` 与当前 TS 代码重新生成的结果 112/112 一致；`python.json` 与 fixture 最后阶段快照 112/112 一致 | `migration/wp11/visual_ts_regen.mts` |

## 3. 我验证了什么、怎么验证的

### 3.1 从零复跑（不采信实现者的结论）
先 `rm -rf reports/functions reports/stages.json`，再依次跑 `npx tsc --noEmit`、`npx vitest run`、`npm run parity:stages`、`npm run ledger`。全部成功，台账由这次运行重新生成。fixtures 的生成时间晚于全部相关 Python 源文件，说明快照没有过期。生成环境是 CPython 3.11.9。

### 3.2 审查对照工具本身
- `test/harness/compare.ts`：数字容差为绝对 1e-6；结构、类型、null、多出或缺少的 key 都会判失败。判定是严格的。
- 7 个 adapter 一个跳过都没有。它们只做三类事：把 JSON 丢失的对象别名关系接回去（shape_size_fitter、passes）；把 dataclass 重建成实例（arrow_adder、ports）；用虚拟图标目录代替 pytest 里的 monkeypatch（icon_assets、converter），以及按浮点重新绑定参数（spec_utils）。这些理由都成立，不会掩盖真实差异。
- `parity-stages.ts` 不统计"容差内相等"的数字，所以我写了 `stage_tolerance.mts` 补测：结果是 0。
- 对照工具有几个看不到的盲区：`-0` 和 `0` 视为相等；int 和 float 视为相等；`kwargs_after` 不比较（我检查过，目前 0 条向量会改 kwargs）；纯数字 key 的顺序看不出来（因为两边都经过 `JSON.parse`）。后两类问题是我自己补测时发现的，见 §5。

### 3.3 无向量 / 从未调用的函数（逐个对读 Python 与 TS）
**有调用、但向量为 0 的 27 个函数**：
- converter 的 9 个类方法：由 `test/parity/wp04-converter.test.ts` 的 112 个阶段对照覆盖。
- architecture_design_system 的 13 个函数：由 56 个架构图样例的阶段对照覆盖。我对读了 `_assign_service_hues`、`_barycenter_order`、`_canonical_role`、`_hex`，翻译是忠实的。
- `passes._commit_best_updates`：对读过，忠实。
- `icon_assets.icon_manifest_path`：只是路径拼接。
- `edge_routing.iter_shape_id_candidates`、`radial._best_branch_order`、`radial._best_radial_slots`：我补了向量，见 §3.4。

**Python 中定义了、但 112 个样例和单元测试都从没调用过的 69 个函数**，主要是这几类：
- tldraw 路径、LLM 相关的 spec_utils、workflow 编排：不在本期范围。
- 带 `lru_cache` 的函数和 `@property`：追踪器挂不上，但通过调用方间接覆盖。

其中 Excalidraw 路径上真正"零覆盖"的函数，我都补了 Python 向量去对照：`iter_concept_nodes`、`resolve_label_from_node_ref`、`normalize_text`（含全角空格、`\x1c`、`\x85`、` ` 等 Unicode 空白）、`sort_and_reindex`、`converter._extract_icon_dimension`、`_svg_text_to_data_uri`（含中文和 emoji）、`_icon_to_data_url` 的各个分支。**结果 74/74 一致。**

### 3.4 三个最高风险区的翻译抽查（补测的 Python 向量）
| 区域 | 补测内容 | 结果 |
|---|---|---|
| `src/py/json.ts` 对比 `json.dumps` | 4 组参数 × 47 个值：`1.0`、`1e16`、`1e15`、`0.1+0.2`、`-0.0`、`5e-324`、NaN/Inf、各类 Unicode 和控制字符、嵌套 `sort_keys`、indent；另测 `str/repr` 25 个、`round` 315 个 | dumps 184/188（4 个失败都是 §5 的问题 4：Python int 2^53）；str/repr 25/25；round 315/315 |
| `arrow_routing/grid_router.ts` 的堆排序并列处理 | 400 个随机网格（整数坐标，大量等代价路径，带 port_normals、已有箭头、-0.0 起点），对比路线和 memo key | 路线 400/400、memo key 400/400；带符号零有 26/400 不同（§5 问题 3） |
| `radial_concept_compactor` 的排列顺序 | `_best_branch_order` 300 个、`_best_radial_slots` 300 个，再加上和 `itertools.permutations` 直接对比 6 组 | 300/300；slots 有 286/300 完全一致，另外 14 个**内容相同、只有 key 顺序不同**（§5 问题 1 的同一根因，调用方只用 `.get`，不影响输出）；permutations 6/6 |

堆的判断依据：Python 堆里存的是 `(cost, serial, ...)`，serial 不会重复，所以弹出顺序是一个全序。TS 的 `_Heap` 先比较 cost 再比较 serial，因此和 `heapq` 的弹出顺序必然相同。随机测试也证实了这一点。

### 3.5 输入变形的阶段对照（WP11 新增）
把 112 个样例中的结构 ID 统一改名，然后分别重跑 Python 和 TS 的全流程：
- 对照组：改成 `n1`、`n2`…，结果 **112/112 一致**。这说明改名脚本本身没有问题。
- 改成纯数字 `"1"`、`"2"`…（按字母序编号）：**只有 4/112 一致**，其中 3 个是两边都在 add_icon_urls 抛出同一个错。其余 108 个都在 `excalidraw_convert` 阶段出现首个差异。
- 改成纯数字、并按 layout 中的出现顺序编号：109/112 一致。

## 4. 剩余问题清单

定位路径的格式：阶段 → 模块 → 函数 → 复现命令或向量。所有 WP11 脚本都在 `migration/wp11/`。较大的变形样例在 `reports/wp11/`（已在 gitignore 中）。

### 问题 1【中】纯数字语义 ID 时，元素顺序、ID 和颜色都和 Python 不一致
- **现象**：节点 ID 是 `"1"`、`"8"` 这类规范整数字符串时，TS 的元素顺序与 Python 不同。由此元素 id、seed、颜色分配、groupIds 和坐标都会跟着变。
- **根因**：JS 普通对象会把"整数索引"形式的 key 提到最前面并升序排列，而 Python dict 保持插入顺序。`layout_instantiation` 等以语义 ID 为 key 的字典都是普通对象，在 `JSON.parse` 时顺序就已经丢了（`pyJsonLoads` 同样有这个问题）。
- **定位**：阶段 `excalidraw_convert` → `render_engine.excalidraw.converter` → `InstantiationToExcalidrawConverter.convert`，`src/render_engine/excalidraw/converter.ts:653`（`Object.entries(this.layout_instantiation)`）。输入边界在 `src/render_engine/workflow.ts:239 createWorkflowState`。同一根因也出现在 `radial_concept_compactor.ts:776 _best_radial_slots` 的返回值上，但不影响输出。
- **复现**：
  ```
  cd packages/render-engine
  npx tsx migration/wp11/run_stage_dir.mts reports/wp11/ids_numeric_sorted   # 4/112
  npx tsx migration/wp11/run_stage_dir.mts reports/wp11/ids_prefixed_control # 112/112 对照
  # 重新生成（在仓库根目录执行）：PYTHONPATH=. .venv/bin/python packages/render-engine/migration/wp11/gen_renamed_ids.py <输出目录>
  #   IDPREFIX=n 生成对照组；IDORDER=layout 按 layout 顺序编号
  ```
- **现有台账为什么看不到**：112 个样例的节点 ID 都是 snake_case，而且对照工具两边都经过 `JSON.parse`，key 顺序会被同样改写。Structure 的 schema（`generation_stage/structure/schemas.py`）也没有禁止纯数字 ID。
- **建议**：成本最低的做法是在 Structure 阶段校验（Python 和 TS 两边都加），拒绝纯数字 ID，或者入库时给 ID 加前缀。另一种做法是在入口用 Map 表示 dict，但改动面很大。

### 问题 2【中低】TS 实现绑定的是 CPython 3.11 的语义，而项目允许 3.12+
- **现象**：`pyproject.toml` 写的是 `requires-python = ">=3.11"`。从 Python 3.12 起，浮点 `sum()` 改用补偿求和：`sum([0.1]*10)` 在 3.11 下是 `0.9999999999999999`，在 3.14 下是 `1.0`。TS 的 `pySum` 复刻的是 3.11 的行为（`src/py/number.ts:192`），`math.hypot` 等也按 3.11 实现。Python 渲染代码里有 38 处 `sum(`。
- **定位**：`src/py/number.ts:192 pySum`、`src/py/math.ts`；fixtures 由 `.venv`（3.11.9）生成。
- **建议**：在 §10.4"单一实现"完成之前，把后端 Python 固定在 3.11，或者明确以 TS 为准。如果升级 Python，必须先 `npm run fixtures` 再重跑全部对照。

### 问题 3【低】网格路由中带符号零的符号丢失
- **现象**：起点 x 为 `-0.0` 时，Python 的 `set` 保留 `-0.0`，路线中间点也是 `-0.0`。JS 的 `Set` 会把 `-0` 规整成 `+0`。数值上相等，只有序列化时 Python 写成 `-0.0`、TS 写成 `0`。现有 112 个样例里没有出现。
- **定位**：阶段 `excalidraw_arrows` → `arrow_routing.grid_router` → `_find_orthogonal_visibility_route`，`src/render_engine/excalidraw/arrow_routing/grid_router.ts:227`（`x_values` / `y_values`）。
- **复现**：`npx tsx migration/wp11/run_grid_signed_zero.mts migration/wp11/vectors_grid.json`（第 4 条向量：start=(-0.0,60)，end=(0,120)）。

### 问题 4【低】≥ 2^53 的 Python int 被格式化成浮点
- **现象**：`json.dumps(2**53)` 在 Python 中是 `9007199254740992`，TS 输出 `9007199254740992.0`。`str()` 也一样。目前的哈希载荷里没有这么大的整数。
- **定位**：`src/py/json.ts:92 numberJson`、`src/py/str.ts:43 numberStr`。
- **复现**：`npx tsx migration/wp11/run_json.mts migration/wp11/vectors_json_vec.json`（4 条失败）。

### 问题 5【低，已知设计限制】TS 无法区分 int 和 float
- 值为整数的浮点会输出成 `100`，而 Python 是 `100.0`，除非显式包一层 `PyFloat`。我逐个检查了现有的哈希入口：`converter._generate_excalidraw_id` 的种子、`arrow_adder` 的 `edge_seed`（含 `int(...)`）、`architecture._stable_id`（用 `:.0f` 和 `:.1f` 格式化）、radial 的 sha256。它们都只含字符串和整数，目前没有影响。
- **风险**：以后如果有人把坐标放进哈希或 `str()`，就会导致 ID 全部变化。WP01 的 notes 已经写明这一点，修改这类代码时必须用 `PyFloat`。

### 问题 6【信息】覆盖缺口
- 非内置图标的路径没有被任何样例走到：`_icon_to_data_url` → `require_icon_svg_path` → `_read_svg_as_data_uri`，以及用 `md5(data_url)` 生成 file id。原因是本机没有生成图标 SVG（`tool_services/public/icons/material-design-icons` 下只有 manifest.json）。我只验证了 `data:`、`<svg` 和抛异常这几个分支（`migration/wp11/run_uncovered.mts`）。
- 27 个零向量函数、69 个从未调用的函数，清单见 `python3 migration/wp11/coverage.py` 的输出（需在仓库根目录用 `.venv/bin/python` 运行），以及 `fixtures/functions/_summary.json` 中 `vectors == 0` 的条目。
- fixtures 是基于**未提交**的 Python 工作区生成的（`arrow_routing/` 尚未纳入版本控制，arrow_adder 等文件有修改）。Python 侧一旦变动，必须重新跑 `npm run fixtures`。
- `migration/notes/ISSUES.md` 不存在。各 WP 的 notes 都说明没有发现跨 WP 问题，这和我的复跑结果一致。

## 5. 复跑命令汇总
```
cd packages/render-engine
rm -rf reports/functions reports/stages.json
npx tsc --noEmit && npx vitest run && npm run parity:stages && npm run ledger
npx tsx migration/wp11/stage_tolerance.mts                      # 阶段数值误差统计
../../.venv/bin/python migration/wp11/visual_check.py            # 出图像素核对
npx tsx migration/wp11/visual_ts_regen.mts                       # ts.json 是否为当前代码输出
npx tsx migration/wp11/run_uncovered.mts migration/wp11/vectors_vec1.json
npx tsx migration/wp11/run_json.mts      migration/wp11/vectors_json_vec.json
npx tsx migration/wp11/run_grid.mts      migration/wp11/vectors_grid.json
npx tsx migration/wp11/run_radial.mts    migration/wp11/vectors_radial.json
```
向量由同目录下的 `gen_*.py` 生成，需在仓库根目录用 `PYTHONPATH=. .venv/bin/python` 运行。

## 6. 下一步

**先做（建议在 §10 之前完成）**
1. 处理问题 1：在 Structure 校验中禁止纯数字 ID，或在入口统一给 ID 加前缀。然后把 `reports/wp11/ids_numeric_sorted` 这类变形样例纳入正式的 `parity:stages`。
2. 处理问题 2：固定 Python 3.11，或者明确以 TS 为准。
3. 把 Python 侧的 `arrow_routing` 重构提交并合并，再用合并后的代码重新生成 fixtures，复跑全部对照。

**MIGRATION_PLAN.md §10 的后续阶段**
1. **浏览器接入**：`py/assets.ts` 改为打包导入；在 `frontend` 里用本包替换 `services/browser/scene.ts` 的 `renderPlan`；放进 Web Worker 运行。接入时顺便生成图标 SVG，补测问题 6 的非内置图标路径。
2. **性能**：主要耗时在 `_find_orthogonal_visibility_route`（约 85%）。每次优化都必须保持本报告中的全部对照结果不变，包括 `migration/wp11/` 下的补测向量。
3. **LLM 阶段**：迁移提示词组装、输出解析和校验逻辑（同样录制向量对照），LLM 调用通过 Vercel Function 代理。
4. **单一实现**：TS 稳定后，Python 后端改为通过 `npx tsx` 调用 TS 渲染引擎，然后删除 Python 渲染代码。
