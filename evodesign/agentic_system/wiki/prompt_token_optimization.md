# Prompt Token 优化分析

## 1. Token 消耗全景

### 1.1 单次 Pipeline 的输入 Token（13 节点图估算）

| 调用 | System | Conversation History | Task | **总输入** |
|------|--------|---------------------|------|----------|
| Structure | 2598 | 0 | 3514 | **6112** |
| Styling | 2598 | 800 | 5652 | **9050** |
| Layout | 2598 | 2900 | 5226 | **10724** |
| **Pipeline 总计** | 7794 (30%) | 3700 (14%) | 14392 (55%) | **25886** |

**Task Prompt 是最大的消耗项，占 55%，且永远全价（不可缓存）。**

### 1.2 缓存命中情况

LLM API 的 prompt caching 是前缀匹配：prompt 开头相同的部分命中缓存（价格约为全价的 10%），后面不同的部分全价。

```
Structure: [system ──────────── | task ────────────]
           ↑ 首次调用，无缓存

Styling:   [system ──────────── | struct_resp ──── | task ────────────]
           ↑ [system] 可命中缓存    ↑ 全价              ↑ 全价

Layout:    [system ──────────── | struct_resp ──── | style_resp ───── | task ────────────]
           ↑ [system+struct_resp] 可命中 Styling 的缓存  ↑ 全价         ↑ 全价
```

| 调用 | 缓存命中 | 全价 |
|------|---------|------|
| Structure | 0 | 6112 |
| Styling | 2598 | 6452 |
| Layout | 3398 | 7326 |
| **总计** | **5996 (23%)** | **19890 (77%)** |

**Task Prompt 14392 tokens 全部全价，是优化的首要目标。**

## 2. Task Prompt 详细拆解

### 2.1 Structure Task Prompt（3514 tokens）

| Section | Tokens | 内容 |
|---------|--------|------|
| REASONING PROTOCOL | 1032 | 结构诊断的 3 步推理流程 |
| OUTPUT CONTRACT | 780 | 输出 JSON schema 定义 |
| DO / DON'T | 668 | id 命名、group members、edge label 等规则 |
| CURRENT TASK | 499 | Stage 1 任务描述 |
| OPTIONAL PER-TYPE FIELDS | 336 | 每种 chart_type 的可选字段 |
| REMINDER | 155 | 发送前检查清单 |
| 其他（STAGE KNOWLEDGE / DESIGN EXPERTISE / INPUTS） | 40 | 占位符 |

### 2.2 Styling Task Prompt（5652 tokens）

| Section | Tokens | 内容 |
|---------|--------|------|
| **PALETTE CATALOG** | **2990** | **12 个调色板的完整定义（hex 色值、routing table、fill_family 逻辑）** |
| DO / DON'T | 639 | shape 字段、label.text、group title 等规则 |
| OUTPUT CONTRACT | 467 | 输出 JSON schema 定义 |
| REASONING PROTOCOL | 465 | 视觉诊断的推理流程 |
| CURRENT TASK | 460 | Stage 2 任务描述 |
| PHASE 2 DIAGNOSTIC FRAMEWORK | 410 | 视觉诊断框架（recognition anchor、shape language 等）|
| REMINDER | 175 | 发送前检查清单 |
| 其他 | 46 | 占位符 |

### 2.3 Layout Task Prompt（5226 tokens）

| Section | Tokens | 内容 |
|---------|--------|------|
| REASONING PROTOCOL | 1158 | 布局诊断的推理流程 |
| CURRENT TASK | 1535 | Stage 3 任务描述 + 5 种图表类型的具体布局算法 |
| OUTPUT CONTRACT | 859 | 输出 JSON schema 定义 |
| PHASE 3 DIAGNOSTIC FRAMEWORK | 542 | 布局诊断框架（canvas planning、organizer-first 等）|
| SIDE SELECTION RULES | 463 | 边的端点 side 选择规则 |
| DO / DON'T | 519 | 坐标格式、group 矩阵等规则 |
| REMINDER | 99 | 发送前检查清单 |
| 其他 | 51 | 占位符 |

### 2.4 按内容类型分类

| 内容类型 | Structure | Styling | Layout | 合计 | 说明 |
|---------|-----------|---------|--------|------|------|
| **静态知识** | 0 | **2990** | 800 | **3790** | PALETTE CATALOG + chart-type layout rules |
| **方法论** | 0 | 410 | 542 | 952 | DIAGNOSTIC FRAMEWORKS |
| **推理流程** | 1032 | 465 | 1158 | 2655 | REASONING PROTOCOL（每个 stage 不同）|
| **输出格式** | 780 | 467 | 859 | 2106 | OUTPUT CONTRACT（每个 stage 不同）|
| **约束规则** | 668 | 639 | 519 | 1826 | DO / DON'T（每个 stage 不同）|
| **任务描述** | 499 | 460 | 1535 | 2494 | CURRENT TASK（每个 stage 不同）|
| **其他** | 530 | 221 | 613 | 1364 | REMINDER + OPTIONAL FIELDS + SIDE SELECTION + placeholders |

## 3. 可优化项分析

### 3.1 PALETTE CATALOG（2990 tokens）— 最大单体

**是什么：** 12 个预定义调色板（Slate Pro、IBM Carbon Blue、SaaS Indigo Neon 等），每个包含 hex 色值、适用场景、routing table、fill_family 选择逻辑。

**问题：** 这是纯静态参考数据，每次 Styling 调用都要作为 task prompt 发送，2990 tokens 永远全价。

**优化方案：** 移到 `system_prompt/palette_catalog.md`，通过 `skill_loader.py` 加载到 system prompt 中。

**影响：**
- Styling task prompt 从 5652 → 2662 tokens（**减少 53%**）
- System prompt 从 2598 → ~5588 tokens
- 由于 system prompt 是前缀，Styling 的第二次调用起可命中缓存
- Structure 和 Layout 也会看到 palette catalog（~2990 tokens 冗余），但这些 tokens 在缓存前缀里，成本很低

**缓存效果对比：**

| | 当前 | 优化后 |
|--|------|--------|
| Styling 全价 tokens | 6452 | 3462（**省 2990**）|
| Layout 全价 tokens | 7326 | 7326（不变）|
| Pipeline 总全价 | 19890 | 16900（**省 15%**）|

### 3.2 DIAGNOSTIC FRAMEWORKS（952 tokens）

**是什么：** Styling 的 Phase 2 框架（recognition anchor、shape language、colour system）和 Layout 的 Phase 3 框架（canvas planning、organizer-first placement）。

**问题：** 这是方法论知识，不是 stage 专属指令。放在 task prompt 里每次全价。

**优化方案：** 移到 system prompt（`diagram-patterns.md` 或新文件）。

**影响：**
- Styling task 减少 410 tokens
- Layout task 减少 542 tokens
- System prompt 增加 ~952 tokens
- Structure 也会看到这些内容（冗余），但在缓存前缀里

**注意：** 这两个框架分别描述 Phase 2 和 Phase 3 的方法论。如果移到 system prompt，Structure agent 也会看到 Phase 2/3 的方法论，可能产生"越界"风险（Structure 开始考虑视觉/布局问题）。需要评估是否会影响 Structure 的输出质量。

### 3.3 Chart-Type Layout Rules（~800 tokens）

**是什么：** Layout 的 CURRENT TASK 里包含了 5 种图表类型的具体布局算法：
- sequence diagram: 7 条规则（actor lane、lifeline、message arrow 等）
- swimlane: 6 条规则（lane 尺寸统一、node centerline、cross-lane handoff 等）
- mindmap: radial-tree 布局
- matrix: grid snap 布局
- gantt: timeline 布局
- ER: midpoint diamonds、cluster grouping

**问题：** 这些是领域知识，放在 CURRENT TASK 里导致该 section 膨胀到 1535 tokens。

**优化方案：** 移到 `system_prompt/chart_type_layout_rules.md`，通过 `load_skill_system_prompt(diagram_type)` 按需加载。

**影响：**
- Layout CURRENT TASK 从 1535 → ~735 tokens
- System prompt 按 chart_type 动态加载，只有匹配的规则被注入
- 只有 Layout 需要，但 Structure 和 Styling 看到也不会有害

### 3.4 REASONING PROTOCOL（2655 tokens 合计）

**是什么：** 每个 stage 的推理步骤。Structure 有 3 步，Styling 有 4 步，Layout 有 5 步。内容完全不同。

**问题：** 三个 agent 的推理协议完全不同，无法提取公因式。

**优化方案：** 保持在 task prompt 中。这是 stage 专属内容，放在 task prompt 是正确的位置。

### 3.5 OUTPUT CONTRACT（2106 tokens 合计）

**是什么：** 每个 stage 的输出 JSON schema 定义。Structure 定义 nodes/edges/groups 的字段，Styling 定义 color/shape/fill 的字段，Layout 定义 x/y/w/h 的字段。

**问题：** 三个 agent 的输出格式完全不同。

**优化方案：** 保持在 task prompt 中。但可以考虑压缩 schema 描述的冗余度（比如每个 stage 都重复说明 `id` 字段的格式）。

### 3.6 DO / DON'T（1826 tokens 合计）

**是什么：** 每个 stage 的约束规则。内容完全不同：
- Structure: id 命名、group members、edge label 规则
- Styling: shape 字段、label.text、group title 规则
- Layout: 坐标格式、group 矩阵、side 选择规则

**优化方案：** 保持在 task prompt 中。三个 stage 的规则完全不同，无法提取公因式。

## 4. 推荐优化方案

### 优先级排序

| 优先级 | 优化项 | 节省 tokens | 难度 | 风险 |
|--------|--------|-----------|------|------|
| **P0** | PALETTE CATALOG → system prompt | 2990/次 | 低 | 低 |
| **P1** | DIAGNOSTIC FRAMEWORKS → system prompt | 952/次 | 低 | 中（越界风险）|
| **P2** | Chart-type layout rules → 按需加载 | ~800/次 | 中 | 低 |
| P3 | OUTPUT CONTRACT 压缩 | 待评估 | 中 | 低 |
| — | REASONING PROTOCOL | — | — | 保持现状 |
| — | DO / DON'T | — | — | 保持现状 |

### P0：PALETTE CATALOG 迁移

**改动：**
1. 新建 `system_prompt/palette_catalog.md`，内容 = 当前 PALETTE CATALOG section
2. `domain_knowledge_loader.py` 新增 `get_palette_catalog()` 加载函数
3. `skill_loader.py` 的 `_load_base_system_prompt()` 拼接 palette catalog
4. Styling task prompt 删除 PALETTE CATALOG section

**预期效果：**
- Styling task prompt: 5652 → 2662 tokens（**-53%**）
- Pipeline 总全价 tokens: 19890 → 16900（**-15%**）
- System prompt: 2598 → ~5588 tokens

**风险：**
- Structure 和 Layout 也会看到 palette catalog（冗余），但在缓存前缀里，成本很低
- 不会影响输出质量（多看一些颜色参考对 Structure/Layout 无害）

### P1：DIAGNOSTIC FRAMEWORKS 迁移

**改动：**
1. 将 PHASE 2 和 PHASE 3 DIAGNOSTIC FRAMEWORK 内容移到 `system_prompt/diagnostic_frameworks.md`
2. `skill_loader.py` 拼接到 system prompt
3. Styling 和 Layout 的 task prompt 删除对应 section

**预期效果：**
- Styling task: 2662 → 2252 tokens（再省 410）
- Layout task: 5226 → 4684 tokens（省 542）
- System prompt: 5588 → ~6540 tokens

**风险：**
- Structure agent 会看到 Phase 2/3 的方法论，可能产生"越界"（Structure 开始考虑视觉/布局问题）
- 需要测试验证 Structure 输出质量不受影响

### P2：Chart-Type Layout Rules 按需加载

**改动：**
1. 将 5 种 chart-type 的布局规则提取到 `system_prompt/chart_type_layout_rules.json`
2. `load_skill_system_prompt(diagram_type)` 按 chart_type 注入对应规则
3. Layout 的 CURRENT TASK 删除这些规则

**预期效果：**
- Layout CURRENT TASK: 1535 → ~735 tokens（省 800）
- System prompt 按需加载，只注入匹配的规则

**风险：**
- Layout agent 需要从 system prompt 而非 task prompt 获取这些规则，行为可能略有变化
- 需要确保 `diagram_type` 在 Layout 调用时已知（来自 Structure 的输出）

## 5. 不动的部分

| Section | 原因 |
|---------|------|
| REASONING PROTOCOL | 每个 stage 完全不同，是 stage 专属指令 |
| OUTPUT CONTRACT | 每个 stage 的 schema 不同，是 stage 专属指令 |
| DO / DON'T | 每个 stage 的规则不同，是 stage 专属指令 |
| CURRENT TASK（除 layout rules） | 任务描述，stage 专属 |
| REMINDER | 检查清单，stage 专属 |

## 6. 效果汇总

### 优化前 vs 优化后（P0 + P1 + P2 全部实施）

| | 优化前 | 优化后 | 变化 |
|--|--------|--------|------|
| System prompt | 2598 | ~6540 | +3942 |
| Structure task | 3514 | 3514 | 不变 |
| Styling task | 5652 | 2252 | **-3400 (-60%)** |
| Layout task | 5226 | 3884 | **-1342 (-26%)** |
| **Task prompt 总计** | **14392** | **9650** | **-4742 (-33%)** |
| Pipeline 总输入 | 25886 | 25086 | -800 |
| Pipeline 总全价 | 19890 | 15148 | **-4742 (-24%)** |

### 仅实施 P0（PALETTE CATALOG）

| | 优化前 | 优化后 | 变化 |
|--|--------|--------|------|
| Styling task | 5652 | 2662 | **-2990 (-53%)** |
| Pipeline 总全价 | 19890 | 16900 | **-2990 (-15%)** |

P0 是投入产出比最高的优化：改动小、风险低、收益大。

## 7. 已实施的优化（2026-05-05）

> **状态**: ✅ P0 + P2 + Router 已实施

### 实施内容

| 优化项 | 状态 | 方式 |
|--------|------|------|
| P0: PALETTE CATALOG | ✅ 已实施 | 动态加载：Router 选定 palette → `get_selected_palette()` → `{{selected_palette}}` |
| P2: Chart-type layout rules | ✅ 已实施 | 动态加载：Router 选定 diagram_type → `get_chart_type_layout_rules()` → `{{chart_type_layout_rules}}` |
| Router 预分类 | ✅ 已实施 | 独立 RouterAgent（~1000 tokens system prompt），使用 `router` role（cheap model） |
| P1: DIAGNOSTIC FRAMEWORKS | ❌ 未实施 | 有越界风险（Structure 看到 Phase 2/3 方法论） |

### 实际效果

| | 优化前 | 实际优化后 | 变化 |
|--|--------|----------|------|
| Router | 0 | ~1000-1500（cheap model） | +1000-1500 |
| System prompt | 2596 | 2596 | 不变 |
| Structure task | 3514 | 3514 | 不变 |
| Styling task | 5652 | ~3131 | **-2521 (-45%)** |
| Layout task | 5226 | ~4215-4702 | **-524~-1011 (-10-19%)** |
| **Task prompt 总计** | **14392** | **~10860-11347** | **-3045~-3532 (-21-25%)** |

### Token 节省明细

- **Styling**: PALETTE CATALOG（2990 tokens，12 个 palette 全量）→ 单个 palette card（~117 tokens）= **-2873 tokens**
- **Layout**: 6 种 chart-type rules 内联（~1090 tokens）→ 按需加载 1 种（~200-500 tokens）= **-590~-890 tokens**
- **Router**: 新增 ~1000-1500 tokens，但使用 cheap model（~1/10 价格）

### 实现文件

| 文件 | 改动 |
|------|------|
| `generation_stage/router/` | 新建：RouterAgent + prompts |
| `system_prompt/chart_type_layout_rules.json` | 新建：提取的 chart-type layout rules |
| `generation_stage/workflow.py` | 修改：Router 调用 + 动态加载 |
| `generation_stage/styling/prompts.py` | 修改：`{{selected_palette}}` 替代 PALETTE CATALOG |
| `generation_stage/layout/prompts.py` | 修改：`{{chart_type_layout_rules}}` 替代内联 rules |
| `common/domain_knowledge_loader.py` | 修改：新增 `get_selected_palette()` + `get_chart_type_layout_rules()` |
| `configs/settings.yaml` | 修改：新增 `router` role |
