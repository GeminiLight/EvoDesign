<!-- Last verified: 2026-03-17 | Current stage: P1 -->

# EvoDesign — 系统架构

Agent CLI v1 的当前实现与协议见 [协作架构](specs/spec-agent-cli-v1.md) 和 [CLI、Skill 契约](specs/agent-cli-v1-cli-and-skill.md)。下文保留早期架构记录，未随本次功能逐项重新核验。

## 技术栈

| 层 | 技术 | 版本 | 选型理由 |
|----|------|------|----------|
| **前端框架** | React + TypeScript + Vite | 19 / 5.9 / 7 | Concurrent Features; 极速 HMR |
| **CSS** | Tailwind CSS | 3.4 | 原子化，深色模式 `class` 策略 |
| **画布 A** | TLDraw | 3.15 | 现代白板引擎，Store + Snapshot API |
| **画布 B** | Excalidraw | 0.18 | 手绘风格，懒加载 |
| **路由** | React Router DOM | 7 | 声明式路由，`location.state` 跨页传参 |
| **后端框架** | FastAPI (Python) | ≥0.109 | 异步原生，自带 OpenAPI 文档 |
| **ORM** | SQLAlchemy 2.0 (async) | ≥2.0.25 | Mapped 类型注解，selectin 预加载 |
| **数据库** | SQLite (dev) / PostgreSQL (prod) | — | `aiosqlite` / `asyncpg` 驱动 |
| **认证** | JWT (python-jose) + httpx-oauth | — | 自管 JWT，不依赖第三方认证服务 |
| **AI 调度** | LangGraph + LangChain | — | 状态机驱动多 Agent 协同 |
| **向量存储** | ChromaDB | — | 三层设计知识（Trajectory / Domain / Universal） |
| **支付** | Stripe | — | Checkout + Portal + Webhook |
| **i18n** | 自研 LanguageProvider | — | 不引入 i18next，轻量；支持 zh/en |

---

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 Vite dev | 5175 | `--host 0.0.0.0 --strictPort` |
| 后端 FastAPI | 3010 | Uvicorn |
| Renderer (Next.js) | 3000 | TLDraw/Dagre/Playwright 渲染缩略图 |

---

## 目录结构（关键路径）

```
EvoDesign/
├── frontend/src/
│   ├── pages/                   # 8 个页面组件
│   ├── components/              # 通用组件 + DiagramCanvas/ + TldrawCanvas/ + Sidebar/
│   ├── features/auth/           # BackendAuthProvider（主用）+ AuthPanel
│   ├── hooks/useDiagramSync.ts  # 画布→后端实时同步核心 Hook
│   ├── services/
│   │   ├── apiDiagramService.ts # AI 生成（SSE 流式）
│   │   ├── backendApi.ts        # CRUD + 快照 + Schema 同步；Guest 自动 fallback
│   │   └── guestStorage.ts      # localStorage 持久化（未登录用户）
│   ├── i18n/messages.ts         # zh/en 翻译字典
│   └── types/                   # api.ts / app.ts / billing.ts
│
├── backend/app/
│   ├── api/v1/endpoints/        # auth / diagram / project / schema / billing / users / health
│   ├── models/                  # User / Project / Snapshot / Subscription（4 表）
│   ├── services/                # auth / diagram / workflow_generate / schema / project / billing / user
│   ├── core/security.py         # JWT + 密码哈希
│   └── config.py                # pydantic-settings，从 .env 加载
│
├── evo_diagram/                 # AI 核心：结构提取 → 风格设计 → 布局计算 → 渲染 → 精修(可选)
│
└── wiki/                        # 本目录
```

---

## 数据流

### 图表生成（主流程）

```
用户输入 Prompt
  → HomePage navigate('/workspace', { state: { pendingGeneration: true, ... } })
  → WorkspacePage.generateDiagram()
    → apiDiagramService POST /api/v1/diagram/generate/stream (SSE)
      → 后端 WorkflowGenerateService
        → LangGraph: StructureWF → StylingWF → LayoutWF → RenderWF → [RefinerWF]
      ← SSE 事件流: stage / progress / schema_blob / thumbnail_url / refine_complete
    → 前端 canvasRef.applyPartialUpdate(schema)
    → useDiagramSync 自动 PATCH /api/v1/schema/sync
```

### Schema 同步（编辑流程）

```
用户画布编辑
  → TldrawCanvas/ExcalidrawCanvas onChange
  → useDiagramSync 检测签名变化
    → 防抖 + 飞行队列 + 抑制期(1200ms)
    → PATCH /api/v1/schema/sync { schema_patch, editor, create_snapshot: false }
      → SchemaService: 替换模式(tldraw/excalidraw) 或 JSON Merge Patch
```

### 认证流程

```
邮箱登录: POST /api/v1/auth/login → JWT
OAuth:    GET /api/v1/auth/{provider} → 302 → Provider → callback → 302 → /?token=xxx
访客:     无 auth_token → apiDiagramService 使用 VITE_GUEST_TOKEN → backendApi fallback 到 guestStorage
```

---

## 数据模型（4 表）

```
users  ──1:N──  projects  ──1:N──  snapshots
  │
  └──1:1──  subscriptions
```

| 表 | PK | 关键字段 | 说明 |
|----|-----|---------|------|
| `users` | `user_id` (UUID) | email(UK), auth_provider, password_hash | OAuth 用户 password_hash 为 NULL |
| `projects` | `project_id` (UUID) | user_id(FK), latest_schema(JSON), thumbnail_url, canvas_engine | latest_schema 存完整画布状态 |
| `snapshots` | `snapshot_id` (UUID) | project_id(FK), parent_id(自引用), schema_blob(JSON), edit_source | 版本链：parent_id → 前一快照 |
| `subscriptions` | `id` (int) | user_id(FK,UK), status, stripe_* | status: free/active/canceled/past_due |

### 已知技术债

- `parent_id` 无 FK 约束（仅文本列）
- 无 Alembic 迁移（`create_all` 不修改已有表）
- SQLite JSON 不支持 JSONB 索引
- 生产需补 3 个复合索引（见 `010_users_projects_snapshots.sql`）

---

## 核心设计决策

| 决策 | 选项 A | 选项 B（选中） | 理由 |
|------|--------|--------------|------|
| 全局状态管理 | Redux/Zustand | React Context + useState | 全局状态仅 auth + language，不需要重型库 |
| 画布同步 | 双向 WebSocket | 单向 REST（前端→后端） | MVP 阶段无实时协作需求；REST 更简单可靠 |
| 画布引擎 | 仅 TLDraw | 双引擎 + 自动检测 | 手绘/专业两种风格，Schema 结构不同需并存 |
| i18n | i18next | 自研 LanguageProvider | 仅 zh/en 两种语言，不需要 namespace/pluralization |
| 访客持久化 | 后端临时用户 | localStorage (guestStorage) | 零后端开销；30 项目×20 快照远低于 5MB 限制 |
| DB 迁移 | Alembic | create_all() | MVP 阶段表结构稳定；P1+ 需引入 Alembic |
| Schema 同步策略 | 全量替换 | 替换 + JSON Merge Patch 双模式 | tldraw/excalidraw 全量替换更安全；其他场景增量更高效 |
| Refiner 控制 | 全局开关 | 按 user_tier 动态控制 | P0 实现的 Feature Gate，Free 用户不触发 |

---

## 环境变量（必填）

| 变量 | 层 | 说明 |
|------|-----|------|
| `JWT_SECRET` | 后端 | JWT 签名密钥 |
| `SESSION_SECRET` | 后端 | Session 密钥 |
| `LLM_API_KEY` | 后端 | LLM API 密钥 |
| `LLM_ENDPOINT_URL` | 后端 | LLM API 地址 |
| `VITE_API_BASE_URL` | 前端 | 后端 API 地址（默认 `http://localhost:3010`） |
| `VITE_GUEST_TOKEN` | 前端 | 访客 Token |

完整配置项参考 `backend/app/config.py` 的 `Settings` 类。

---

## API 路由总览

```
/api/v1/
├── /health                GET     健康检查
├── /auth
│   ├── /login             POST    邮箱登录
│   ├── /register          POST    邮箱注册
│   ├── /me                GET     当前用户 (JWT)
│   ├── /google            GET     Google OAuth 跳转
│   ├── /google/callback   GET     Google OAuth 回调
│   ├── /github            GET     GitHub OAuth 跳转
│   └── /github/callback   GET     GitHub OAuth 回调
├── /diagram
│   ├── /generate          POST    AI 生成（同步）
│   └── /generate/stream   POST    AI 生成（SSE 流式）
├── /diagrams              CRUD    图表记录
├── /project/snapshot      GET     快照历史（分页）
├── /schema/sync           PATCH   Schema 同步
├── /users
│   ├── /subscription      GET     订阅信息
│   └── /profile           PUT     更新资料
└── /billing
    ├── /checkout           POST    Stripe Checkout
    ├── /portal             POST    Stripe Portal
    └── /webhooks/stripe    POST    Stripe Webhook
```

P1 将新增：`/api/v1/dna/*`（基因 CRUD + 提取）、`/api/v1/gallery/*`（公开图表 + 克隆）。
