# 版本差异分析：Dev vs GitHub Baseline

## 测试结果对比

| 指标 | Dev (本地) | Baseline (GitHub) |
|------|-----------|------------------|
| 成功率 | 2/5 | 5/5 |
| 边交叉 | 0 (未渲染) | 多处交叉 |
| 布局质量 | Example 119 可用，140 压缩 | 全部清晰可读 |
| Icon | 有 (use_icons) | 无 |

## 关键差异清单

### 1. Dagre 基线注入（最大影响）

**问题**：Dev 版本 dagre prepass 成功运行，注入 baseline block 给 LLM。Baseline 版本 dagre 失败（`layout-cli.ts not found`），LLM 收到空的 baseline block。

**日志证据**：
- Dev: `dagre baseline computed for 13 nodes`
- Baseline: `layout-cli.ts not found; returning empty baseline`

**影响**：LLM 被 baseline block 干扰，返回非 JSON 输出（3/5 失败），或布局质量下降。Baseline 版本的 LLM 完全自主布局，反而效果更好。

**根因**：baseline block 里的 rank/order 信息增加了 prompt 复杂度，LLM 在处理大量额外约束时容易输出格式错误。

### 2. System Prompt 来源不同

| | Dev | Baseline |
|---|---|---|
| 来源 | 单文件 `evodiagram_prompt.md` | 多文件拼接：`SKILL.md` + `thinking-methodology.md` + `best-practices.md` |
| 大小 | 较大（包含所有知识） | 较小（模块化拼接） |
| 通用模式 | 内嵌 | 从 `diagram-patterns.md` 追加 |

**影响**：prompt 内容和结构不同，可能导致 LLM 的输出风格和质量差异。需要对比两个 prompt 的具体内容。

### 3. Assistant Content 格式

| | Dev | Baseline |
|---|---|---|
| 格式 | `build_assistant_content()` — 人类可读 spec + JSON | 纯 `json.dumps()` |

**影响**：Dev 的 conversation history 包含更多人类可读文本，增加了 token 数量和噪声。Baseline 的纯 JSON 更紧凑，LLM 更容易理解上下文。

### 4. 域知识注入方式

| | Dev | Baseline |
|---|---|---|
| Structure 阶段 | 仅 `diagram_type_knowledge_base.json` | 追加 group/containment reference |
| Styling 阶段 | 仅知识库 | 追加 color knowledge |
| Layout 阶段 | 仅知识库 + router 的 chart_type_layout_rules | 追加 Excalidraw element reference |

**影响**：Baseline 在每个阶段注入了更丰富的领域知识（element-ref, color-knowledge, group-containment），LLM 有更好的参考。Dev 依赖 router 动态加载，但 router 可能没有正确传递所有知识。

### 5. Label 处理策略

| | Dev | Baseline |
|---|---|---|
| 策略 | `_strip_labels_from_styling()` — 从 styling 中删除 label | `_inject_labels_from_structure()` — 从 structure 注入 label 到 styling |
| 哲学 | label 归 structure 所有，renderer 从 structure 查找 | renderer 需要 label 在 styling JSON 中 |

**影响**：如果 renderer 依赖 styling 中的 label，Dev 版本会导致 group title 为空（日志中确实看到了 `empty title text` 警告）。

### 6. Router Agent（Dev 独有）

Dev 版本在 pipeline 前运行 RouterAgent，预分类 diagram_type 和 palette。Baseline 没有 router。

**影响**：
- 增加一次 LLM 调用（延迟 + 成本）
- Router 分类结果影响后续所有阶段的 domain knowledge
- Router 可能误分类，导致下游使用错误的知识

### 7. Layout Prompt 修改（今天改的）

| | Dev (改后) | Baseline |
|---|---|---|
| Baseline block | 软提示："HOW TO USE THIS BASELINE" | 硬规则："HARD RULES — a post-layout audit silently reverts any violation" |
| Q5 | "respect rank ordering, group containment overrides baseline y" | "rank/order contract is authoritative, your node y values must cluster per rank" |
| Reasoning (a) | "use rank/order as reference, group containment priority" | "rank/order contract is authoritative" |

**影响**：今天的改动把 baseline 从硬规则改为软提示。但 baseline 版本的硬规则反而配合 dagre 失败（无 baseline block）工作得很好。当 baseline block 存在时，软提示可能不如硬规则清晰。

## 最可能的根因排序

### 高影响

1. **Dagre baseline block 干扰 LLM** — 这是 3/5 失败的直接原因。Baseline 版本 dagre 失败，LLM 没有被干扰。
2. **System prompt 内容不同** — 两个版本的 prompt 内容差异很大，直接影响 LLM 的输出质量。

### 中影响

3. **Assistant content 格式** — 纯 JSON vs 人类可读格式，影响 conversation history 的 token 效率。
4. **域知识注入** — Baseline 注入了更丰富的阶段特定知识。
5. **Label 处理** — Dev 的 strip 策略导致 group title 为空。

### 低影响

6. **Router agent** — 增加延迟但不直接影响布局质量。
7. **Config 系统差异** — 纯工程差异，不影响 LLM 输出。

## 建议修复方向

1. **移除 dagre baseline block 注入**（或让 dagre 失败时不注入任何内容）— 让 LLM 自主布局
2. **对齐 system prompt** — 使用 baseline 的多文件拼接方式
3. **对齐 assistant content 格式** — 使用纯 JSON
4. **恢复 label 注入策略** — 从 structure 注入 label 到 styling
5. **检查域知识注入** — 确保每个阶段有完整的领域知识
