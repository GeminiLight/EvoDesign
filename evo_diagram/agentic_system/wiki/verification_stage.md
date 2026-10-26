# Verification Stage（验证阶段）

可选的质量验证阶段，结合客观规则检查与 VLM 主观评判。在渲染完成后运行，产出质量报告，并为主流水线提供质量门控信号。客观 findings 中的 `critical` / `major` 和 blocking input/runtime errors 会使 `quality_passed=false`；主观 critic 失败、报告写入失败等 nonblocking errors 只作为 warnings 记录，不阻断质量通过。

## 流水线

```
Manifest + PNG + 结构 + 源文本
    → load_inputs（加载 manifest / structure / layout JSON）
    → run_objective_checks（纯 Python，无 LLM，8 项检查）
    → run_subjective_critic（1 次 VLM 调用，可用 --no-critic 跳过）
    → build_report → verifier_report.json + .md
```

通过 `--enable-verifier` 启用。输出到 `{save_dir}/6_verification/`。

## 与主流水线的集成

Verification 嵌入在 `workflow.py` 的 Phase 3，位于 Render 之后、Refinement 之前：

```
Phase 1: Generate（Structure → Styling → Layout）
Phase 2: Render（manifest JSON → PNG）
Phase 3: Verify ← 本阶段（报告 + blocking quality gate）
Phase 4: Refine（需 --enable-refiner，且非 verification_only / 非 oneshot / 无 blocking verification errors）
Phase 5: Finalize
```

Verification 产出的 findings 和 critique 作为 Refinement 的输入上下文（告诉 refiner 哪里有问题、怎么改）。注意区分三层语义：
- core Python pipeline 中，objective findings 不直接打开/关闭 refiner，而是作为修复输入和质量统计；
- backend streaming pipeline 在 `always_refine=false` 时会用 blocking findings 或低 critic 分数决定是否触发 refiner；
- blocking input/runtime errors 会让主流程跳过 refinement；
- 独立 verifier CLI 会根据 `quality_passed` 返回退出码，warnings 不导致失败。

主流水线传入：
- `manifest_path`：渲染后的 Excalidraw manifest
- `image_path`：渲染后的 PNG
- `structure_path`：结构化输出（用于 chart_type 感知检查和显式 group 成员映射）
- `source_text`：原始输入文本（传给 VLM critic 做上下文感知评估）

主流水线相关 CLI 参数：
- `--no-verifier`：跳过验证阶段
- `--no-critic`：跳过 VLM 主观评判（仅运行客观检查）
- `--verification-only`：仅运行验证，不执行 refinement

## 文件列表

| 文件 | 用途 |
|------|------|
| `workflow.py` | 4 节点 LangGraph 工作流 |
| `state.py` | `VerifierState`、`Critique`、`DimensionCritique` 模型 |
| `__main__.py` | CLI 入口 |

### 核心数据模型 — `state.py`

**VerifierState** — 工作流状态，跨 4 个节点共享：
- 输入：`manifest_path`、`image_path`、`structure_path`、`layout_path`、`source_text`
- 控制：`skip_critic`、`emit_markdown`
- 输出：`objective_findings`、`objective_summary`、`critique`、`report`
- 状态机：`init → loaded → checked → critiqued → reported`（或 `reported_with_findings` / `reported_with_warnings` / `reported_with_errors` / `failed`）
- error 分类：`blocking_errors` 会使质量门控失败；`nonblocking_errors` 进入报告 warnings。

**Critique** — VLM 主观评判结果：
- 三个维度（`DimensionCritique`）：`structure`、`styling`、`layout`
- 每个维度：`score`（0-10）、`strengths`、`weaknesses`、`suggestions`
- 汇总：`overall_score`、`summary`

### Finding 模型 — `checks/finding.py`

所有客观检查的通用数据结构，是 checks 层的 lingua franca：

```python
class Severity(str, Enum):
    CRITICAL = "critical"   # 渲染损坏（schema 无效、必填字段缺失）
    MAJOR    = "major"      # 视觉缺陷（重叠、错误包含、缺失箭头）
    MINOR    = "minor"      # 质量瑕疵（画布溢出、冗余元素）
    INFO     = "info"       # 观察性信息（边交叉等）

class Finding(BaseModel):
    category: str           # 检查类别（如 "collision/node_overlap"）
    severity: Severity
    message: str
    element_id: Optional[str]   # 关联的 Excalidraw 元素 ID
    location: Optional[Dict]    # 坐标 / bbox 信息
```

`summarize_findings(findings)` → 按严重度统计的直方图（`{critical: N, major: N, ...}`）。

### Checks（检查模块）— `checks/`

| 模块 | 函数 | 检查项 | 严重度 |
|------|------|--------|--------|
| `render_validation.py` | `check_schema()` | manifest 结构完整性 | CRITICAL / MINOR |
| `render_validation.py` | `check_render_audit()` | 渲染阶段遗留问题（空文本、箭头覆盖、z-order、对比度） | MAJOR |
| `render_validation.py` | `check_layout_audit()` | 布局阶段遗留问题（空标题、边分类、重复 ID） | MAJOR |
| `binding_consistency.py` | `check_arrow_shape_binding()` | 箭头 ↔ 形状双向绑定一致性 | CRITICAL / MAJOR |
| `containment.py` | `check_group_bbox_contains_children()` | 组框是否完全包含子节点（优先使用 `structure.groups[].members` 显式映射，回退到质心推断） | MAJOR |
| `containment.py` | `check_swimlane_lane_membership()` | 泳道成员归属（仅 swimlane 类型，同样支持显式映射） | MAJOR |
| `collision_detection.py` | `check_node_overlap()` | 元素之间是否存在重叠 | MAJOR |
| `collision_detection.py` | `check_edge_crossings()` | 连接线是否不必要地交叉 | INFO / MINOR |
| `collision_detection.py` | `check_out_of_canvas()` | 元素是否超出画布边界 | MINOR |
| `aggregator.py` | `run_all_checks()` | 聚合所有检查结果 | — |

检查执行顺序：schema → audit → layout audit → binding → containment → collisions。

可通过 `--skip-checks` 跳过特定检查类别（逗号分隔），可用类别：`schema`、`render_audit`、`layout_audit`、`binding`、`containment/group_bbox`、`containment/swimlane_lane`、`collision/node_overlap`、`collision/edge_crossing`、`collision/out_of_canvas`。

**注意**：containment 检查优先使用 `structure.groups[].members` 提供的显式成员映射；当结构数据不可用时回退到质心推断。

### Critic（主观评判）— `critic/`

| 文件 | 用途 |
|------|------|
| `critic_agent.py` | `VerifierCriticAgent` — 单次 VLM 调用，返回 `Critique` |
| `prompts.py` | 系统提示词 + `build_user_prompt()` |

**评分维度**（各 0-10 分）：
- **Structure**：实体覆盖、关系正确性、chart_type 适配、冗余检测
- **Styling**：颜色对比、形状语义、字体可读性、图标含义
- **Layout**：对齐、间距、画布利用、边路由、类型特定几何

**VLM 调用流程**：
1. 读取 PNG → base64 编码
2. 构建多模态消息（系统提示 + 图片 + 元数据文本）
3. 调用 VLM → 解析 JSON（支持直接解析、fenced block、最大平衡对象三种策略）
4. 校验并 clamp 分数 → 返回 `Critique`

元数据包括 `chart_type`、`source_text`（原始输入，截断到 1500 字符）、`objective_summary`（客观检查统计）。

### Reports（报告）— `reports/`

- `report_builder.py` — 组装 `verifier_report.json`（结构化）和 `verifier_report.md`（可读）

报告结构：
```json
{
  "manifest_path": "...",
  "image_path": "...",
  "objective": {
    "summary": {"critical": 0, "major": 2, "minor": 1, "info": 0, "total": 3},
    "findings": [...]
  },
  "subjective": {
    "structure": {"score": 7.5, "strengths": [...], ...},
    "styling": {...},
    "layout": {...},
    "overall_score": 7.2,
    "summary": "..."
  },
  "metadata": {
    "timestamp": "...",
    "vlm_model": "...",
    "skip_critic": false,
    "status": "reported",
    "errors": [],
    "blocking_errors": [],
    "nonblocking_errors": []
  }
}
```

## 独立使用

```bash
python -m evo_diagram.agentic_system.verification_stage \
    --manifest path/to/diagram_manifest.json \
    --image    path/to/rendered_diagram.png \
    [--canvas-library excalidraw|tldraw] \
    [--structure path/to/structure_instantiation.json] \
    [--layout path/to/layout_instantiation.json] \
    [--source-text "original input text"] \
    [--output-dir path] \
    [--no-critic] \
    [--skip-checks "schema,collision/edge_crossing"] \
    [--markdown] \
    [--verbose]
```

## 与 Refinement Stage 的关系

Verification 产出的 findings 和 critique 是 Refinement 的输入上下文：

| Verification 输出 | Refinement 用途 |
|---|---|
| objective findings | deterministic fixers（碰撞解决、包含纠正、溢出处理）的触发信号 |
| VLM critique | LLM agent 生成 EditOps 的上下文 |

Refinement 由 `--enable-refiner` 允许，但不会无条件执行：`--verification-only`、`oneshot` 模式或 verification blocking errors 都会跳过 refinement。没有 blocking errors 时，verification 的 findings / critique 会成为 refiner 输入。

Refinement 的每次迭代也会重新运行 verification（verify → fix → re-render → re-verify），形成闭环。
