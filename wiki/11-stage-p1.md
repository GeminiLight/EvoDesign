<!-- Last verified: 2026-03-17 | Current stage: P1 -->

# P1 — 产品核心差异化 [active]

**关联 PRD：** PRD-004 / PRD-005 / PRD-006
**目标：** 补齐产品核心差异化功能，去除所有 mock 数据依赖

---

## PRD-004：DNA 基因后端持久化与跨设备同步

### 背景与现状
- 前端 DNA 系统已完整：`YourDNAPage.tsx` 有三类基因舱（structure/style/layout）、编辑 Modal、Clone 流程
- 基因数据仅存 localStorage（`guestStorage.ts` 中 key `evodiagram_guest_dna`）
- 类型定义在 `frontend/src/types/dna.ts`，每条 Rule 含 title/preview/source/enabled/usageCount
- 后端无任何基因相关模型、API、Service

---

### TASK-004-A：后端 — 新建 user_genes 表与 ORM 模型

**负责人：** 后端
**文件：** `backend/app/models/gene.py`（新建）、`backend/app/models/__init__.py`

**具体工作：**

1. 新建 `Gene` 模型：
   ```python
   class Gene(Base):
       __tablename__ = "user_genes"
       id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
       user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id"), index=True)
       cabin: Mapped[str] = mapped_column(String(20))  # "structure" | "style" | "layout"
       title: Mapped[str] = mapped_column(String(200))
       preview: Mapped[str] = mapped_column(Text)  # 规则描述/预览文本
       source: Mapped[str] = mapped_column(String(20), default="manual")  # "ai" | "manual"
       enabled: Mapped[bool] = mapped_column(default=True)
       usage_count: Mapped[int] = mapped_column(default=0)
       created_at: Mapped[datetime] = mapped_column(server_default=func.now())
       updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
   ```

2. 在 `__init__.py` 中注册模型，确保 `init_db` 自动建表

**验收：**
- 后端启动后 `user_genes` 表自动创建
- 字段与前端 `Rule` 类型一一对应

---

### TASK-004-B：后端 — DNA CRUD API

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/dna.py`（新建）、`backend/app/schemas/dna.py`（新建）、`backend/app/services/dna_service.py`（新建）

**具体工作：**

1. Pydantic schemas：
   - `GeneCreate`: cabin, title, preview, source?, enabled?
   - `GeneUpdate`: title?, preview?, enabled?
   - `GeneResponse`: 全字段返回
   - `GeneListResponse`: List[GeneResponse]

2. Service 层：
   - `list_genes(user_id, cabin?)` — 查询用户全部基因，可按 cabin 过滤
   - `create_gene(user_id, data)` — 创建基因
   - `update_gene(user_id, gene_id, data)` — 更新基因（校验归属）
   - `delete_gene(user_id, gene_id)` — 删除基因（校验归属）
   - `increment_usage(gene_id)` — 使用次数 +1（生成时调用）

3. API endpoints：
   ```
   GET    /api/v1/dna/genes           — 获取当前用户全部基因
   POST   /api/v1/dna/genes           — 创建基因
   PATCH  /api/v1/dna/genes/{gene_id} — 更新基因
   DELETE /api/v1/dna/genes/{gene_id} — 删除基因
   ```

4. 在 `backend/app/api/v1/router.py` 中注册路由

**验收：**
- 4 个 endpoint 均可通过 Swagger 测试
- 非归属用户操作返回 403
- 匿名用户（Guest）返回 401

---

### TASK-004-C：前端 — DNA 页接通后端 API

**负责人：** 前端
**文件：** `frontend/src/services/backendApi.ts`、`frontend/src/pages/YourDNAPage.tsx`、`frontend/src/services/guestStorage.ts`

**具体工作：**

1. 在 `backendApi.ts` 新增 DNA API 调用函数：
   - `fetchGenes(): Promise<Gene[]>`
   - `createGene(data): Promise<Gene>`
   - `updateGene(id, data): Promise<Gene>`
   - `deleteGene(id): Promise<void>`

2. 修改 `YourDNAPage.tsx`：
   - 登录用户：页面加载时从后端拉取基因，所有增删改操作调用后端 API
   - Guest 用户：保持 localStorage 行为不变（降级）
   - 添加 loading/error 状态处理

3. 保留 localStorage 作为缓存层：
   - 登录用户首次同步后写入 localStorage
   - 后续优先读 localStorage，后台静默同步后端

**验收：**
- 登录用户的基因数据持久化到后端
- 刷新页面后基因不丢失
- Guest 用户行为不变

---

### TASK-004-D：后端 — 生成时加载用户活跃基因

**负责人：** 后端
**文件：** `backend/app/services/workflow_generate_service.py`、`backend/app/api/v1/endpoints/diagram.py`

**具体工作：**

1. 在 `/generate/stream` 请求处理中，查询当前用户的活跃基因（`enabled=True`）
2. 将基因规则序列化为 `design_expertise` 字符串，注入 workflow state：
   ```python
   genes = await dna_service.list_genes(user_id, enabled_only=True)
   design_expertise = format_genes_as_expertise(genes)
   # 传入 workflow 的 design_expertise 参数
   ```
3. 基因使用后调用 `increment_usage` 更新使用次数

**验收：**
- 用户设置"使用圆角矩形"基因后，生成的图表节点确实使用圆角
- 基因使用次数正确递增

---

## PRD-005：Gallery 真实内容接通

### 背景与现状
- 前端 Gallery 页（`GalleryPage.tsx`）功能完整：搜索、筛选、排序、预览 Modal、热门排行
- 数据全部来自 `galleryMockData.ts`（12 条 mock works + 6 条 mock DNA）
- 后端无公开图表 API、无 `is_public` 字段、无 Gallery 相关 Service
- 项目模型（`backend/app/models/project.py`）无 `is_public`/`tags` 字段

---

### TASK-005-A：后端 — 项目模型扩展公开字段

**负责人：** 后端
**文件：** `backend/app/models/project.py`、`backend/app/schemas/project.py`

**具体工作：**

1. 在 `Project` 模型中新增字段：
   - `is_public: Mapped[bool] = mapped_column(default=False)`
   - `tags: Mapped[str | None] = mapped_column(Text)` — JSON 数组字符串，如 `'["fintech","architecture"]'`
   - `like_count: Mapped[int] = mapped_column(default=0)`
   - `clone_count: Mapped[int] = mapped_column(default=0)`

2. 在 `ProjectListItem` / `ProjectDetailResponse` schema 中添加对应字段

3. 在 `PATCH /api/v1/projects/{id}` 中允许更新 `is_public` 和 `tags`

**验收：**
- 数据库 migration 正常执行
- 项目可被设为公开/私有

---

### TASK-005-B：后端 — Gallery 公开图表 API

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/gallery.py`（新建）、`backend/app/services/gallery_service.py`（新建）

**具体工作：**

1. Service 层：
   - `search_public_works(query?, tags?, complexity?, sort_by?, page?, page_size?)` — 搜索公开图表
   - `get_public_work(project_id)` — 获取单个公开图表详情
   - `like_work(user_id, project_id)` — 点赞
   - `clone_work(user_id, project_id)` — 克隆到用户工作台

2. API endpoints：
   ```
   GET  /api/v1/gallery/works                — 搜索公开图表（支持分页、筛选、排序）
   GET  /api/v1/gallery/works/{id}           — 获取公开图表详情
   POST /api/v1/gallery/works/{id}/like      — 点赞
   POST /api/v1/gallery/works/{id}/clone     — 克隆到我的项目
   GET  /api/v1/gallery/dna                  — 公开 DNA 基因模板列表
   POST /api/v1/gallery/dna/{id}/clone       — 克隆基因到我的 DNA
   ```

3. 热门排行：`GET /api/v1/gallery/works?sort_by=like_count&limit=10`

**验收：**
- 无需认证即可浏览公开图表
- 克隆操作需要认证
- 分页、筛选、排序均可用

---

### TASK-005-C：前端 — Gallery 去 mock，接通真实 API

**负责人：** 前端
**文件：** `frontend/src/pages/GalleryPage.tsx`、`frontend/src/services/backendApi.ts`

**具体工作：**

1. 在 `backendApi.ts` 新增 Gallery API 调用函数：
   - `fetchPublicWorks(params): Promise<{ items, total }>`
   - `fetchPublicDna(params): Promise<{ items, total }>`
   - `likeWork(id): Promise<void>`
   - `cloneWork(id): Promise<Project>`
   - `cloneDna(id): Promise<Gene>`

2. 重构 `GalleryPage.tsx`：
   - 删除 `galleryMockData.ts` 的 import
   - 改为调用真实 API，添加 loading/error/empty 状态
   - 搜索/筛选参数传给后端，不在前端过滤
   - 热门排行调用 `sort_by=like_count` 接口

3. 添加"设为公开"入口：
   - 在 WorkspacePage 项目菜单中新增"Publish to Gallery"选项
   - 调用 `PATCH /api/v1/projects/{id}` 设置 `is_public=true`

**验收：**
- Gallery 页无 mock 数据依赖
- `galleryMockData.ts` 文件可安全删除
- 空 Gallery 状态显示引导文案而非空白

---

### TASK-005-D：前端 — 项目详情页"设为公开"功能

**负责人：** 前端
**文件：** `frontend/src/pages/WorkspacePage.tsx`、`frontend/src/components/`

**具体工作：**

1. 在工作台项目菜单或侧栏中新增"Publish to Gallery"开关
2. 公开后显示分享链接和 Gallery 中的浏览量/点赞数
3. 可随时取消公开

**验收：**
- 用户可将自己的项目设为公开
- 公开的项目出现在 Gallery 搜索结果中

---

## PRD-006：DNA Cloning 真实提取流程

### 背景与现状
- 前端 Clone 流程 UI 完整（`YourDNAPage.tsx` 的 Clone Modal）
- 提取候选规则全部硬编码，与项目内容无关
- 后端无基因提取 Agent / API

---

### TASK-006-A：后端 — 基因提取 Agent Service

**负责人：** 后端
**文件：** `backend/app/services/dna_extract_service.py`（新建）

**具体工作：**

1. 新建 `DnaExtractService`：
   - 输入：项目 ID（或多个快照的 schema_blob 列表）
   - 过程：调用 LLM 分析项目结构/风格/布局特征，提取 3-5 条候选基因规则
   - 输出：`List[CandidateRule]`，每条含 cabin/title/preview/confidence

2. Prompt 设计要点：
   - 对比项目的多个快照，识别一致性模式
   - 分三类输出：结构规则、风格规则、布局规则
   - 每条规则附带可操作的描述（如"使用 12px 间距"而非"间距合理"）

3. 异步执行：提取可能耗时 10-30 秒，返回 task_id，前端轮询结果

**验收：**
- 对不同项目提取，候选规则内容不同
- 规则描述与项目实际设计特征相符
- 超时或失败时返回错误信息，不阻断其他功能

---

### TASK-006-B：后端 — 基因提取 API

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/dna.py`（扩展）

**具体工作：**

1. 新增 endpoints：
   ```
   POST /api/v1/dna/extract              — 触发基因提取（异步）
     Body: { project_id: string }
     Response: { task_id: string }

   GET  /api/v1/dna/extract/{task_id}    — 查询提取结果
     Response: { status: "pending"|"done"|"failed", candidates?: CandidateRule[] }
   ```

2. 使用 asyncio.Task 或后台任务队列管理异步提取

**验收：**
- 提交提取请求后立即返回 task_id
- 轮询 task_id 可获取最终结果
- 提取完成后候选规则包含 cabin/title/preview

---

### TASK-006-C：前端 — Clone Modal 接通真实提取

**负责人：** 前端
**文件：** `frontend/src/pages/YourDNAPage.tsx`

**具体工作：**

1. Clone Modal 中"Extract from Project"按钮：
   - 调用 `POST /api/v1/dna/extract` 触发提取
   - 显示加载动画（"Agent 正在分析项目设计模式..."）
   - 轮询 `GET /api/v1/dna/extract/{task_id}` 获取结果

2. 候选规则列表：
   - 删除硬编码 mock 数据
   - 渲染后端返回的真实候选规则
   - 每条规则显示 Accept/Reject 按钮

3. Accept 操作：调用 `POST /api/v1/dna/genes` 创建基因（复用 TASK-004-B API）

**验收：**
- 选择不同项目提取时，候选规则内容不同
- Accept 后基因出现在 DNA 页对应 cabin 中
- 提取失败时显示友好错误信息

---

## 任务依赖关系

```
PRD-004 (DNA 持久化)
  TASK-004-A (模型建表)
      └── TASK-004-B (CRUD API)
              ├── TASK-004-C (前端接通)
              └── TASK-004-D (生成时加载基因)

PRD-005 (Gallery 真实内容)
  TASK-005-A (模型扩展)
      └── TASK-005-B (Gallery API)
              ├── TASK-005-C (前端去 mock)
              └── TASK-005-D (设为公开功能)

PRD-006 (DNA Cloning)
  依赖 TASK-004-B (基因 CRUD API)
  TASK-006-A (提取 Agent Service)
      └── TASK-006-B (提取 API)
              └── TASK-006-C (前端 Clone 接通)
```

---

## 开发顺序建议

| 顺序 | 任务 | 方向 | 理由 |
|------|------|------|------|
| 1 | TASK-004-A | 后端 | 建表，所有 DNA 任务的基础 |
| 1 | TASK-005-A | 后端 | 扩展模型，Gallery 任务的基础 |
| 2 | TASK-004-B | 后端 | DNA CRUD API，前端和提取都依赖 |
| 2 | TASK-005-B | 后端 | Gallery API |
| 3 | TASK-004-C | 前端 | DNA 页接通 |
| 3 | TASK-005-C | 前端 | Gallery 去 mock |
| 3 | TASK-006-A | 后端 | 提取 Agent（可与前端并行） |
| 4 | TASK-004-D | 后端 | 生成集成基因 |
| 4 | TASK-005-D | 前端 | 设为公开 |
| 4 | TASK-006-B | 后端 | 提取 API |
| 5 | TASK-006-C | 前端 | Clone 接通 |
