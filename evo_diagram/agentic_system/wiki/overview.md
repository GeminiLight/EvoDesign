# Agentic System 总览

Text2Diagram Agentic System 将自然语言文本转换为可编辑的 canvas manifest 和 PNG。当前默认 canvas 是 Excalidraw；TLDraw 是受限/传统后端。

## 当前主线

```
文本 + 查询
    -> StructureWorkflow
    -> StylingWorkflow
    -> LayoutWorkflow
    -> canvas_environment.render_manifest()
    -> VerifierWorkflow
    -> IterativeRefinerWorkflow (可选)
    -> final_diagram_manifest.json + rendered_diagram.png
```

`Text2DiagramWorkflow` 是顶层编排器。生成阶段是必选；verification 默认开启，可用 `--no-verifier` 关闭；refiner 是否运行取决于配置、canvas/mode 能力和 verification blocking 状态。

## 能力矩阵

| Canvas / Mode | Multiagent generation | Oneshot generation | Iterative refiner | Knowledge evolution |
|---------------|-----------------------|--------------------|-------------------|---------------------|
| Excalidraw | 支持 | 支持 | 支持，仅 non-oneshot | 支持 |
| TLDraw | 支持 | 不支持 | 不支持 | 不支持 |

后端 streaming 当前只支持 pipeline/multiagent 阶段事件：`structure -> styling -> layout -> render -> refining`。后端 refiner 由 user tier gate 控制，free 不跑，pro 最多 1 轮；TLDraw 会跳过 refiner。

## 模块索引

| 模块 | 用途 | 详细文档 |
|------|------|----------|
| [common/](common.md) | 共享基础设施 | BaseAgent、skill_loader、task_prompts、领域知识 |
| [generation_stage/](generation_stage.md) | 核心流水线 | Structure、Styling、Layout、Oneshot 工作流 |
| [verification_stage/](verification_stage.md) | 质量验证 | 客观检查 + VLM 主观评判 |
| [refinement_stage/](refinement_stage.md) | 迭代优化 | 确定性修复器 + LLM EditOps |
| [render_engine/](render_engine.md) | PNG 渲染实现层 | Excalidraw + TLDraw 渲染管道 |
| [tool_services/](tool_services.md) | Node.js 服务 | Playwright 渲染、图标服务、布局实验接口 |
| [system_prompt/](system_prompt.md) | 提示词知识库 | 设计模式、最佳实践、领域知识 |

## 输出位置

输出根目录取决于入口：

- CLI test/eval dataset：`experiments/{exp_id}/outputs/evodiagram/{variant}/{model}/{item_id}/`
- CLI non-eval dataset：`examples/{item_id}/`
- Backend streaming：`{RESULTS_DIR}/stream_runs/{request_id}/`
- `--no-save-intermediate`：中间阶段进入临时目录，最终只保留 `final_diagram_manifest.json` / `rendered_diagram.png`

## Multiagent 产物树

```
{run_dir}/
├── 1_structure/
│   ├── structure_instantiation.json
│   └── structure_specification.json
├── 2_styling/
│   ├── styling_instantiation.json
│   └── styling_specification.json
├── 3_layout/
│   ├── layout_instantiation.json
│   └── layout_specification.json
├── 4_render/
│   ├── diagram_manifest.json
│   └── diagram_manifest.png
├── 6_verification/
│   └── verifier_report.json
├── 7_refiner/
│   ├── refined_manifest.json       # refiner 收敛时
│   ├── refined_diagram.png         # refiner 收敛时
│   ├── candidate_manifest.json     # refiner 未收敛时
│   └── candidate_diagram.png       # refiner 未收敛时
├── 8_final_verification/           # refined artifact 被采用后才写入
├── final_diagram_manifest.json
└── rendered_diagram.png
```

Oneshot 输出不会产生 `1_structure/2_styling/3_layout`，而是写入 `1_unified/diagram_manifest.json`、`1_unified/structure_instantiation.json` 和可选 `raw_llm_output.txt`。Oneshot 当前只支持 Excalidraw，且不运行 iterative refiner。

## 快速开始

```bash
# 1. 启动渲染服务（repo root）
cd evo_diagram/agentic_system/tool_services && npm run dev

# 2. 生成图表（repo root）
python -m evo_diagram.agentic_system.main --example 1 --model-config configs/models.yaml

# 3. 显式开启/配置 refiner
python -m evo_diagram.agentic_system.main --example 1 --model-config configs/models.yaml \
    --enable-refiner --refiner-iterations 3
```

## 相关文档

- [generation_stage.md](generation_stage.md)
- [render_engine.md](render_engine.md)
- [verification_stage.md](verification_stage.md)
- [refinement_stage.md](refinement_stage.md)
