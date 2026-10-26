# System Prompt 拆分分析

> **最后更新**: 2026-05-05，反映 Router + 动态加载实现后的状态。

## 1. 现状

### 1.1 System Prompt 来源

三个 agent（Structure、Styling、Layout）共用同一个 system prompt，由两部分拼接而成：

| 来源文件 | 内容 | 大小 |
|---------|------|------|
| `system_prompt/evodiagram_prompt.md` | Pipeline Contract、Anti-Drift Rules、Critical Rules、Diagram Types | ~8.5KB (~2128 tokens) |
| `system_prompt/diagram-patterns.md`（universal 部分）| Common Professional Patterns、Quick Reference | ~1.8KB (~456 tokens) |
| **合计** | | **~10.4KB (~2596 tokens)** |

加载逻辑：`skill_loader.py` → `_load_base_system_prompt()` 拼接两个文件 → `EVODIAGRAM_SKILL_SYSTEM_PROMPT` 常量。

另外，每个 agent 可通过 `load_skill_system_prompt(diagram_type)` 动态加载 type-specific knowledge（~200-854 tokens），拼接到 system prompt 末尾。

### 1.2 Task Prompt 大小（Router 实现后）

| Agent | System Prompt | Task Prompt | 总 prompt | 变化 |
|-------|-------------|------------|----------|------|
| **Router** | ~1000 tokens（独立小 prompt） | ~100-500 tokens | ~1100-1500 | 新增 |
| Structure | ~2596 tokens | ~3514 tokens | ~6110 | 不变 |
| Styling | ~2596 tokens | ~3131 tokens | ~5727 | **-2521 (45%)** |
| Layout | ~2596 tokens | ~4215-4702 tokens | ~6811-7298 | **-524~-1011 (10-19%)** |

**关键变化：**
- Styling task prompt 从 5652 → 3131 tokens：PALETTE CATALOG（2990 tokens）被替换为单个 palette card（~117 tokens）
- Layout task prompt 从 5226 → 4215-4702 tokens：6 种 chart-type layout rules 被替换为按需加载的 1 种
- 新增 Router agent：~1000 tokens system prompt + ~100-500 tokens task prompt，使用 cheap model

### 1.3 System Prompt 章节详情

| # | 章节 | 字符数 | ~tokens | 内容 |
|---|------|--------|---------|------|
| 1 | EvoDesign System Prompt (title) | 252 | 63 | 角色定义 |
| 2 | Pipeline Contract | 678 | 169 | 3-stage 流程描述 |
| 3 | Anti-Drift Rules | 4821 | 1205 | 6 条规则（Type-First、Zero-Bloat、Identity、Container、Recognition、Stage Boundary）|
| 4 | Critical Rules | 1501 | 375 | Binding Consistency、Unique IDs、Group Pattern、Default Styling |
| 5 | Supported Diagram Types | 1310 | 327 | 10 种图表类型的描述 |
| 6 | Common Professional Patterns | 1215 | 303 | Styling Rules、Visual Hierarchy、Arrow Conventions、Color Combos |
| 7 | Quick Reference: Diagram Types | 609 | 152 | 图表类型速查表 |

## 2. Router 实现后的架构

### 2.1 动态加载机制

Router 在 pipeline 之前运行，输出 `diagram_type` + `palette_name`，驱动三种动态加载：

| 加载内容 | 来源 | 目标 agent | 节省 |
|---------|------|-----------|------|
| 单个 palette card | `domain_knowledge_loader.get_selected_palette()` | Styling | -2521 tokens/次 |
| chart-type layout rules | `domain_knowledge_loader.get_chart_type_layout_rules()` | Layout | -524~-1011 tokens/次 |
| type-specific knowledge | `skill_loader.load_skill_system_prompt(diagram_type)` | 所有 agent | 已有机制 |

### 2.2 Token 流向

```
Router (独立小 prompt ~1000 tokens, cheap model, 不加载 type knowledge)
  │
  ├─ diagram_type ──→ 传给 Structure/Styling/Layout 的 state ──→ 它们的 system prompt 通过
  │                   load_skill_system_prompt(diagram_type) 增强（已有机制）
  ├─ palette_name ──→ get_selected_palette(name) ──→ StylingState.selected_palette ──→ Styling task {{selected_palette}}
  └─ diagram_type ──→ get_chart_type_layout_rules(type) ──→ LayoutState.chart_type_layout_rules ──→ Layout task {{chart_type_layout_rules}}
```

### 2.3 Router Prompt 结构

Router 使用独立的小型 system prompt（~1000 tokens），不使用主 pipeline 的 EvoDesign system prompt：

| 内容 | Tokens | 说明 |
|------|--------|------|
| Diagram type descriptions（22 种，含描述） | ~400 | "What it shows" + "Best for" |
| Palette routing table（12 种，含 mood） | ~200 | topic → palette 映射 |
| Override rules | ~50 | 用户指定时必须遵守 |
| Selection goal | ~50 | "best fit + most aesthetically coherent" |
| 输出格式 | ~100 | JSON schema |
| **合计** | **~800** | |

## 3. 问题分析

### 3.1 冗余内容

每个 agent 都为整个 system prompt 买单，但并非所有内容都对每个 agent 有用：

| 章节 | Structure | Styling | Layout |
|------|-----------|---------|--------|
| Pipeline Contract | 需要 | 需要 | 需要 |
| Anti-Drift Rules | 需要 | 需要 | 需要 |
| Critical Rules | 需要 | 需要 | 需要 |
| Supported Diagram Types | 需要 | 部分需要 | 部分需要 |
| Common Professional Patterns | **不需要** | **核心需要** | 部分需要 |
| Quick Reference | 部分需要 | 需要 | 部分需要 |

**主要冗余：** Common Professional Patterns（303 tokens）对 Structure 完全无用。Visual Hierarchy、Color Combinations 主要是 Styling 的知识。

### 3.2 缓存影响

当前三个 agent 共用同一个 system prompt，意味着：

- Structure 调用时，system prompt 首次写入缓存（~2596 tokens）
- Styling 调用时，system prompt 命中缓存（前缀匹配）
- Layout 调用时，system prompt 命中缓存

**如果拆分成不同内容，缓存命中率会下降。** 这是拆分的核心 tradeoff。

### 3.3 缓存成本量化

假设使用 OpenAI 定价（cached tokens 价格为 regular 的 10%）：

| 方案 | Structure 首次 | Styling 缓存命中 | Layout 缓存命中 |
|------|-------------|----------------|----------------|
| 当前（共用）| 2596 tokens (full price) | 2596 tokens (cached) | 2596 tokens (cached) |
| 拆分后 | shared ~1800 (full) + 专属 ~800 (full) | shared ~1800 (cached) + 专属 ~800 (full) | shared ~1800 (cached) + 专属 ~800 (full) |

拆分后，每个 agent 的"专属部分"（~800 tokens）每次都要 full price，因为三个 agent 的专属部分内容不同，无法命中前缀缓存。

**净效果：** 每次 pipeline 运行多花 ~800 tokens × 2 agents = ~1600 tokens 的 full-price 成本，但每个 agent 的 prompt 更精准。

## 4. 拆分方案

### 方案 A：不拆分（当前状态 + Router 动态加载）

- 优点：缓存命中率最高，实现简单，Router 已大幅减少 task prompt
- 缺点：每个 agent 有 ~300 tokens 冗余

**当前已实施的优化：**
- ✅ PALETTE CATALOG 从 Styling task prompt 移除（-2521 tokens）
- ✅ Chart-type layout rules 从 Layout task prompt 移除（-524~-1011 tokens）
- ✅ Router 预分类 diagram_type + palette_name（cheap model）
- ✅ Type-specific knowledge 通过 `load_skill_system_prompt(diagram_type)` 动态加载

### 方案 B：两层拆分（未来可选）

```
共享层 (~1800 tokens)：Pipeline Contract + Anti-Drift + Critical Rules + Diagram Types
Stage 专属层 (~800 tokens)：
  - Structure: （无额外内容，或加 Structure-specific rules）
  - Styling: Common Professional Patterns + Color Combos
  - Layout: Layout-specific rules（可从 task prompt 迁入）
```

- 优点：每个 agent 的 prompt 更精准，减少噪音
- 缺点：缓存命中率下降，需要改 skill_loader 和 agent 初始化逻辑

### 方案 C：从 task prompt 迁移内容到 system prompt

反向操作：把 task prompt 里通用的内容（如 Diagram Types 的详细描述）迁到 system prompt，减少 task prompt 的大小。

- 优点：task prompt 更精简，system prompt 的缓存价值更高
- 缺点：system prompt 变大

**Router 实现后，方案 C 的价值降低：** task prompt 已经通过动态加载大幅缩减，进一步优化的空间有限。

## 5. 拆分的影响分析

### 5.1 缓存成本

**当前 pipeline 一次运行的 prompt token 成本（含 Router）：**

| 调用 | 可缓存前缀 | 新增 tokens | 缓存节省 |
|------|----------|-----------|---------|
| Router | 0（独立调用） | ~1000-1500 | 0 |
| Structure | 2596 (system) | 3514 (task) + response | 0（首次）|
| Styling | 2596 + ~500 (system + struct resp) | 3131 (task) + response | ~2596 tokens |
| Layout | 2596 + ~500 + ~1500 (system + struct + style resp) | ~4500 (task) + response | ~4596 tokens |

**拆分后（方案 B）：**

| 调用 | 可缓存前缀 | 新增 tokens | 缓存节省 |
|------|----------|-----------|---------|
| Router | 0 | ~1000-1500 | 0 |
| Structure | 1800 (shared) | 800 (struct专属) + 3514 (task) | 0 |
| Styling | 1800 + ~500 (shared + struct resp) | 800 (style专属) + 3131 (task) | ~1800 tokens |
| Layout | 1800 + ~500 + ~1500 (shared + struct + style resp) | 800 (layout专属) + ~4500 (task) | ~3800 tokens |

**差异：** 每次 pipeline 运行，拆分后多花 ~1600 tokens full-price，少 ~800 tokens cached。实际成本差异很小（< $0.01 per pipeline run）。

### 5.2 输出质量

**风险：** 拆分后，如果某个 agent 缺少了它需要的知识，可能导致输出质量下降。

**评估：**
- Anti-Drift Rules（1205 tokens）是三个 agent 都需要的核心约束，必须在共享层
- Common Professional Patterns 里的 Color Combinations 只有 Styling 需要，但如果 Layout 看到了也不会有害
- 结论：拆分的质量风险很低，因为共享层已经包含了最关键的内容

### 5.3 实现复杂度

| 改动点 | 工作量 |
|--------|--------|
| `skill_loader.py` — 新增 `load_stage_system_prompt(stage)` | 中 |
| 三个 agent 的 `__init__` — 使用 stage-specific prompt | 小 |
| 测试验证 | 中 |
| **总计** | **中等** |

## 6. 建议

**短期（当前）：** 不拆分 system prompt。Router + 动态加载已经解决了 task prompt 膨胀的核心问题。~300 tokens 的冗余不值得为之牺牲缓存命中率。

**中期（如果 system prompt 继续膨胀）：** 当 system prompt 超过 4000 tokens 时，拆分变得有意义。可以实施方案 B。

**已完成的优化（效果汇总）：**

| 优化项 | 实施状态 | 节省 |
|--------|---------|------|
| PALETTE CATALOG → 动态加载 | ✅ 已实施 | Styling task -2521 tokens (45%) |
| Chart-type layout rules → 动态加载 | ✅ 已实施 | Layout task -524~-1011 tokens (10-19%) |
| Router 预分类 | ✅ 已实施 | 使用 cheap model，总 cost 降低 |
| DIAGNOSTIC FRAMEWORKS → system prompt | ❌ 未实施 | 可省 952 tokens，有越界风险 |
| System prompt 拆分 | ❌ 未实施 | 可省 ~1600 tokens full-price，缓存代价 |

**更有效的优化方向（未来）：**
1. 压缩 conversation_history 里的 instantiation JSON 格式
2. 把 `text_content` 从 task prompt 移到 conversation_history 的 user 消息（提升缓存命中率）
3. 评估 DIAGNOSTIC FRAMEWORKS 迁移到 system prompt（需测试 Structure 越界风险）
