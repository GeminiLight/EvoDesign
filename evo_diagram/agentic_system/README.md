> **EvoDesign public release:** use the [root README](../../README.md) and [configuration guide](../../docs/configuration.md) for current setup. Legacy module names below remain for compatibility.

# Text2Diagram Agentic System 文档

## 目录

- [概述](#概述)
- [系统架构](#系统架构)
- [核心工作流](#核心工作流)
- [Tool Services](#4-tool-services-nodejs-工具服务)
- [验证与优化工作流](#验证与优化工作流)
- [数据模型](#数据模型)
- [设计记忆系统](#设计记忆系统)
- [快速开始](#快速开始)
- [开发指南](#开发指南)
- [配置说明](#配置说明)
- [常见问题](#常见问题)

## 模块详细文档

| 模块 | 说明 |
|------|------|
| [概览](wiki/overview.md) | 系统总览、数据流、快速开始 |
| [common/](wiki/common.md) | 共享基础设施：BaseAgent、skill_loader、task_prompts |
| [generation_stage/](wiki/generation_stage.md) | 核心流水线：Structure、Styling、Layout、Oneshot |
| [verification_stage/](wiki/verification_stage.md) | 质量验证：客观检查 + VLM 主观评判 |
| [refinement_stage/](wiki/refinement_stage.md) | 迭代优化：确定性修复器 + LLM EditOps |
| [render_engine/](wiki/render_engine.md) | 渲染引擎：Excalidraw + TLDraw 管道 |
| [tool_services/](wiki/tool_services.md) | Node.js 工具服务：Playwright 渲染、图标服务、布局实验接口 |
| [system_prompt/](wiki/system_prompt.md) | 提示词知识库：设计模式、最佳实践、领域知识 |

---

## 概述

**Text2Diagram Agentic System** 是一个基于多智能体协作的自然语言到图表转换系统。该系统通过顺序化的工作流管道，将非结构化文本转换为高质量、可编辑的 canvas manifest（当前默认 Excalidraw；TLDraw 是受限/传统后端）和 PNG。

### 核心特性

- **多智能体协作**：使用 LangGraph 和 LangChain 构建的智能体工作流
- **分层设计**：结构、样式、布局、渲染四层解耦设计
- **设计记忆**：集成向量数据库，支持设计知识的检索与复用
- **视觉优化**：基于 VLM 的图表精细化改进
- **可扩展性**：模块化架构，易于添加新的图表类型和样式

### 技术栈

**Python**：
- LangChain / LangGraph - 智能体框架和工作流编排
- Pydantic - 数据验证
- Tenacity - 重试机制
- ChromaDB - 向量数据库

**Node.js**：
- Next.js 14.2 - 渲染服务框架
- tldraw 3.15 - 图表编辑库
- Playwright - 浏览器自动化截图
- Material icon API - 图标资源服务

---

## 当前执行契约

默认 CLI 主线是 `multiagent + excalidraw`：`Structure -> Styling -> Layout -> Render -> Verify -> optional Refine -> Finalize`。`canvas_environment` 是主工作流、验证和优化阶段应使用的公共 render/validate/audit facade；`agentic_system/render_engine` 是 facade 后方的实现层。

| Canvas / Mode | Multiagent generation | Oneshot generation | Iterative refiner | Knowledge evolution |
|---------------|-----------------------|--------------------|-------------------|---------------------|
| Excalidraw | 支持 | 支持 | 支持，仅 non-oneshot | 支持 |
| TLDraw | 支持 | 不支持 | 不支持 | 不支持 |

- CLI verifier 默认开启，可用 `--no-verifier` 关闭。
- CLI refiner 默认取 `configs/settings.yaml` 的 `generation.enable_refiner`，当前默认开启，`--refiner-iterations` 默认 3；但仍受上表能力限制。
- 后端 streaming 当前只支持 pipeline/multiagent 分阶段事件；后端 refiner 由 user tier 控制，free 不跑，pro 最多 1 轮，TLDraw 会跳过 refiner。
- `render_manifest()` 只保证 manifest/PNG 渲染和少数 blocking render audit，不代表完整质量通过；完整质量门控在 verification/refinement。

---

## 系统架构

### 整体架构图

```
                          文本输入
                              ↓
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Text2DiagramWorkflow (主工作流)                          │
│                                                                              │
│  配置来源: models.yaml (--model-config) 或环境变量 (.env)            │
│  共享系统提示词: common/skill_loader.py → EVODIAGRAM_SKILL_SYSTEM_PROMPT    │
└──────────────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Generation Stage (生成阶段)                              │
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │  Structure   │→ │   Styling    │→ │    Layout    │→ │    Render    │ │
│  │  Agent       │   │   Agent      │   │    Agent     │   │   Engine     │ │
│  │  (1 LLM)     │   │   (1 LLM)    │   │   (1 LLM)    │   │  (无 LLM)   │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│  元素结构             视觉样式            位置与尺寸          manifest + PNG   │
└──────────────────────────────────────────────────────────────────────────────┘
                              ↓
                    rendered_diagram.png
                     /              \
                    ↓                ↓
┌─────────────────────────┐  ┌─────────────────────────┐
│  Verification Stage     │  │    --no-verifier        │
│  (CLI 默认开启)         │  │                         │
│  可用 --no-verifier 关闭│  │                         │
│                         │  │                         │
│  客观检查 (纯Python)    │  │                         │
│  + VLM 主观评判         │  │                         │
│  → verifier_report.json │  │                         │
└─────────────────────────┘  └─────────────────────────┘
            ↓ (有问题时)
┌─────────────────────────┐
│  Refinement Stage       │
│  (优化阶段, 可选)       │
│  --enable-refiner       │
│                         │
│  VLM 分析 → 自动修复   │
│  → refined PNG          │
└─────────────────────────┘
```

**三大阶段关系**：Generation 是核心流水线（必选），Verification 和 Refinement 是后处理阶段（可选）。三者在目录结构中平级：`generation_stage/`、`verification_stage/`、`refinement_stage/`。

### 数据流

1. **输入阶段**：接收文本内容和用户查询
2. **知识检索**：从设计记忆系统检索相关设计知识
3. **结构提取**：生成元素结构（节点、边、组）
4. **样式设计**：分配视觉属性（颜色、字体、图标）
5. **布局计算**：先估计元素尺寸，再由 Layout LLM 生成空间位置
6. **渲染输出**：生成 Excalidraw/TLDraw 清单和 PNG 图像
7. **质量验证**：客观规则检查 + VLM 主观评判（可选）
8. **优化改进**：使用 VLM 进行视觉质量优化（可选）

---

## 共享基础设施

### 共享系统提示词 (EVODIAGRAM_SKILL_SYSTEM_PROMPT)

所有生成阶段的 Agent（Structure、Styling、Layout、Unified）共用同一个系统提示词，定义在 `common/skill_loader.py` 中。

**使用方**：

| Agent | 文件 | 用途 |
|-------|------|------|
| StructureAgent | `generation_stage/structure/structure_agent.py` | 元素结构提取 |
| StylingAgent | `generation_stage/styling/styling_agent.py` | 视觉样式分配 |
| LayoutAgent | `generation_stage/layout/layout_agent.py` | 空间布局计算 |
| UnifiedAgent | `generation_stage/unified/generator.py` | 一站式生成 |

**设计意图**：统一的角色定义和约束条件，确保各阶段 Agent 在相同的认知框架下工作，减少阶段间的语义漂移。各 Agent 的任务提示词（task prompt）不同，但系统级约束一致。

### BaseAgent 基类

所有 LLM Agent 继承自 `core/base_agent.py` 的 `BaseAgent`，提供：

- LLM 调用封装（支持多 provider）
- JSON 输出解析与重试（tenacity，最多 5 次）
- 统一的错误处理

### ModelConfig 配置

通过 `configs/models.yaml`（providers → models）定义可用模型，`configs/settings.yaml`（roles）定义各阶段使用的模型，由 `config/model_loader.py` 的 `ModelConfig` 解析。

---

## 核心工作流

### 1. Structure Workflow (结构工作流)

**目标**：将非结构化文本转换为结构化的元素结构

#### 工作流程

```
文本内容 → StructureAgent (one-shot) → ElementStructure
```

#### 智能体

- **StructureAgent**（one-shot，1 次 LLM 调用）
  - 在单次调用中完成设计思考和结构合成
  - 确定图表类型（流程图、思维导图、组织架构图等）
  - 构建包含节点、边和组的元素结构
  - 提取概念实体和关系，建立层次结构

#### 输出

```json
{
  "chart_type": "flowchart",
  "nodes": [
    {
      "id": "node_1",
      "label": "概念A",
      "type": "Concept"
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "node_1",
      "target": "node_2",
      "relation": "包含"
    }
  ],
  "groups": [
    {
      "id": "group_1",
      "label": "分组1",
      "members": ["node_1", "node_2"],
      "group_member_relation": "parallel"
    }
  ]
}
```

#### 文件位置

- `agentic_system/generation_stage/structure/`
- 主要文件：
  - `structure_agent.py` - 结构智能体（one-shot）
  - `prompts/` - 结构提示词
  - `workflow.py` - 结构工作流编排
  - `state.py` - 状态定义

---

### 2. Styling Workflow (样式工作流)

**目标**：为语义元素分配视觉样式和图标

#### 工作流程

```
ElementStructure → StylingAgent (one-shot) → StylingInstantiation
```

#### 智能体

- **StylingAgent**（one-shot，1 次 LLM 调用）
  - 在单次调用中完成设计思考和样式执行
  - 定义调色板、字体选择、线条样式，确保整体视觉一致性
  - 为节点选择合适的 Material Symbols 图标
  - 生成所选 canvas 的样式参数（默认 Excalidraw；TLDraw 使用独立 contract）

#### 输出

```json
{
  "node_1": {
    "color": "#FF5722",
    "fill": "#FFCCBC",
    "stroke": "#BF360C",
    "font": "sans-serif",
    "icon": "arrow_forward"
  },
  "edge_1": {
    "color": "#757575",
    "strokeWidth": 2,
    "style": "solid"
  }
}
```

#### 文件位置

- `agentic_system/generation_stage/styling/`
- 主要文件：
  - `styling_agent.py` - 样式智能体（one-shot，含图标选择）
  - `prompts/` - 提示词和设计手册
  - `workflow.py` - 样式工作流编排

---

### 3. Layout Workflow (布局工作流)

**目标**：在画布上对元素进行空间排列

#### 工作流程

```
ElementStructure + StylingInstantiation
    → estimate_sizes (文本宽度估算)
    → LayoutAgent (one-shot LLM, 生成空间位置)
    → LayoutInstantiation
```

#### 智能体

- **LayoutAgent**（one-shot，1 次 LLM 调用）
  - 计算所有元素的精确 (x, y) 坐标和尺寸
  - 处理特殊图表类型的布局需求

#### 预处理与后处理

- **estimate_sizes**：基于文本内容估算节点的 min_width / min_height
- 旧 dagre baseline prepass 与 baseline validator 已移除；layout 阶段不再依赖 stage-local dagre 客户端

#### 输出

```json
{
  "node_1": {
    "x": 100,
    "y": 200,
    "width": 150,
    "height": 80
  },
  "node_2": {
    "x": 300,
    "y": 200,
    "width": 150,
    "height": 80
  }
}
```

#### 文件位置

- `agentic_system/generation_stage/layout/`
- 主要文件：
  - `layout_agent.py` - 布局智能体（one-shot）
  - `element_shape_estimator.py` - 节点尺寸估算
  - `prompts/` - 布局提示词
  - `workflow.py` - 布局工作流编排

---

### 4. Tool Services (Node.js 工具服务)

**目标**：为 Python pipeline 提供 JS 生态能力（渲染、图标服务、文字测量）

`tool_services/` 是一个 Next.js 微服务，Python 通过 HTTP 或 subprocess 调用。

#### 三个调用点

| 调用方 (Python) | 目标 | 方式 | 用途 |
|---|---|---|---|
| `render_engine/canvas_render.py` | `scripts/render-tldraw.ts` / `render-excalidraw.ts` | subprocess (`npx tsx`) | Playwright 截图，JSON → PNG |
| `render_engine/shared/icon_url_adder.py` | `/icons/material-design-icons/{color}/{icon}.svg` | 生成 URL（渲染时浏览器 fetch） | Material Symbols 图标 SVG |

Layout workflow 现在只做元素尺寸预估，然后由 Layout LLM 基于 Structure + Styling 的 conversation context 直接生成坐标；旧 dagre baseline prepass 已移除。

#### canvas_render 调用链

```
Text2DiagramWorkflow._render_generation_output()
  → canvas_environment.render_manifest() / canvas_environment.render_png_result()
  → render_engine/service.py
  → render_engine/workflow.py
  → render_canvas(data, output_path, canvas_library)
    → TldrawRender.render()    # subprocess: npx tsx scripts/render-tldraw.ts --snapshot - --output out.png
    → ExcalidrawRender.render() # subprocess: npx tsx scripts/render-excalidraw.ts --scene - --output out.png
    → smart_crop()              # 后处理：裁剪白边
```

#### icon_url_adder 调用链

```
render_engine/workflow.py (add_icon_urls node)
  → icon_url_adder(styling_json)
    → 为每个 icon 生成 http://localhost:3000/icons/material-design-icons/{color}/{icon}.svg
    → 渲染时 Playwright 浏览器自动 fetch 这些 URL
```

图标文件由 `scripts/setup_icons.py` 下载并复制到 `tool_services/public/icons/`。

#### API 端点

```
tool_services/src/app/api/v1/
├── tools/layout/route.ts              # POST dagre 布局计算
├── tools/text-width/route.ts          # POST canvas 文字宽度测量
├── renderers/tldraw/snapshot/route.ts # POST TLDraw → PNG
└── renderers/excalidraw/snapshot/route.ts # POST Excalidraw → PNG
```

#### 文件位置

- `agentic_system/tool_services/` — Next.js 应用
- `agentic_system/render_engine/canvas_render.py` — 渲染入口
- `agentic_system/render_engine/shared/icon_url_adder.py` — 图标 URL 生成

---

### 5. Render Workflow (渲染工作流)

**目标**：组装最终的图表文件并渲染图像

系统支持 **两种渲染管道**：

#### A. TLDraw 渲染管道（传统）

```
LayoutInstantiation + ElementStructure → 添加图标URL → 转换 → 箭头添加 → 组框适配 → 验证 → 结束
```

**节点**：`add_icon_urls` → `convert_snapshot` → `add_arrows` → `fit_groups` → `validate_snapshot`

#### B. Excalidraw 渲染管道（默认）

```
LayoutInstantiation + ElementStructure → 添加图标URL → 转换 → 尺寸适配 → 组框适配 → 组框对齐 → 箭头添加 → Z序修复 → 验证 → 结束
```

**节点**：`excalidraw_add_icon_urls` → `excalidraw_convert` → `excalidraw_size_fit` → `excalidraw_fit_groups` → `excalidraw_align_groups` → `excalidraw_arrows` → `excalidraw_zorder_repair` → `excalidraw_validate`

#### 处理步骤

1. **添加图标 URL**：为各元素补充图标资源链接
2. **转换**：将 `LayoutInstantiation` 转换为 Excalidraw/TLDraw 兼容的 JSON 结构
3. **尺寸适配**：根据标签文本长度自动扩展 shape 宽度
4. **箭头添加**：优先使用 layout/converter 保留的 `edge_data` 绘制连接线，缺失时回退到 `ElementStructure` 关系（支持 case-preserving ID 匹配）
5. **组框适配**：调整组框架的大小和位置以适应其子节点
6. **Z 序修复**：调整元素层级顺序，确保遮挡关系正确
7. **验证**：检查清单完整性
8. **渲染**：使用无头浏览器（Playwright）将图表捕获为 PNG 图像

#### 工具

- `InstantiationToExcalidrawConverter` - Excalidraw 格式转换器（含 `_safe_num` 数字安全处理）
- `ExcalidrawArrowAdder` - Excalidraw 箭头添加工具（支持 bound text 查找）
- `ExcalidrawGroupFitter` - 组框适配器
- `ExcalidrawZOrderRepair` - Z 序修复工具
- `ExcalidrawValidator` - Excalidraw 验证器
- `ArrowAdder` - TLDraw 箭头添加工具

#### 输出

```json
{
  "document": {
    "pages": {
      "page:page": {
        "id": "page:page",
        "name": "Page 1",
        "shapes": [...],
        "assets": {}
      }
    }
  }
}
```

#### 文件位置

- `agentic_system/render_engine/`
- 主要文件：
  - `service.py` - `canvas_environment` facade 后方的渲染实现适配层
  - `excalidraw/` - Excalidraw 渲染管道（converter、arrow_adder、group_fitter、zorder_repair、validator、render）
  - `tldraw/` - TLDraw 渲染管道（converter、arrow_adder、group_fitter、validator、render）
  - `shared/` - 共享工具（render_audit、normalization、edge routing 等）
  - `canvas_render.py` - 画布渲染入口

---

### 6. Refiner Workflow (优化工作流) - 可选

**目标**：使用 VLM 分析并优化图表的视觉质量

#### 工作流程

```
DiagramManifest + RenderedImage → VLM分析 → 问题检测 → 自动修复 → 渲染
```

#### 功能

- **视觉问题检测**：识别重叠、对齐问题、文本截断等
- **语义箭头分析**：根据原始文本优化箭头连接
- **自动修复**：调整位置、大小、样式
- **迭代优化**：CLI 默认最多 3 轮；后端 pro streaming 最多 1 轮

#### 输出

- `7_refiner/refined_manifest.json` - 收敛后才提升为 refined 的清单
- `7_refiner/refined_diagram.png` - 收敛后才提升为 refined 的图像
- `7_refiner/candidate_manifest.json` / `candidate_diagram.png` - 未收敛时保留的候选产物；主 workflow 仍使用原始 render 作为 final
- `final_diagram_manifest.json` / `rendered_diagram.png` - 主 workflow 最终选用的产物

#### 文件位置

- `agentic_system/refinement_stage/`
- 主要文件：
  - `workflow.py` - 优化工作流编排
  - `agent/llm_agent.py` - VLM 智能体
  - `tools/` - 修复工具集

---

## 验证与优化工作流

### 7. Verifier Workflow (验证工作流)

**目标**：基于客观规则 + VLM 主观评判，对图表进行质量验证，输出结构化报告

#### 工作流程

```
DiagramManifest + RenderedImage + Structure
    → load_inputs (加载 manifest / structure / layout JSON)
    → run_objective_checks (纯 Python，无 LLM)
    → run_subjective_critic (1 次 VLM 调用，可 --no-critic 跳过)
    → build_report (输出 verifier_report.json)
```

#### 客观检查（Objective Checks）

| 检查项 | 模块 | 说明 |
|--------|------|------|
| Schema 校验 | `render_validation` | manifest 结构完整性 |
| 渲染审计 | `render_audit` | 渲染阶段遗留问题 |
| 布局审计 | `layout_audit` | 布局阶段遗留问题 |
| 箭头-形状绑定 | `binding_consistency` | 箭头是否正确连接到目标元素 |
| 组框包含 | `containment` | 组框是否完全包含子节点 |
| 泳道成员 | `containment` | 节点是否在正确的泳道内 |
| 节点重叠 | `collision_detection` | 节点之间是否存在重叠 |
| 边交叉 | `collision_detection` | 连接线是否不必要地交叉 |
| 画布溢出 | `collision_detection` | 元素是否超出画布边界 |

严重度分为四级：`CRITICAL`（渲染损坏）、`MAJOR`（视觉缺陷）、`MINOR`（质量瑕疵）、`INFO`（观察性信息）

#### 主观评判（VLM Critic）

- 使用 VLM 分析渲染后的 PNG 图像
- 从 structure、styling、layout 三个维度评分（0-10）
- 生成总体评分和改进建议
- 通过 `models.yaml` 的 `verifier` 角色配置 VLM

#### 文件位置

- `agentic_system/verification_stage/`
- 主要文件：
  - `workflow.py` - 验证工作流编排（4 节点 LangGraph）
  - `state.py` - 状态定义（VerifierState、Critique）
  - `checks/aggregator.py` - 检查聚合器
  - `checks/collision_detection.py` - 碰撞/交叉/溢出检测
  - `checks/containment.py` - 组框/泳道包含检查
  - `checks/binding_consistency.py` - 箭头绑定一致性
  - `checks/render_validation.py` - schema/渲染/布局审计
  - `critic/critic_agent.py` - VLM 主观评判智能体
  - `reports/report_builder.py` - 报告构建器

### 8. Verifier Refiner Workflow (验证驱动的优化工作流)

**目标**：结合 Verifier 的反馈自动修复图表问题

#### 工作流程

```
DiagramManifest + 验证报告 → 加载输入 → 迭代修复 → 最终定稿
```

**节点**：`load_inputs` → `run_iteration`（循环）→ `finalize`

#### 功能

- **验证驱动**：根据 Verifier 报告中的问题自动选择修复策略
- **迭代修复**：支持多轮验证-修复循环
- **修复器集合**：不同问题类型对应专门的 fixer

#### 文件位置

- `agentic_system/refinement_stage/`
- 主要文件：
  - `workflow.py` - 工作流编排
  - `agent/llm_agent.py` - LLM 修复智能体
  - `fixers/` - 各类修复器
  - `reports/` - 报告输出

渲染通过 `evo_diagram.canvas_environment.render_png_result()` 复用当前
canvas facade；`render_engine/service.py` 只作为后方渲染实现适配层。

### 9. Unified Workflow (统一工作流)

**目标**：简化端到端调用，将多个阶段合并为一个统一接口

#### 工作流程

```
文本输入 → 生成场景 → 规范化场景 → 验证场景 → 输出
```

**节点**：`generate_scene` → `normalize_scene` → `validate_scene`

#### 文件位置

- `agentic_system/generation_stage/unified/`
- 主要文件：
  - `workflow.py` - 统一工作流
  - `generator.py` - 统一智能体

---

## 数据模型

### 元素结构 (ElementStructure)

```python
class ElementStructure(BaseModel):
    """最终的元素结构结构"""
    chart_type: str  # 图表类型
    nodes: List[GraphNode]  # 节点列表
    edges: List[GraphEdge]  # 边列表
    groups: List[GraphGroup]  # 分组列表

class GraphNode(BaseModel):
    """元素结构节点"""
    id: str
    label: str
    type: str

class GraphEdge(BaseModel):
    """元素结构边"""
    id: str
    source: str
    target: str
    relation: str
    label: Optional[str]

class GraphGroup(BaseModel):
    """元素结构分组"""
    id: str
    label: str
    parent_group_id: Optional[str]
    members: List[str]  # 成员节点 ID
    relations: List[str]  # 连接成员的边 ID
    group_member_relation: str  # 成员关系类型
```

### 样式实例化 (StylingInstantiation)

将元素 ID 映射到视觉属性：

```python
{
    "element_id": {
        "color": "#HEX",
        "fill": "#HEX",
        "stroke": "#HEX",
        "font": "font-family",
        "icon": "icon_name"
    }
}
```

### 布局实例化 (LayoutInstantiation)

扩展样式实例化，添加几何信息：

```python
{
    "element_id": {
        "x": float,
        "y": float,
        "width": float,
        "height": float
    }
}
```

### 图表清单 (DiagramManifest)

所选 canvas 后端的最终格式。默认 Excalidraw clipboard manifest；TLDraw 后端使用 TLDraw snapshot。

```python
{
    "document": {
        "pages": {
            "page:page": {
                "id": "page:page",
                "name": "Page 1",
                "shapes": [...],  # 所有形状定义
                "assets": {...}   # 资源定义
            }
        }
    }
}
```

---

## 设计记忆系统

### 概述

设计记忆系统是一个基于 ChromaDB 的向量数据库，用于存储和检索图表设计知识。

### 功能

- **知识存储**：存储结构、样式、布局等设计知识
- **智能检索**：基于语义相似度检索相关设计
- **层级管理**：按层级（结构、样式、布局）组织知识
- **动态更新**：支持知识的添加和更新

### 使用

```python
from evo_diagram.design_memory.diagram_design_memory import DiagramDesignMemory
from evo_diagram.design_memory.diagram_design_retriever import DiagramDesignRetriever

# 初始化
memory = DiagramDesignMemory(vector_db_path="./data/knowledge")
retriever = DiagramDesignRetriever(memory)

# 检索知识
search_query = "流程图设计原则"
retrieved_docs = retriever.retrieve_knowledge(search_query)

# 格式化结果
for layer, docs in retrieved_docs.items():
    print(f"=== {layer.upper()} ===")
    for doc in docs:
        print(doc.page_content)
```

### 文件位置

- `design_memory/`
- 主要文件：
  - `diagram_design_memory.py` - 向量库管理
  - `diagram_design_retriever.py` - 检索逻辑
  - `memory_workflow.py` - 存储与检索工作流

---

## 快速开始

### 环境要求

- **Python**: 3.11+
- **Node.js**: 18+
- **Conda**: 推荐用于环境管理

### 安装步骤

1. **克隆仓库**

```bash
git clone https://github.com/GeminiLight/EvoDesign.git
cd EvoDesign
```

2. **创建 Python 环境**

```bash
conda create -n evodiagram python=3.11
conda activate evodiagram
```

3. **安装 Python 依赖**

```bash
pip install -r evo_diagram/requirements.txt
```

4. **安装 Node.js 依赖**

```bash
cd evo_diagram/agentic_system/tool_services
npm install
cd ../../..
```

5. **配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入 API 密钥：

```bash
OPENAI_API_KEY=your_key
PROXY_B_API_KEY=your_key
```

6. **配置 YAML**（推荐）

编辑仓库根目录 `configs/models.yaml` 配置 provider/model，编辑 `configs/settings.yaml` 配置 roles。`api_key` 支持 `env:VAR_NAME` 语法从环境变量加载。完整说明见 `../../docs/configuration.md`。

6. **初始化设计记忆系统**

```bash
python -m design_memory.memory_workflow
```

### 运行系统

需要两个终端：

**终端 1：启动渲染服务**

```bash
cd evo_diagram/agentic_system/tool_services
npm run dev
```

服务运行在 `http://localhost:3000`

**终端 2：运行图表生成**

```bash
# 使用默认 configs/*.yaml
python -m evo_diagram.agentic_system.main --example 1

# 或显式指定配置文件
python -m evo_diagram.agentic_system.main --example 1 --model-config configs/models.yaml --settings configs/settings.yaml
```

### 输出结构

输出目录取决于入口：

- CLI test/eval dataset：`experiments/{exp_id}/outputs/evodiagram/{variant}/{model}/{item_id}/`
- CLI non-eval dataset：`examples/{item_id}/`
- Backend streaming：`{RESULTS_DIR}/stream_runs/{request_id}/`
- `--no-save-intermediate`：中间阶段进入临时目录，最终只保留 `final_diagram_manifest.json` / `rendered_diagram.png`

Multiagent 输出结构如下：

```
examples/{item_id}/
├── 1_structure/
│   ├── structure_instantiation.json     # 元素结构
│   └── structure_specification.json     # 结构设计说明
├── 2_styling/
│   ├── styling_instantiation.json       # 样式实例
│   └── styling_specification.json       # 样式设计说明
├── 3_layout/
│   ├── layout_instantiation.json        # 带位置信息的元素
│   └── layout_specification.json        # 布局设计说明
├── 4_render/
│   ├── diagram_manifest.json            # 渲染清单
│   └── diagram_manifest.png             # 初始渲染图像
├── 6_verification/
│   └── verifier_report.json             # 验证报告（CLI 默认开启；--no-verifier 时不写入）
├── 7_refiner/
│   ├── refined_manifest.json            # refiner 收敛时
│   ├── refined_diagram.png              # refiner 收敛时
│   ├── candidate_manifest.json          # refiner 未收敛时
│   └── candidate_diagram.png            # refiner 未收敛时
├── 8_final_verification/                # refined artifact 被采用后才写入
├── final_diagram_manifest.json          # 最终选用清单
└── rendered_diagram.png                 # 最终选用图像
```

Oneshot 输出不会产生 `1_structure/2_styling/3_layout`，而是写入 `1_unified/diagram_manifest.json`、`1_unified/structure_instantiation.json` 和可选 `raw_llm_output.txt`。

---

## 开发指南

### 添加新的智能体

1. **创建智能体文件**

```python
# agentic_system/generation_stage/{workflow}/new_agent.py
from langchain_core.language_models import BaseChatModel
from evo_diagram.agentic_system.generation_stage.{workflow}.state import WorkflowState

class NewAgent:
    def __init__(self, model: BaseChatModel):
        self.model = model

    def run(self, state: WorkflowState) -> WorkflowState:
        # 实现智能体逻辑
        return state
```

2. **定义提示词**

```python
# agentic_system/generation_stage/structure/prompts/new_agent_prompt.py
SYSTEM_PROMPT = """
# Role: [智能体角色名称]

## Role Context
简要描述智能体的核心身份和专业定位

## Layer Alignment
定义该智能体如何确保层级之间的逻辑一致性

## Logic Paradigm
规定该智能体必须遵循的推理范式

## Global Constraints
注入所有智能体必须共同遵守的底层硬约束
"""

TASK_PROMPT = """
# Task: [具体任务名称]

## Task Objective
简要明确本次任务的具体目标

## Input Context
描述当前任务依赖的核心输入数据

## Execution Pipeline
详细说明完成任务的原子操作步骤

## Strict Constraints
列出针对当前任务的即时禁令

## Output Format
规定输出 JSON 的具体字段结构

## Input Data
{input_data}
"""
```

3. **集成到工作流**

```python
# agentic_system/generation_stage/structure/workflow.py
from langgraph.graph import StateGraph, END

def create_workflow():
    workflow = StateGraph(WorkflowState)

    # 添加节点
    workflow.add_node("new_agent", new_agent_node)

    # 定义边
    workflow.add_edge("previous_node", "new_agent")
    workflow.add_edge("new_agent", "next_node")

    return workflow.compile()
```

### 修改提示词

提示词位于各工作流的 `prompts.py` 或 `prompts/` 模块：

```bash
agentic_system/generation_stage/structure/prompts.py
agentic_system/generation_stage/styling/prompts.py
agentic_system/generation_stage/layout/prompts/
```

### 调整布局算法

布局算法位于 `agentic_system/generation_stage/layout/`：

- `element_shape_estimator.py` - 节点尺寸估算
- `layout_agent.py` / `prompts/` - LLM 布局策略与输出约束

如果需要重新启用外部 dagre 能力，先通过 `agentic_system/tool_services/src/app/api/v1/tools/layout/route.ts` 或 `tool_services/scripts/layout-cli.ts` 做独立实验，再把结果显式接回 layout workflow。

### 自定义样式

样式提示词和 canvas-specific contract 位于：

- `agentic_system/generation_stage/styling/prompts.py` - styling system/task prompt
- `agentic_system/generation_stage/styling/contracts/` - Excalidraw/TLDraw 样式 contract

修改颜色方案：

```python
COLOR_PALETTES = {
    "default": {
        "primary": "#2196F3",
        "secondary": "#FF9800",
        "success": "#4CAF50",
        "warning": "#FFC107",
        "danger": "#F44336"
    }
}
```

### 测试

运行测试套件：

```bash
# 所有测试
pytest tests/

# 特定测试
pytest tests/test_workflow.py

# 带输出
pytest tests/ -v -s
```

---

## 配置说明

### 推荐方式：configs/*.yaml

系统通过根目录 `configs/models.yaml` 管理 provider/model，通过 `configs/settings.yaml` 管理 roles 和应用默认值：

```yaml
# configs/models.yaml

providers:       # 连接信息（base_url, api_key）
  openai:
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY          # 从环境变量加载
  proxyB:
    base_url: https://api.your-proxy-endpoint/v1
    api_key: env:PROXY_B_API_KEY

models:          # 模型参数（temperature, timeout 等）
  gemini-thinking:
    provider: proxyB                      # 引用 provider
    model_name: "[CodeA]gemini-3-pro-preview-thinking"
    temperature: 0
    timeout: 1200
```

```yaml
# configs/settings.yaml
roles:           # 角色映射（pipeline 各阶段用哪个 model）
  default: gpt-5.5                       # 通用回退
  generator: gemini-thinking             # 主流水线 (Structure, Styling, Layout)
  refiner: gemini-vlm                    # VLM 优化 (RefinerAgent)
  verifier: gpt-5.5                      # VLM 主观评分 (VerifierCriticAgent)
  fast: qwen-fast                        # 低成本任务
  eval: eval-model                       # 评估
  distiller: gpt-5.5                     # 知识蒸馏 (knowledge_evolution)
```

默认自动读取 `configs/*.yaml`。也可以通过 CLI 显式指定：

```bash
# 使用默认配置
python -m evo_diagram.agentic_system.main --example 1

# 指定不同角色作为主模型
python -m evo_diagram.agentic_system.main --example 1 --role router

# 开启 refiner（Excalidraw + multiagent；自动使用 roles.refiner 对应的 VLM）
python -m evo_diagram.agentic_system.main --example 1 --enable-refiner
```

### 环境变量 (.env)

`configs/models.yaml` 中 `api_key` 支持 `env:VAR_NAME` / `$VAR_NAME` 语法从环境变量加载。当前统一从仓库根目录 `.env` 加载共享环境变量：

```bash
# .env

# 默认 StepFun 配置
STEPFUN_API_KEY=your_key

# 仅后端 / 基线直连路径需要
# LLM_API_KEY=your_key

# 渲染服务
RENDER_SERVICE_URL=http://localhost:3000

# 向量数据库
VECTOR_DB_PATH=./data/knowledge
```

`LLM_*` environment variables are reserved for backend and baseline direct-call paths; the agentic system should use `configs/*.yaml`.

---

## 常见问题

### Q1: 渲染服务无法启动

**问题**：`npm run dev` 报错

**解决方案**：

```bash
# 检查 Node.js 版本
node --version  # 需要 18+

# 重新安装依赖
cd evo_diagram/agentic_system/tool_services
rm -rf node_modules package-lock.json
npm install

# 检查端口占用
lsof -i :3000
```

### Q2: LLM 调用失败

**问题**：API 调用超时或失败

**解决方案**：

1. 检查 `.env` 中的 API 密钥是否正确
2. 检查网络连接
3. 增加超时时间：

```python
# core/llm_factory.py
model = LLMFactory.create(
    model="qwen3-vl-plus",
    timeout=120  # 增加到 120 秒
)
```

### Q3: 布局计算超时

**问题**：大型图表布局计算时间过长

**解决方案**：

1. 减少节点数量
2. 使用更简单的布局算法
3. 检查 `generation_stage/layout/element_shape_estimator.py` 和 layout prompt 是否对大型图表给出了过大的尺寸或间距约束

### Q4: 内存不足

**问题**：渲染大型图表时内存溢出

**解决方案**：

1. 使用当前主入口复现问题，并在 renderer/tool service 侧调整资源或视口配置：
```bash
python -m evo_diagram.agentic_system.main --example 1 \
  --dataset-path dataset/test/data.json \
  --tag large-diagram
```

2. 分批渲染节点
3. 使用更高效的布局算法

### Q5: 优化工作流不生效

**问题**：`--enable-refiner` 后没有改进

**解决方案**：

1. 检查 VLM 配置：
```bash
# 确保有 VLM API 密钥
cat .env-gemini
```

2. 检查渲染服务是否运行：
```bash
curl http://localhost:3000
```

3. 查看报告：
```bash
# 检查优化工作流报告
cat examples/{item_id}/7_refiner/refiner_report.json
```

---

## 附录

### 支持的图表类型

- 流程图 (Flowchart)
- 思维导图 (Mind Map)
- 组织架构图 (Org Chart)
- 序列图 (Sequence Diagram)
- 状态图 (State Diagram)
- 类图 (Class Diagram)
- 数据流图 (Data Flow Diagram)
- 泳道图 (Swimlane Diagram)
- 矩阵图 (Matrix Diagram)
- 金字塔图 (Pyramid Diagram)
- 漏斗图 (Funnel Diagram)
- 甘特图 (Gantt Chart)
- 鱼骨图 (Fishbone Diagram)

### 支持的图标库

系统使用 Material Symbols，支持 2000+ 图标。

常用图标：
- 箭头：`arrow_forward`, `arrow_back`, `arrow_upward`
- 流程：`play_arrow`, `pause`, `stop`
- 数据：`storage`, `database`, `cloud`
- 通信：`share`, `link`, `connect_without_contact`
- 文档：`description`, `article`, `folder`

### 参考资源

- [LangChain 文档](https://python.langchain.com/)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [TLDraw 文档](https://tldraw.dev/docs)
- [Material Symbols](https://fonts.google.com/icons)
- [G6 图可视化](https://g6.antv.antgroup.com/)

### 贡献指南

欢迎贡献！请遵循以下步骤：

1. Fork 仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

---

**文档版本**: 1.3.0
**最后更新**: 2026-05-02
**维护者**: AuraX AI Team
