# Render Engine（渲染引擎）

将布局 JSON 转换为画布 manifest（Excalidraw/TLDraw）并渲染 PNG 图片。不涉及 LLM。

## 入口

当前公共入口是 `evo_diagram.canvas_environment`：
- `render_manifest()`：从 layout + structure 构建 manifest 并渲染 PNG；
- `render_png_result()`：仅渲染已有 manifest，返回包含 `ok/output_path/error` 的结果对象。

`agentic_system/render_engine/service.py` 是 facade 后面的实现适配层，承接 converter、arrow、fit、z-order、validator 等底层步骤；主工作流和优化阶段应通过 `canvas_environment` facade 调用，避免重新耦合到底层 render_engine service。

`render_manifest()` 是渲染边界，不是完整质量门控。它会验证 manifest 形状并阻断少数 render-time 语义丢失；完整质量检查仍在 `verification_stage` / `refinement_stage`。

## 两种渲染后端

### Excalidraw（默认）

目录：`render_engine/excalidraw/`

```
LayoutInstantiation + ElementStructure
    → icon_url_adder（shared）
    → converter.py — 布局 JSON → Excalidraw 元素
    → shape_size_fitter.py — 根据标签文本自动扩展形状宽度
    → group_fitter.py — 调整组框适配子节点
    → group_alignment_normalizer.py — 保持等宽/等高组框意图
    → arrow_adder.py — 添加方向箭头（支持大小写不敏感的 ID 匹配）
    → zorder_repair.py — 修复 z 序
    → validator.py — 验证 manifest
    → render.py — 通过 Playwright 渲染 PNG
```

### TLDraw（传统）

目录：`render_engine/tldraw/`

```
LayoutInstantiation + ElementStructure
    → icon_url_adder（shared）
    → converter.py — 布局 JSON → TLDraw snapshot
    → arrow_adder.py — 添加方向箭头
    → group_fitter.py — 调整组框适配子节点
    → validator.py — 验证 manifest
    → render.py — 通过 Playwright 渲染 PNG
```

### 共享工具 — `shared/`

| 文件 | 用途 |
|------|------|
| `normalization.py` | 共享 z-order 分层、group frame 检测、标题去重、零填充 index |
| `edge_routing.py` | 将 layout-derived edge data 转换为渲染关系 |
| `icon_url_adder.py` | 为元素图标生成 Material Symbols URL |
| `image_cropper.py` | 智能裁剪白边 |
| `edge_crossing_detector.py` | 检测渲染结果中的边交叉 |
| `render_audit.py` | 审计渲染阶段的问题 |

## 工作流

`workflow.py` — `RenderWorkflow` 将完整渲染管道编排为 LangGraph 图。根据 `CANVAS_LIBRARY` 设置分派到 Excalidraw 或 TLDraw 节点。

当前节点顺序：

- Excalidraw：`excalidraw_add_icon_urls -> excalidraw_convert -> excalidraw_size_fit -> excalidraw_fit_groups -> excalidraw_align_groups -> excalidraw_arrows -> excalidraw_zorder_repair -> excalidraw_validate`
- TLDraw：`add_icon_urls -> convert_snapshot -> add_arrows -> fit_groups -> validate_snapshot`

`canvas_render.py` — 底层渲染分派：通过 subprocess 调用 Playwright（`npx tsx scripts/render-excalidraw.ts` 或 `render-tldraw.ts`）。

`canvas_environment.normalize_manifest()` 和 `repair_manifest_zorder()` 当前只对 Excalidraw 执行实际归一化/修复；TLDraw 是 passthrough，因为 TLDraw 的结构调整在 converter/group fitter 中完成。

## 画布库选择

由 `AppSettings.canvas_library` 控制（默认 `"excalidraw"`）。可通过 `CANVAS_LIBRARY` 环境变量覆盖。

## 端口

渲染服务显式运行在 3000 端口（`tool_services/package.json` 的 `dev`/`start` 脚本都固定 `--port 3000`），与 `start_dev.sh` / `scripts/start_service.sh` 和渲染 CLI 的默认 URL 保持一致。
