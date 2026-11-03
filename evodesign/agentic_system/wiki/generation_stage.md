# Generation Stage（生成阶段）

核心流水线，将文本转换为带位置信息的图表。默认 `multiagent` 模式共 3 次 LLM 调用；`oneshot` 是 Excalidraw-only 的实验/消融路径。

## 流水线

```
文本 → StructureAgent → StylingAgent → LayoutAgent → RenderWorkflow → PNG
       (元素结构)          (视觉样式)     (位置尺寸)      (无 LLM)
```

## 子模块

### Structure（结构提取）— `generation_stage/structure/`

**目标**：从非结构化文本中提取元素结构。

- `structure_agent.py` — One-shot Agent：文本 → ElementStructure（chart_type、nodes、edges、groups）
- `prompts.py` — 系统提示词和任务提示词
- `schemas.py` — Pydantic 模型：`GraphNode`、`GraphEdge`、`GraphGroup`、`ElementStructure`
- `state.py` — `StructureWorkflowState`
- `workflow.py` — LangGraph 工作流（单 Agent 节点）
- `tools/` — 结构处理辅助工具

输出：`structure_instantiation.json`，包含 chart_type、nodes（id, label, type）、edges（source, target, relation）、groups（members, group_member_relation）。

### Styling（样式分配）— `generation_stage/styling/`

**目标**：为语义元素分配视觉样式和图标。

- `styling_agent.py` — One-shot Agent：ElementStructure → StylingInstantiation（颜色、形状、填充、字体、图标）
- `colorful.py` — 调色板生成
- `prompts.py` — 系统提示词和任务提示词（按 canvas_library 注入 Excalidraw/TLDraw contract）
- `state.py` — `StylingWorkflowState`
- `workflow.py` — LangGraph 工作流（Agent + 图标 URL 添加节点）

输出：`styling_instantiation.json`，将元素 ID 映射到视觉属性（color, fill, stroke, font, icon）。

### Layout（布局计算）— `generation_stage/layout/`

**目标**：计算元素的空间位置和尺寸。

- `layout_agent.py` — One-shot Agent：ElementStructure + StylingInstantiation → LayoutInstantiation
- `element_shape_estimator.py` — 基于文本内容估算节点的 min_width / min_height
- `prompts.py` — Layout 任务提示词（使用 canvas_runtime 的当前 viewport 常量）
- `state.py` — `LayoutWorkflowState`
- `workflow.py` — LangGraph 工作流：estimate_sizes → LLM

Layout 阶段不再运行 Dagre baseline prepass。结构和样式阶段的
conversation context 加上 `element_shape_estimator.py` 生成的尺寸提示，直接交给
Layout LLM 生成坐标；后续由 render/verification/refinement 阶段做确定性检查和修复。

输出：`layout_instantiation.json`，将元素 ID 映射到 {x, y, width, height}。

### Oneshot（一站式生成）— `generation_stage/unified/`

**目标**：单次调用完成端到端生成（替代三阶段流水线的方案），同时携带
Structure-shaped semantic sidecar，供 verification 复用结构感知检查。

当前限制：oneshot 只支持 Excalidraw manifest，不支持 TLDraw，也不会运行 iterative refiner。

- `generator.py` — 单个 Agent 合并 structure + styling + layout，并输出 Excalidraw manifest + `_meta.structure_instantiation`
- `state.py` — `UnifiedWorkflowState`
- `workflow.py` — LangGraph：generate_scene → normalize_scene → validate_scene

## 顶层文件

- `generation_stage/workflow.py` — 串联 Structure → Styling → Layout 工作流，在各阶段间传递状态。

## 能力矩阵

| Canvas / Mode | Multiagent generation | Oneshot generation | Iterative refiner |
|---------------|-----------------------|--------------------|-------------------|
| Excalidraw | 支持 | 支持 | 支持，仅 non-oneshot |
| TLDraw | 支持 | 不支持 | 不支持 |

后端 streaming 当前只使用 multiagent 分阶段 API：`structure -> styling -> layout`，随后由 render stage 生成 manifest/PNG。
