# 工具服务 (Tool Services)

`evo_diagram/agentic_system/tool_services` 是一个统一的 Next.js 服务，集成了多种辅助后端功能，包括图布局计算、文本宽度测量以及 headless 浏览器渲染服务（TLDraw 和 Excalidraw）。

## 目录结构

```text
tool_services/
├── src/
│   └── app/
│       ├── api/
│       │   └── v1/
│       │       ├── tools/          # 通用工具 API (Layout, TextWidth)
│       │       └── renderers/      # 渲染快照 API
│       └── renderers/              # 前端页面 (用于 Playwright 访问)
│           ├── tldraw/             # TLDraw 渲染页
│           └── excalidraw/         # Excalidraw 渲染页
├── scripts/                        # TypeScript CLI 脚本 (用于 Playwright 渲染)
├── public/                         # 静态资源
│   └── icons/                      # Material Icons（通过 HTTP 访问）
│       └── material-design-icons/  # 图标文件和清单
├── package.json
└── tsconfig.json
```

## 安装与启动

该服务基于 Next.js，需要 Node.js 环境。

### 安装依赖

在 `evo_diagram/agentic_system/tool_services` 目录下运行：

```bash
npm install
```

这将安装 Next.js, React, Playwright, Canvas 等相关依赖。

### 启动服务

```bash
npm start
```

服务默认运行在 `http://localhost:3000`。

### 方式二：CLI 模式 (CLI Mode)

如果您不想通过 HTTP API 调用 layout/text-width，可以直接使用对应 CLI。渲染 CLI 仍使用同一套本地 renderer 页面，默认连接 `localhost:3000`，以避免评测路径和服务路径使用不同的渲染源码。

1. **调用 CLI 工具**:
   Python 代码可以直接通过 `subprocess` 调用 TypeScript 脚本，无需 HTTP 请求。

   - **Layout**: `npx tsx scripts/layout-cli.ts -i input.json -o output.json`
   - **Text Width**: `npx tsx scripts/text-width-cli.ts -i input.json`
   - **Tldraw Render**: `npx tsx scripts/render-tldraw.ts --snapshot snap.json` (默认 `http://localhost:3000/renderers/tldraw`)
   - **Excalidraw Render**: `npx tsx scripts/render-excalidraw.ts --scene scene.json` (默认 `http://localhost:3000/renderers/excalidraw`)

   注意：渲染 CLI 不再生成临时 CDN HTML，也不再使用 `file://out/...`。如需更换端口或 renderer host，请设置 `TLDRAW_RENDER_URL` / `EXCALIDRAW_RENDER_URL` 或显式传 `--url`，且地址必须指向本地 renderer 页面。

## 功能模块

### 1. 布局计算 (Layout)

提供 DAGRE, Force-directed (D3) 和其他布局算法。

- **URL**: `POST /api/v1/tools/layout`
- **请求体**:
  ```json
  {
    "layout": "dagre", // dagre, force, circular
    "nodes": [{ "id": "1", "width": 100, "height": 40 }],
    "edges": [{ "source": "1", "target": "2" }]
  }
  ```
- **响应**: 计算后的节点坐标。

### 2. 文本宽度测量 (Text Width)

基于 Node-canvas 和服务端字体文件测量文本渲染宽度。

- **URL**: `POST /api/v1/tools/text-width`
- **请求体**:
  ```json
  {
    "text": "Hello World",
    "fontSize": 16,
    "font": "sans" // sans, mono, serif, draw
  }
  ```

### 3. 图标托管 (Icon Hosting)

tool_services 托管 Material Icons，供图表渲染时通过 HTTP 访问。

#### 图标目录结构

```
public/icons/material-design-icons/
├── manifest.json           # 图标清单文件
├── filled/                 # 原始填充图标
├── black/                  # 黑色图标
├── grey/                   # 灰色图标
├── light_violet/           # 浅紫色图标
├── violet/                 # 紫色图标
├── blue/                   # 蓝色图标
├── light_blue/             # 浅蓝色图标
├── yellow/                 # 黄色图标
├── orange/                 # 橙色图标
├── green/                  # 绿色图标
├── light_green/            # 浅绿色图标
├── light_red/              # 浅红色图标
└── red/                    # 红色图标
```

#### 访问图标

**单个图标访问**:
```
http://localhost:3000/icons/material-design-icons/<color>/<icon_name>.svg
```

示例:
- `http://localhost:3000/icons/material-design-icons/blue/check.svg`
- `http://localhost:3000/icons/material-design-icons/red/close.svg`

**图标清单访问**:
```
http://localhost:3000/icons/material-design-icons/manifest.json
```

清单文件包含所有可用图标的完整信息：
```json
{
  "version": "1.0",
  "total_icons": 2500,
  "colors": {
    "blue": {
      "hex": "#2f80ed",
      "count": 250,
      "icons": [
        {
          "name": "check",
          "file": "check.svg",
          "url": "/icons/material-design-icons/blue/check.svg"
        }
      ]
    }
  }
}
```

#### 设置图标

图标由 `evo_diagram/scripts/setup_icons.py` 脚本自动设置：

```bash
# 在 evo_diagram 目录下运行
python scripts/setup_icons.py
```

此脚本会：
1. 从 npm 下载 Material Icons
2. 生成12种颜色的图标变体
3. 复制到 `tool_services/public/icons/` 目录
4. 生成 `manifest.json` 清单文件

**可用颜色**: `black`, `grey`, `light_violet`, `violet`, `blue`, `light_blue`, `yellow`, `orange`, `green`, `light_green`, `light_red`, `red`

#### 在渲染中使用图标

在图表渲染时，可以直接引用图标 URL：

```javascript
// 在 Excalidraw 或 Tldraw 中使用图标
const iconUrl = '/icons/material-design-icons/blue/check.svg';
```

或通过清单文件动态获取图标：
```javascript
const response = await fetch('/icons/material-design-icons/manifest.json');
const manifest = await response.json();
const iconUrl = manifest.colors.blue.icons.find(i => i.name === 'check').url;
```

### 4. 图表渲染 (Renderer)

服务通过 Playwright 访问内部 Next.js 页面来将 JSON 数据渲染为图片。

#### 前端渲染页 (UI)

- **TLDraw**: `http://localhost:3000/renderers/tldraw`
- **Excalidraw**: `http://localhost:3000/renderers/excalidraw`

这些页面在 `window` 对象上暴露了特定的注入函数（如 `loadTldrawSnapshot`, `loadExcalidrawScene`），供 Headless 浏览器脚本调用。

#### 快照接口 (Snapshot API)

直接通过 HTTP 请求获取 PNG 图片。

- **TLDraw**: `POST /api/v1/renderers/tldraw/snapshot`
- **Excalidraw**: `POST /api/v1/renderers/excalidraw/snapshot`

#### 两者区别与联系

- **前端渲染页 (UI)**：
  - 本质是 **HTML 页面**。
  - 是实际执行渲染逻辑的"画板"，承载 React 组件和 Canvas 逻辑。
  - 必须由浏览器（或 Headless Browser）访问才能运行。
  - 通常不直接供外部 API 调用，而是供 Snapshot API 内部访问。

- **快照接口 (Snapshot API)**：
  - 本质是 **HTTP API**。
  - 是面向外部服务调用的"自动化服务"。
  - **工作流程**：它接收 JSON 数据 -> 启动 Playwright -> 访问对应的**前端渲染页** -> 注入数据 -> 截图 -> 返回图片。
  - 仓库内 Python 主链路默认通过 `canvas_environment` 调用 CLI renderer；HTTP Snapshot API 是独立的服务调用面，不是主链路依赖。

**请求体示例 (Excalidraw)**:
```json
{
  "scene": { "elements": [...] },
  "viewport": { "width": 2000, "height": 1400 }
}
```

**请求体示例 (TLDraw)**:
```json
{
  "snapshot": { "document": { "store": {}, "schema": {} }, "session": {} },
  "viewport": { "width": 3000, "height": 2000 }
}
```

Snapshot API 使用画板原生字段名：Excalidraw 使用 `scene`，TLDraw 使用 `snapshot`。`manifest` 不是 Snapshot API 的请求字段。

Snapshot API 不接受请求体级别的 `url` 覆盖。渲染页地址只能在服务端配置：

- Excalidraw: `EXCALIDRAW_RENDER_URL`，默认 `http://localhost:3000/renderers/excalidraw`
- TLDraw: `TLDRAW_RENDER_URL`，默认 `http://localhost:3000/renderers/tldraw`

出于安全边界考虑，配置的 URL 必须指向本地 renderer host，并且 path 必须匹配对应的 renderer 页面。

Snapshot API 的 `viewport` 只接受 `width` 与 `height`。裁剪边距由 CLI renderer 的 `--margin` 参数负责，HTTP Snapshot API 不接受 `viewport.margin`。

## 命令行工具 (Scripts)

`scripts/` 目录下提供了 CLI 工具，通常由 Python 渲染边界（`canvas_environment` / `render_engine`）调用。

- `render-excalidraw.ts`: 渲染 Excalidraw 场景生成 PNG。
- `render-tldraw.ts`: 渲染 TLDraw 快照生成 PNG。

这些脚本默认使用自包含的临时 HTML 渲染；只有显式传入 `--url` 或配置脚本专用 renderer URL 时，才连接本地运行的 renderer page。

## 开发注意事项

- 如果修改了前端页面 (`src/app/renderers/...`)，无需重启服务（Next.js Dev 模式），但生产环境需要 rebuild。
- 确保 `public/resources` (或项目根目录 `resources` 软链) 存在，以便字体文件正确加载。
- **图标托管**: Material Icons 存放在 `public/icons/material-design-icons/` 目录，通过 HTTP 自动提供访问。运行 `python scripts/setup_icons.py` 来设置图标。
- **静态资源**: `public/` 目录中的所有文件都可以通过 `http://localhost:3000/` 根路径直接访问。
- **字体文件**: 确保字体文件在 `public/resources/fonts/` 或项目根目录的 `resources/fonts/` 中，以便文本宽度测量功能正常工作。
