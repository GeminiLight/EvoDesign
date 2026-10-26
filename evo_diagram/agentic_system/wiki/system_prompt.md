# System Prompt 知识库

位于 `system_prompt/`。当前提示词体系由一个稳定的共享系统提示词、类型知识切片、调色板切片和少量按需参考组成；旧的多文件 legacy prompt 已移除。

## 文件列表

| 文件 | 用途 |
|------|------|
| `evodiagram_prompt.md` | 所有生成 Agent 共用的基础系统提示词 |
| `diagram_type_digest.md` | 支持的 diagram family 摘要，拼进共享系统提示词 |
| `palette_digest.md` | 可用 palette 摘要，拼进共享系统提示词 |
| `type_patterns/*.md` | 按 diagram type 拆分的 Structure / Styling / Layout 阶段知识 |
| `palette_catalog/*.md` | Styling 阶段按 palette key 注入的完整调色板卡片 |
| `group_containment_reference.md` | architecture Structure 阶段按需注入的 group containment 参考 |

## 加载机制

`common/skill_loader.py` 读取 `evodiagram_prompt.md`，并追加 `diagram_type_digest.md`、`palette_digest.md`，构建 `EVODIAGRAM_SKILL_SYSTEM_PROMPT` 常量。这是注入到每个生成 Agent 的共享系统提示词。

`common/domain_knowledge_loader.py` 读取 `type_patterns/*.md` 并按当前 diagram type / stage 生成阶段知识；architecture 的 Structure 阶段额外读取 `group_containment_reference.md`。

## 集成方式

Agent 提示词引用这些知识源：

1. **系统提示词**（来自 `evodiagram_prompt.md` + digest）— 定义 Agent 角色、约束、输出格式规则和可用类型/调色板边界
2. **类型知识**（来自 `type_patterns/*.md`）— 当前 diagram type 的阶段规则
3. **任务提示词**（来自 `{workflow}/prompts.py`）— 具体任务指令

分层提示词架构确保一致性：所有 Agent 共享相同的系统级框架，同时拥有各自的任务特定指令。
