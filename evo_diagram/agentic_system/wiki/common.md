# Common 模块

所有生成阶段 Agent 共享的基础设施。

## 文件列表

| 文件 | 用途 |
|------|------|
| `skill_loader.py` | 加载 `EVODIAGRAM_SKILL_SYSTEM_PROMPT` — 所有生成 Agent 共用的系统提示词 |
| `task_prompts.py` | 任务提示词模板和构建函数 |
| `domain_knowledge_loader.py` | 从 `system_prompt/` 加载领域知识，注入到 Agent 提示词中 |
| `base_workflow.py` | LangGraph 工作流编排基类 |
| `workflow_state_base.py` | 工作流状态 Pydantic 基类 |
| `spec_utils.py` | Spec 解析工具 |
| `tldraw_utils.py` | TLDraw 专用工具函数 |
| `self_consistency.py` | 自一致性校验工具 |

## 共享系统提示词

所有生成 Agent（Structure、Styling、Layout、Unified）共用一个系统提示词，由 `skill_loader.py` 加载。确保各阶段 Agent 在相同的认知框架下工作，减少阶段间的语义漂移。各 Agent 的任务提示词（task prompt）不同，但系统级约束一致。

## BaseAgent

所有 LLM Agent 继承自 `core/base_agent.py`（位于 `evo_diagram/core/base_agent.py`），提供：

- LLM 调用封装，tenacity 重试（最多 5 次，指数退避）
- JSON 输出解析
- 统一的错误处理
- 通过 `LLMFactory` 实现 provider 无关接口

## 领域知识

`domain_knowledge_loader.py` 从 `system_prompt/type_patterns/*.md`、`palette_catalog/`、`diagram_type_digest.md`、`palette_digest.md` 等文件读取阶段知识，按当前 diagram type 和 stage 注入到 Agent 提示词中。
