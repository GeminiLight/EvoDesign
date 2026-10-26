# Tool Services（工具服务）

基于 Next.js 的微服务，为 Python 流水线提供 JS 生态能力。

## API 端点

```
tool_services/src/app/api/v1/
├── tools/text-width/route.ts          # POST — Canvas 文字宽度测量
├── renderers/tldraw/snapshot/route.ts # POST — TLDraw → PNG
└── renderers/excalidraw/snapshot/route.ts # POST — Excalidraw → PNG
```

## 三个调用点

| Python 调用方 | 端点 | 方式 | 用途 |
|---------------|------|------|------|
| `render_engine/canvas_render.py` | `scripts/render-tldraw.ts` / `render-excalidraw.ts` | subprocess（`npx tsx`） | Playwright 截图，JSON → PNG |
| `render_engine/shared/icon_url_adder.py` | `/icons/material-design-icons/{color}/{icon}.svg` | 生成 URL（渲染时浏览器 fetch） | Material Symbols 图标 SVG |

## Layout

布局阶段不再调用 dagre baseline prepass。当前流程是 Python 端先运行 `estimate_element_sizes()` 补齐节点最小尺寸，然后 Layout LLM 基于上游 Structure + Styling conversation context 直接输出几何。

## 渲染调用链

```
render_engine/canvas_render.py
  → render_canvas(data, output_path, canvas_library)
    → ExcalidrawRender.render()  # subprocess: npx tsx scripts/render-excalidraw.ts
    → smart_crop()               # 后处理：裁剪白边
```

## 图标服务

`scripts/setup_icons.py` 下载 Material Symbols 图标到 `tool_services/public/icons/`。渲染时 Playwright 浏览器从本地服务器 fetch 图标 SVG。

## 启动

```bash
cd tool_services && npm run dev
# 运行在 3000 端口
```
