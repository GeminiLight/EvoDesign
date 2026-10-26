# Refinement Stage（优化阶段）

迭代式 verify → fix → render 编排器。Verification、Refinement、Rendering 是独立阶段，由 `IterativeRefinerWorkflow` 组合成循环。

## 架构

```
IterativeRefinerWorkflow（编排器）
  │
  ├─ load_inputs（加载 manifest / structure / verifier report）
  │
  ├─ run_iteration（循环，最多 max_iterations 轮）
  │   ├─ 1. Verify  → verification_stage.checks.run_all_checks()（纯规则，无 LLM）
  │   ├─ 2. Fix     → deterministic fixers + LLM agent（生成 EditOps）
  │   ├─ 3. Apply   → apply_edits()（将 EditOps 应用到 manifest）
  │   ├─ 4. Verify  → run_all_checks()（post-fix，用于 convergence 和下一轮 LLM 输入）
  │   └─ 5. Render  → canvas_environment.render_png_result()（重新生成 PNG，供下一轮 VLM 使用）
  │
  └─ finalize（输出 refined manifest + PNG + report）
```

三个阶段各自独立：
- **verification_stage** — `run_all_checks()` 返回 findings，不关心谁调用
- **refinement_stage/agent + fixers** — 纯 fix 逻辑，输入 findings + manifest，输出 edits
- **canvas_environment** — `render_png_result()` 输入 manifest，输出 PNG；底层渲染实现适配仍在 render_engine 后方。

通过 `--enable-refiner` 启用。默认 1 轮迭代，可通过 `--refiner-iterations` 配置。

## 文件列表

| 文件 | 用途 |
|------|------|
| `../iterative_workflow.py` | `IterativeRefinerWorkflow` — 编排器（verify→fix→render 循环），位于 `agentic_system/`。加载 manifest 后先调用 `patch_schema_defaults()` 预处理，再进入迭代循环。 |
| `state.py` | `VerifierRefinerState`、`EditOp`、`IterationLog` 模型 |
| `__main__.py` | CLI 入口 |

### Agent（智能体）— `agent/`

| 文件 | 用途 |
|------|------|
| `llm_agent.py` | `RefinerLLMAgent` — 根据检查结果 + 图片分析生成 EditOps |
| `prompts.py` | LLM 编辑生成的提示词模板 |

VLM 客户端通过 `core.LLMFactory.create_for_role("refiner")` 创建。

### Fixers（修复器）— `fixers/`

| 文件 | 用途 |
|------|------|
| `deterministic.py` | 基于规则的修复：碰撞解决、包含纠正、溢出处理。`patch_schema_defaults()` 作为预处理步骤单独调用，不走 EditOp 审计管线。 |
| `apply_edits.py` | 将确定性和 LLM 生成的 EditOps 应用到 manifest |
| `primitives.py` | 编辑操作原语。`op_delete_element` 会清理被删元素上的箭头绑定（startBinding/endBinding）。 |

### EditOps DSL

10 种 manifest 修改操作：

| 操作 | 用途 |
|------|------|
| `set_position` | 移动元素到 (x, y) |
| `set_size` | 修改宽度/高度 |
| `set_style` | 修改视觉属性 |
| `set_text` | 修改元素标签 |
| `delete_element` | 删除元素 |
| `clear_arrow_binding` | 断开箭头端点 |
| `clear_container_binding` | 断开文本与容器的绑定 |
| `append_bound_element` | 连接箭头到元素 |
| `remove_bound_element` | 从元素的 `boundElements` 删除指定绑定 |
| `set_index` | 修改 z 序 |

### Reports（报告）— `reports/`

- `refiner_report.py` — 组装 `refiner_report.json`，包含迭代日志、最终 findings、编辑历史

## 与 Verification Stage 的关系

| Verification 输出 | Refinement 用途 |
|---|---|
| objective findings | deterministic fixers 的触发信号 |
| VLM critique | LLM agent 生成 EditOps 的上下文 |

Refinement 由 `--enable-refiner` 允许，但主流水线不会无条件执行：`verification_only`、`oneshot` 模式或 verification blocking errors 都会跳过 refinement。没有 blocking errors 时，verification 提供报告和上下文，objective findings / VLM critique 会进入 fixers 和 LLM prompt。

每次迭代中：
1. **Verify** → 产出 findings（迭代开始时）
2. **Fix** → deterministic + LLM 基于 findings 生成 EditOps
3. **Verify** → 重新检查（迭代结束时，用于 convergence 判断和下一轮 LLM 输入）

## Convergence（收敛条件）

迭代在以下任一条件满足时停止：
1. **无编辑产出** — deterministic 和 LLM 都没有新的 EditOps → fixed point
2. **严重问题清零** — `critical + major` findings 必须为 0
3. **达到最大迭代次数** — `current_iteration >= max_iterations`

## 独立使用

```bash
python -m evo_diagram.agentic_system.refinement_stage \
    --manifest path/to/diagram_manifest.json \
    --image    path/to/rendered_diagram.png \
    [--structure path/to/structure_instantiation.json] \
    [--layout path/to/layout_instantiation.json] \
    [--verifier-report path/to/verifier_report.json] \
    [--output-dir path] \
    [--max-iterations 3] \
    [--no-rerender] \
    [--markdown] \
    [--verbose]
```

独立运行当前产物时，建议同时传入 `3_layout/layout_instantiation.json`。否则 `layout_audit` 无法读取 layout 输入，会产生 missing-layout finding，影响收敛判断。

## 与 Knowledge Evolution 的集成

`knowledge_evolution/refine.py` 模块直接使用 `IterativeRefinerWorkflow` 进行优化步骤。
