# Diagram Design Memory

该目录维护 EvoDesign 的图表设计知识库：把 guidelines、principles、samples、strategies 写入 Chroma 向量库，并为生成 pipeline 提供检索接口。

## 主要文件

- `memory_workflow.py`：从 JSON 知识文件批量导入 Chroma，并执行基本检索 smoke test。
- `diagram_design_memory.py`：向量库读写、版本化、生命周期和统计。
- `diagram_design_retriever.py`：跨知识层检索、过滤、rerank 和降级标记。
- `utils/format_memory.py`：检索结果展示辅助函数。

## JSON 输入

`MemoryStorageWorkflow` 默认从指定目录读取以下文件：

- `guideline.json`
- `principle.json`
- `samples.json`
- `strategy.json`

每个文件支持两种格式：

```json
[
  {
    "id": "guideline_auth_grouping",
    "title": "Group related auth nodes",
    "content": "Authentication-related nodes should be clustered together.",
    "tags": {
      "domain": ["architecture"],
      "diagram_type": ["class"]
    }
  }
]
```

或：

```json
{
  "guideline": [
    {
      "title": "Group related auth nodes",
      "content": "Authentication-related nodes should be clustered together."
    }
  ]
}
```

导入边界会做 fail-fast 校验：

- 每个 item 必须是 JSON object。
- 缺失、空字符串或 `null` ID 会按内容生成稳定 hash ID。
- 同一文件内重复 ID 会在写入 Chroma 前失败。
- `design_type` 如显式提供，必须与文件层级一致；最终以文件层级为准写入。
- `tags` 缺失会规范化为 `{}`；存在时必须是 object。
- `domain`、`diagram_type`、`source`、`agent` 等 tags 字段必须是 `list[str]`。
- 至少需要 `title`、`content`、`description`、`when_to_use` 中一个非空文本字段。

## 运行

从仓库根目录运行：

```bash
python -m evo_diagram.design_memory.memory_workflow
```

默认配置来自 `evo_diagram.config.settings.AppSettings`。常用环境变量：

- `DESIGN_MEMORY_VECTOR_DB_PATH`：ChromaDB 持久化目录。
- `DESIGN_MEMORY_EMBEDDING_MODEL`：HuggingFace embedding 模型。
