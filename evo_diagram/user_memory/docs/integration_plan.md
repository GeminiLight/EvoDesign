# User Memory 集成计划

## 概述

将 `user_memory/` 模块集成到 `agentic_system/`，通过参数控制启用。

---

## 已完成

### Phase 1: CLI 学习模式 ✅

**修改文件**: `agentic_system/main.py`

新增参数:
- `--learn-from-edit` - 学习模式开关
- `--enable-user-memory` - 生成时启用记忆
- `--user-id` - 用户ID（默认: default_user）
- `--session-id` - 会话ID（默认: 自动生成）
- `--memory-db-path` - 数据库路径
- `--task-json`, `--model-manifest`, `--model-image`, `--user-manifest`, `--user-image` - 学习模式专用

### Phase 2: 生成时检索记忆 ✅

**修改文件**: `agentic_system/workflow.py`

- 新增 `enable_user_memory`, `user_id` 参数
- 新增 `_retrieve_user_preferences()` 方法（支持按类别检索）
- 检索到的偏好注入 `design_expertise`

### Phase 2.5: 分阶段偏好注入 ✅

**修改文件**:
- `agentic_system/workflow.py` - 按阶段分别检索对应类别偏好
- `agentic_system/generation_stage/styling/styling_agent.py` - 传递 design_expertise 到 prompt
- `agentic_system/generation_stage/styling/prompts.py` - 添加 design_expertise 占位符
- `agentic_system/generation_stage/layout/layout_agent.py` - 传递 design_expertise 到 prompt
- `agentic_system/generation_stage/layout/prompts.py` - 添加 design_expertise 占位符

**实现逻辑**:
- Structure 阶段: 仅注入 `agent_category="Structure"` 的偏好
- Styling 阶段: 仅注入 `agent_category="Styling"` 的偏好
- Layout 阶段: 仅注入 `agent_category="Layout"` 的偏好

---

## 文件变更清单

| 文件 | 状态 | 变更 |
|------|------|------|
| `agentic_system/main.py` | ✅ 已修改 | 添加 user-memory 参数 |
| `agentic_system/workflow.py` | ✅ 已修改 | 添加记忆检索逻辑，分阶段注入 |
| `agentic_system/generation_stage/styling/styling_agent.py` | ✅ 已修改 | 传递 design_expertise |
| `agentic_system/generation_stage/styling/prompts.py` | ✅ 已修改 | 添加偏好注入占位符 |
| `agentic_system/generation_stage/layout/layout_agent.py` | ✅ 已修改 | 传递 design_expertise |
| `agentic_system/generation_stage/layout/prompts.py` | ✅ 已修改 | 添加偏好注入占位符 |
| `user_memory/storage/mem0_storage.py` | ✅ 已修改 | 使用 ChromaDB + HuggingFace 嵌入 |
| `user_memory/main.py` | ✅ 已修改 | 增加 max_tokens，改进 prompt 格式 |
| `utils/llm_output.py` | ✅ 已修改 | JSON 解析支持 markdown 代码块 |
| `config/default.yaml` | ✅ 已修改 | 添加 user_memory 配置 |

---

## 待实现

详见 [future_features.md](future_features.md)
