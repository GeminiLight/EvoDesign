<!-- Last verified: 2026-03-17 | Current stage: P1 | Status: ✅ completed -->

# P0 — 核心体验闭环 [completed]

**关联 PRD：** PRD-001 / PRD-002 / PRD-003
**目标：** 打通核心体验闭环
**完成日期：** 2026-03-09

---

## PRD-001：图表缩略图生成与展示

### 背景与现状
- `projects` 表已有 `thumbnail_url` 字段（`backend/app/models/project.py:31`），但从未被写入
- 生成结果的 `schema_blob` 已存入 DB，包含完整节点/边数据，足以渲染缩略图
- 前端卡片在 `HomePage.tsx:278-289` 和 `DashboardPage.tsx` 用 Emoji 占位

---

### TASK-001-A：后端 — 生成后自动渲染并存储缩略图

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/diagram.py`、`backend/app/services/`

**具体工作：**

1. 新建 `ThumbnailService`（`backend/app/services/thumbnail_service.py`）
   - 接收 `schema_blob`（excalidraw 或 tldraw 格式）和 `canvas_engine`
   - 使用 Playwright headless 或 excalidraw-utils 将 schema 渲染为 PNG（建议 400×300px）
   - 上传至对象存储（Supabase Storage / S3），返回公开 URL

2. 在 `_persist_result` 函数（`diagram.py:22-74`）中接入：
   ```python
   # 在 project.latest_schema 赋值后追加
   thumbnail_url = await thumbnail_service.render(
       schema_blob=workflow_result["schema_blob"],
       canvas_engine=canvas_engine
   )
   project.thumbnail_url = thumbnail_url
   ```

3. 流式接口（`/generate/stream`）在 SSE 最后一条事件中附带 `thumbnail_url`，供前端实时更新

**验收：**
- 新生成项目的 `projects.thumbnail_url` 非空
- 缩略图包含节点文字（非纯色块）
- 渲染失败时静默降级（`thumbnail_url = null`），不阻断主流程

---

### TASK-001-B：后端 — 项目列表 API 返回 thumbnail_url

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/project.py`

**具体工作：**

1. 检查 `GET /api/v1/projects` 和 `GET /api/v1/projects/{project_id}` 的响应 schema
2. 确认 `ProjectResponse` Pydantic model 包含 `thumbnail_url: str | None` 字段
3. 若缺失，添加该字段并确保 ORM 映射正确返回

**验收：**
- `GET /api/v1/projects` 响应中每个项目含 `thumbnail_url`（可为 null）

---

### TASK-001-C：前端 — 项目卡片渲染真实缩略图

**负责人：** 前端
**文件：** `frontend/src/pages/HomePage.tsx:278-289`、`frontend/src/pages/DashboardPage.tsx`

**具体工作：**

1. **替换 Emoji 占位符**（`HomePage.tsx:278-289`）：
   ```tsx
   // 删除现有 Emoji 块，替换为：
   {project.thumbnail_url ? (
     <img
       src={project.thumbnail_url}
       alt={project.title}
       className="h-full w-full object-cover object-top"
     />
   ) : (
     // 骨架屏：灰色渐变矩形，无 Emoji
     <div className="h-full w-full animate-pulse bg-gradient-to-br from-slate-100 to-slate-200" />
   )}
   ```

2. **DashboardPage** 同步替换相同逻辑

3. **流式生成完成后实时更新缩略图**：
   - SSE 最后事件含 `thumbnail_url` 时，更新对应项目卡片（无需重新拉取列表）

**验收：**
- 有缩略图的项目显示真实预览图
- 无缩略图（null）的项目显示骨架屏动画，不显示任何 Emoji
- 生成完成后首页卡片自动更新，无需刷新页面

---

## PRD-002：Agent 聊天局部编辑接通

### 背景与现状
- 前端 `handleSendChatMessage`（`WorkspacePage.tsx:428-433`）仅追加假消息，无任何 API 调用
- 后端 `/api/v1/diagram/generate` 已支持 `locked_nodes` + `current_schema` 参数，可实现增量编辑（`workflow.py:241-246`）
- **不需要新增 API endpoint**，复用现有 generate/stream 接口即可

---

### TASK-002-A：后端 — 确认并暴露局部编辑参数

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/diagram.py`、`backend/app/schemas/`

**具体工作：**

1. 检查 `/api/v1/diagram/generate/stream` 的请求 schema，确认以下字段已在 Pydantic model 中定义且被传入 workflow：
   - `current_schema`: 当前画布完整 schema（JSON）
   - `locked_nodes`: 不允许修改的节点 ID 列表（`list[str]`）
   - `user_query`: 用户自然语言指令

2. 若字段缺失，在请求 schema 中补充，并在 `workflow.py` 的 `playbook` 构建处（lines 241-246）确保正确传入

3. 保持模式边界在 endpoint 层：全局生成使用 `/generate/stream`，局部编辑使用 `/edit-local`，不要在生成请求里加入 `edit_mode`

**验收：**
- `POST /api/v1/diagram/generate/stream` 接受 `current_schema` + `locked_nodes`
- `POST /api/v1/diagram/edit-local` 接受 `current_schema` + `selected_node_ids` + `instruction`
- 传入 `locked_nodes` 后，workflow 不修改这些节点的位置和样式

---

### TASK-002-B：前端 — 实现局部编辑发送逻辑

**负责人：** 前端
**文件：** `frontend/src/pages/WorkspacePage.tsx:428-433`

**具体工作：**

1. **替换 `handleSendChatMessage`**，接入真实 streaming API：

   ```ts
   const handleSendChatMessage = useCallback(async () => {
     const content = chatInput.trim();
     if (!content || isGenerating) return;

     // 1. 追加用户消息到 UI
     setChatMessages(prev => [...prev, { id: createId('msg'), role: 'user', content }]);
     setChatInput('');

     // 2. 获取当前画布 schema 和选中节点
     const currentSchema = canvasRef.current?.getSchema();
     const lockedNodes = getUnselectedNodeIds(currentSchema, selectedNodeIds);

     // 3. 有选区时调用 /edit-local；无选区时调用 streaming generate
     if (selectedNodeIds.length > 0) {
       await apiDiagramService.editDiagramLocal({
         current_schema: currentSchema,
         selected_node_ids: selectedNodeIds,
         instruction: content,
         canvas_library: currentCanvasEngine,
         project_id: currentProject?.id,
       });
       return;
     }

     await apiDiagramService.generateStream({
       user_query: content,
       current_schema: currentSchema,
       locked_nodes: lockedNodes,
       diagram_type: currentProject?.diagram_type,
       canvas_engine: currentCanvasEngine,
       project_id: currentProject?.id,
     }, {
       onStageUpdate: (stage) => {
         // 复用现有思考流 UI 更新逻辑
         setAgentStages(stage);
       },
       onComplete: (result) => {
         // 增量更新画布：仅替换未锁定区域
         canvasRef.current?.applyPartialUpdate(result.schema_blob, lockedNodes);
         setChatMessages(prev => [...prev, {
           id: createId('msg'), role: 'agent',
           content: `已完成：${result.summary ?? '图表已更新'}`
         }]);
       },
       onError: (err) => {
         setChatMessages(prev => [...prev, { id: createId('msg'), role: 'agent', content: `出错了：${err}` }]);
       }
     });
   }, [chatInput, isGenerating, selectedNodeIds, currentProject, currentCanvasEngine]);
   ```

2. **实现 `canvasRef.applyPartialUpdate(schema, lockedNodes)`**：
   - 对 TLDraw：仅 upsert schema 中 `id` 不在 `lockedNodes` 的元素，其余保留
   - 对 Excalidraw：同理，按 `id` 过滤合并

**验收：**
- 用户在聊天框输入指令并发送后，画布真实更新
- 用户选中某节点后发指令，其他节点位置不变
- 执行过程中思考流正常展示（复用现有 UI）
- 执行失败时 chat 面板显示错误信息，画布不变

---

### TASK-002-C：前端 — 聊天面板 UI 死区修复

**负责人：** 前端
**文件：** `frontend/src/components/Workspace/AgentChatPanel.tsx`

**具体工作：**（参考 `page_review.md` Workspace P1）

1. Agent 状态消息改为顶部小型 Badge，不占大面积空间
2. Quick Prompt Chips 紧接 Badge 下方展示（而非沉底）
3. Chips 样式改为 pill button：`rounded-full border border-slate-200 bg-white/50 px-3 py-1.5 text-xs font-medium hover:bg-brand-50`

**验收：**
- 聊天面板无大面积空白区域
- Chips 视觉上明显可点击

---

## PRD-003：精修 Agent 开启与状态 UI

### 背景与现状
- Refiner 代码完整，在两处被硬编码关闭：
  - `workflow_generate_service.py:100`（streaming）
  - `workflow_generate_service.py:254`（non-streaming）
  - `backend/app/config.py:77`（配置默认值）
- 当前无任何 tier-based feature gating 机制
- Refiner 需要 `save_dir` 参数才能运行（`workflow.py:313`）

---

### TASK-003-A：后端 — 基于订阅 tier 的 Feature Gate

**负责人：** 后端
**文件：** `backend/app/services/workflow_generate_service.py`、`backend/app/models/`

**具体工作：**

1. 在 `workflow_generate_service.py` 中读取用户 tier：
   ```python
   # 当前 billing contract 只开放 pro；enterprise 需要明确 price mapping 后再接入
   user_tier = await get_user_tier(user_id)  # 返回 None | "pro"
   enable_refiner = user_tier == "pro"
   refiner_max_iterations = 1
   ```

2. 匿名用户（`user_id=None`）：`enable_refiner=False`

3. 为 Refiner 提供临时 `save_dir`（可用 `/tmp/{request_id}/`）

**验收：**
- Pro 用户请求生成时，`enable_refiner=True`
- Free/匿名用户 `enable_refiner=False`，行为与现在一致

---

### TASK-003-B：后端 — SSE 流中增加精修阶段事件

**负责人：** 后端
**文件：** `backend/app/api/v1/endpoints/diagram.py`（streaming handler）

**具体工作：**

1. 在 streaming 生成的 SSE 事件序列中，精修阶段发送新的 stage 事件：
   ```json
   { "type": "stage", "stage": "refining", "message": "精修 Agent 正在修复视觉冲突..." }
   ```

2. 精修完成后发送结果事件：
   ```json
   {
     "type": "refine_complete",
     "fixes_applied": 3,
     "message": "已自动修复 3 处视觉冲突"
   }
   ```

3. Pro 用户但 Refiner 出错时，静默降级，返回未精修结果，不报错

**验收：**
- Pro 用户生成时，前端 SSE 流中可接收到 `refining` 阶段事件
- `refine_complete` 事件包含 `fixes_applied` 数量

---

### TASK-003-C：前端 — 思考流新增精修阶段 + 完成提示

**负责人：** 前端
**文件：** `frontend/src/components/Workspace/`（思考流相关组件）

**具体工作：**

1. 在现有 Agent 思考流 UI 中新增第 5 阶段"精修"：
   - 图标：✨ 或魔法棒
   - 状态：`pending` / `running` / `done` / `skipped`（Free 用户为 `skipped`）

2. 精修完成后，在 Agent 聊天面板顶部短暂展示 Toast：
   - Pro 用户："✨ 已自动修复 N 处视觉冲突"
   - Free 用户（精修阶段显示 skipped）："升级 Pro 解锁自动精修 →"（可点击跳转升级页）

3. Free 用户精修阶段显示为灰色锁定态，不影响其他 4 个阶段的正常展示

**验收：**
- Pro 用户可在思考流中看到第 5 阶段运行
- Free 用户可见精修阶段但显示锁定态，并有升级引导
- 精修完成后 Toast 3 秒后自动消失

---

## 任务依赖关系

```
PRD-001
  TASK-001-A (后端缩略图生成)
      └── TASK-001-B (API 返回 thumbnail_url)
              └── TASK-001-C (前端卡片渲染) ← 可与 001-A 并行开发，用 null 兜底

PRD-002
  TASK-002-A (后端确认参数) ← 先做，确认接口
      └── TASK-002-B (前端接入真实 API)
  TASK-002-C (UI 优化) ← 独立，可随时做

PRD-003
  TASK-003-A (后端 Feature Gate) ← 先做
      └── TASK-003-B (SSE 精修事件)
              └── TASK-003-C (前端精修 UI)
```

---

## 开发顺序建议

| 顺序 | 任务 | 方向 | 理由 |
|------|------|------|------|
| 1 | TASK-002-A | 后端 | 确认接口契约，前端可同步开工 |
| 1 | TASK-001-A | 后端 | 最重工作，需要最多时间 |
| 1 | TASK-003-A | 后端 | 独立，快 |
| 2 | TASK-001-B | 后端 | 依赖 001-A 完成 |
| 2 | TASK-003-B | 后端 | 依赖 003-A 完成 |
| 2 | TASK-001-C | 前端 | 001-A 开始后即可并行，用 null 兜底骨架屏 |
| 2 | TASK-002-B | 前端 | 依赖 002-A 接口确认 |
| 2 | TASK-002-C | 前端 | 独立 UI，任意时间 |
| 3 | TASK-003-C | 前端 | 依赖 003-B SSE 事件 |

---

## 实施状态

> 更新时间：2026-03-09

### 总览

| 任务 | 状态 | 实施方式 |
|------|------|----------|
| TASK-001-A | ✅ 已完成 | 已有实现：`diagram.py` 的 `_persist_result` 中生成并存储 `thumbnail_url` |
| TASK-001-B | ✅ 已完成 | 已有实现：`ProjectListItem` / `ProjectDetailResponse` schema 已含 `thumbnail_url` 字段 |
| TASK-001-C | ✅ 已完成 | 已有实现：`HomePage.tsx` 用 `<img>` / skeleton 渲染缩略图，SSE `thumbnail_url` 实时更新卡片 |
| TASK-002-A | ✅ 已完成 | 已有实现：`/generate/stream` 已接受 `locked_nodes` + `current_schema`，局部编辑由 `/edit-local` 承接 |
| TASK-002-B | ✅ 已完成 | 已有实现：`WorkspacePage.tsx` 的 `handleSendChatMessage` 会按选区路由到 `editDiagramLocal()` 或全局 `generateDiagram()` |
| TASK-002-C | ✅ 已完成 | **本次实现**：重构 `AgentChatPanel.tsx` — badge 式 header、pill 式 chips、消除空白死区 |
| TASK-003-A | ✅ 已完成 | 已有实现：`_refiner_params()` 根据当前 billing tier 控制 `enable_refiner` / `refiner_max_iterations`；当前只开放 Pro |
| TASK-003-B | ✅ 已完成 | **本次实现**：在 `workflow_generate_service.py` 中为 Free 用户新增 `refiner_skipped` SSE 事件 |
| TASK-003-C | ✅ 已完成 | **本次实现**：`StageProgress.tsx` 新增 Lock 图标 + 删除线 + "Pro" 标签；`useGenerateDiagram` / `apiDiagramService` 新增 `onRefinerSkipped` 回调 |

### 本次变更文件清单

**后端：**
- `backend/app/services/workflow_generate_service.py` — 新增 `refiner_skipped` SSE 事件（Free 用户）

**前端：**
- `frontend/src/types/app.ts` — `GenerationProgress` 新增 `refinerSkipped?: boolean`
- `frontend/src/types/api.ts` — `DiagramRequest` 新增 `lockedNodes?: string[]`
- `frontend/src/services/apiDiagramService.ts` — `StreamCallbacks` 新增 `onRefinerSkipped`；SSE 解析新增 `refiner_skipped` case；`locked_nodes` 从 `request.lockedNodes` 传入
- `frontend/src/hooks/useGenerateDiagram.ts` — 新增 `onRefinerSkipped` handler
- `frontend/src/components/StageProgress.tsx` — 精修阶段显示 Lock 锁定态 + "Pro" 标签（Free 用户）
- `frontend/src/components/Workspace/AgentChatPanel.tsx` — header 改为 badge 样式、chips 改为 pill 按钮、消除空白区域
- `frontend/src/components/DiagramCanvas/DiagramCanvasPanel.tsx` — 透传 `onSelectionChange` prop
- `frontend/src/components/TldrawCanvas/TldrawCanvas.tsx` — 新增选区变更监听（独立 `session` scope listener，防止无限渲染）
- `frontend/src/components/ExcalidrawCanvas.tsx` — 新增选区变更监听（带 diff 比较，防止无限渲染）
- `frontend/src/pages/WorkspacePage.tsx` — `selectedNodeIds` state + `getAllNodeIds` 局部编辑逻辑
- `frontend/src/utils/app.ts` — 新增 `getAllNodeIds()` 工具函数

### 修复的 Bug

- **无限渲染循环**：`onSelectionChange` 回调在 TldrawCanvas/ExcalidrawCanvas 中每次 store 变更都生成新数组引用，触发父组件 re-render 形成死循环。修复方案：TLDraw 使用独立 `session` scope listener + 选区 diff 比较；Excalidraw 同样增加选区 diff 比较，仅在选区实际变化时触发回调。
