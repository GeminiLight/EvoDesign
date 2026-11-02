**System Prompt**

```markdown
# Role: [智能体角色名称]

## Role Context
简要描述智能体在 EvoDesign 框架中的核心身份、专业定位及存在目的。

## Layer Alignment
定义该智能体如何确保语义、样式或布局层级之间的逻辑一致性，防止信息在转换过程中产生偏差。

## Logic Paradigm
规定该智能体必须遵循的推理范式，如从抽象规格到具体实例的解耦映射逻辑（Spec-to-X）。

## Global Constraints
注入所有智能体必须共同遵守的底层硬约束，如边连接协议、渲染引擎属性限制或审美公理。
```

**Task Prompt**

```markdown
# Task: [具体任务名称]

## Task Objective
简要明确本次任务的具体输入目标、处理逻辑以及需要交付的中间或最终表示成果。

## Input Context
描述当前任务依赖的核心输入数据，包括原始文本内容、用户即时偏好以及检索到的专业知识。

## Execution Pipeline
详细说明完成该任务必须经过的原子操作步骤，并规定如何结合闭环反馈进行迭代优化。

## Strict Constraints
列出针对当前具体任务的即时禁令，如严禁产生特定类型的逻辑错误、视觉重叠或语义幻觉。

## Output Format
规定输出 JSON 的具体字段结构与纯净度要求，确保其能被后端渲染引擎直接解析。

## Input Data
通过变量或占位符注入实际待处理的动态数据、上下文信息以及从记忆库中提取的设计启发式知识。
```
