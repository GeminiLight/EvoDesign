# programmic 目录说明

## 概述

`programmic` 目录包含基于程序化方法的文本到图表生成基线实现。这些实现使用大语言模型（LLM）直接生成结构化的图表代码（如 Mermaid、TiKZ、DOT 等），而不是生成图像或 JSON 格式的图表描述。

## 目录结构

```
programmic/
├── merid/           # Mermaid 图表生成基线
│   ├── run_mermaid_agent.py
│   └── experiments/{exp_id}/outputs/
└── tlzl/            # TiKZ/DOT 图表生成基线
    ├── code_agent.py
    └── experiments/{exp_id}/outputs/
```

## 子目录说明

### 1. merid/ - Mermaid 图表生成

**功能**：使用 LLM 生成 Mermaid 流程图代码

**主要文件**：
- `run_mermaid_agent.py` - 主运行脚本

**技术栈**：
- 模型：iflow/qwen3-vl-plus（通过 iflow API）
- 输出格式：Mermaid 流程图代码

**使用方法**：

```bash
# 数据集模式（推荐）
python run_mermaid_agent.py --dataset /path/to/dataset.json

# 单输入模式
python run_mermaid_agent.py --input "您的文本内容"

# 限制处理数量
python run_mermaid_agent.py --dataset /path/to/dataset.json --limit 10
```

**数据集格式**：
```json
[
  {
    "id": "xxx",
    "content": "文本内容"
  }
]
```

**输出**：
- 结果保存在 `experiments/{exp_id}/outputs/` 目录
- 文件命名格式：`{id}_{model_name}.json`
- JSON 格式包含：input、output、timestamp、model

**特性**：
- 支持从文本生成 Mermaid 流程图
- 自动识别关键概念和关系
- 使用适当的节点形状（矩形、菱形、圆形等）
- 支持使用 subgraph 分组相关概念

---

### 2. tlzl/ - TiKZ/DOT 图表生成

**功能**：使用 DiagramAgent/Code_Agent 模型生成 TiKZ 和 DOT 代码

**主要文件**：
- `code_agent.py` - 主运行脚本

**技术栈**：
- 模型：DiagramAgent/Code_Agent（本地缓存）
- 模型路径：`/mnt/data/.cache/huggingface`
- 输出格式：TiKZ（LaTeX）或 DOT（Graphviz）代码

**使用方法**：

```bash
# 数据集模式（推荐）
python code_agent.py --dataset /path/to/dataset.json

# 单输入模式
python code_agent.py --input "您的文本内容"

# 限制处理数量
python code_agent.py --dataset /path/to/dataset.json --limit 10

# 自定义最大 token 数
python code_agent.py --dataset /path/to/dataset.json --max-tokens 16384
```

**数据集格式**：
```json
[
  {
    "id": "xxx",
    "content": "文本内容"
  }
]
```

**输出**：
- 结果保存在 `experiments/{exp_id}/outputs/` 目录
- 文件命名格式：`{id}_{model_name}.json`
- JSON 格式包含：id、input、output、timestamp、model

**特性**：
- 专精于 TiKZ 和 DOT 语言
- 适合生成高质量出版级图表
- 支持流程图、层次结构、网络等多种图表类型
- 包含样式、颜色和标签以增强清晰度
- 自动添加注释说明图表结构

**模型特点**：
- 使用本地缓存的 HuggingFace 模型
- 自动设备映射（CPU/GPU）
- 最大生成 token 数默认 8192

---

## 通用特性

### 命令行参数

所有实现都支持以下通用参数：

- `--dataset, -d`：数据集 JSON 文件路径
- `--input, -i`：单个文本输入
- `--max-tokens`：最大生成 token 数（默认值因实现而异）
- `--limit, -l`：限制处理的项目数量（0 = 无限制）

### 默认数据集

如果不提供 `--dataset` 或 `--input` 参数，脚本会尝试使用默认数据集：
- `../../dataset/train/data.json`

### 结果保存

所有结果都以 JSON 格式保存，包含：
- `id`：项目标识符
- `input`：输入文本
- `output`：生成的图表代码
- `timestamp`：生成时间戳
- `model`：使用的模型名称

---

## 适用场景

### Mermaid (merid/)
- 需要快速生成流程图
- 在 Markdown 文档中嵌入图表
- Web 应用中渲染简单图表
- 需要轻量级、易于维护的图表代码

### TiKZ/DOT (tlzl/)
- 需要出版级质量的图表
- LaTeX 文档中的专业图表
- 复杂的层次结构和网络图
- 需要精细控制样式的图表

---

## 依赖项

### merid/
- `langchain-core`：LLM 调用接口
- `core.llm_factory`：项目自定义的 LLM 工厂类

### tlzl/
- `transformers`：HuggingFace 模型加载
- `torch`：PyTorch 深度学习框架

---

## 注意事项

1. **模型加载**：
   - merid/ 使用远程 API 调用，需要有效的 API key
   - tlzl/ 使用本地模型，确保模型已正确缓存

2. **性能考虑**：
   - tlzl/ 的 Code_Agent 模型较大，首次加载可能需要较长时间
   - 建议使用 GPU 加速以提高生成速度

3. **输出质量**：
   - 生成的代码可能需要后续微调
   - 复杂图表可能需要多次迭代优化

4. **数据集要求**：
   - 数据集必须是 JSON 数组格式
   - 每个项目必须包含 `id` 和 `content` 字段