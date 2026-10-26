# User Preference Memory System

用户偏好记忆系统 - 基于 LLM 的智能偏好学习框架，通过分析用户对自动生成图表的手动调整，自动提取和存储语义化设计偏好，用于未来任务的个性化生成。

## 目录

- [系统架构](#系统架构)
- [核心特性](#核心特性)
- [环境配置](#环境配置)
- [CLI 使用指南](#cli-使用指南)
- [工作流集成](#工作流集成)
- [实现逻辑](#实现逻辑)
- [数据存储](#数据存储)
- [待实现功能](#待实现功能)
- [测试](#测试)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         User Preference Memory System                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Layer 1   │    │   Layer 2   │    │   Layer 3   │    │   Layer 4   │  │
│  │     VLM     │───▶│  JSON Diff  │───▶│     LLM     │───▶│   ChromaDB  │  │
│  │  Observer   │    │  Extractor  │    │  Preference │    │   Storage   │  │
│  │             │    │             │    │    Agent    │    │             │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│        │                  │                  │                  │          │
│        ▼                  ▼                  ▼                  ▼          │
│  VisualObservation   GuidedDiff      SemanticPreference    Vector Store   │
│  (overall_intent,    (modifications, (preference_text,     (HuggingFace   │
│   structural/        additions,       agent_category,       Embedding +    │
│   styling/layout     deletions)       confidence,           ChromaDB)      │
│   changes)                            applies_to)                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Agentic System Integration                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Structure  │    │   Styling   │    │   Layout    │    │   Render    │  │
│  │   Stage     │    │    Stage    │    │    Stage    │    │    Stage    │  │
│  │             │    │             │    │             │    │             │  │
│  │ ◀──────────────────────────────────────────────────▶   │             │  │
│  │   Per-Stage Preference Injection (design_expertise)    │             │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 目录结构

```
user_memory/
├── main.py                             # 主入口（4层编排）
│
├── extractors/                         # 提取器模块
│   ├── vlm_observer.py                 # Layer 1: VLM 图像观察
│   ├── manifest_validator.py           # Layer 2a: manifest 格式检测
│   ├── manifest_normalizer.py          # Layer 2b: manifest 归一化
│   ├── diff_extractor.py               # Layer 2c: JSON 差异提取
│   └── llm_preference_agent.py         # Layer 3: LLM 语义提取 ⭐
│
├── schemas/                            # 数据模型
│   ├── observation_schemas.py          # VLM 观察模型
│   ├── diff_schemas.py                 # JSON 差异模型
│   └── semantic_preference_schemas.py  # 语义偏好模型
│
├── storage/                            # 存储模块
│   └── mem0_storage.py                 # Layer 4: ChromaDB + HuggingFace 存储
│
├── docs/                               # 文档
│   ├── wiki.md                         # 本文档
│   ├── integration_plan.md             # 集成计划
│   └── future_features.md              # 待实现功能 & API 设计
│
└── data_example/                       # 示例数据
    └── class_20251204_212001_22/       # 示例数据集
```

---

## 核心特性

| 特性 | 描述 |
|------|------|
| **LLM 语义提取** | 使用 LLM 生成富含上下文的自然语言偏好 |
| **4 层架构** | VLM 观察 → JSON Diff → LLM 分析 → ChromaDB 存储 |
| **Agent 对齐** | 偏好分类对齐主系统 Agent (Structure/Styling/Layout) |
| **分阶段注入** | 各阶段仅注入对应类别的偏好 |
| **置信度过滤** | 自动过滤 confidence < 0.7 的低质量偏好 |
| **向量存储** | ChromaDB + HuggingFace Embedding (Qwen3-Embedding-0.6B) |

---

## 环境配置

### 配置文件

在 `config/default.yaml` 中配置：

```yaml
# User preference memory configuration
user_memory:
  vector_db_path: ${oc.env:USER_PREFERENCE_MEMORY_PATH,./data/user_preferences}
  embedding_model_name: ${oc.env:USER_PREFERENCE_EMBEDDING_MODEL,Qwen/Qwen3-Embedding-0.6B}
```

### 环境变量（可选）

```bash
# 自定义存储路径
export USER_PREFERENCE_MEMORY_PATH=./data/user_preferences

# 自定义 Embedding 模型
export USER_PREFERENCE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
```

---

## CLI 使用指南

User Memory 已集成到 `agentic_system.main`，通过命令行参数控制。

### 1. 学习用户偏好 (Learn Mode)

当用户手动调整了 Agent 生成的图表后，运行学习模式提取偏好：

```bash
python -m evo_diagram.agentic_system.main \
    --learn-from-edit \
    --user-id "test_user" \
    --task-json "user_memory/data_example/class_20251204_212001_22/task.json" \
    --model-manifest "user_memory/data_example/class_20251204_212001_22/4_render/diagram_manifest.json" \
    --model-image "user_memory/data_example/class_20251204_212001_22/4_render/rendered_diagram.png" \
    --user-manifest "user_memory/data_example/class_20251204_212001_22/user_adjusted/diagram_manifest.json" \
    --user-image "user_memory/data_example/class_20251204_212001_22/user_adjusted/rendered_diagram.png"
```

**参数说明：**

| 参数 | 必需 | 描述 |
|------|------|------|
| `--learn-from-edit` | ✅ | 启用学习模式 |
| `--user-id` | ❌ | 用户标识符（默认: `default_user`） |
| `--session-id` | ❌ | 会话标识符（默认: 自动生成 `session_YYYYMMDD_HHMMSS`） |
| `--task-json` | ✅ | 任务描述文件路径 |
| `--model-manifest` | ✅ | Agent 生成的 manifest JSON 路径 |
| `--model-image` | ✅ | Agent 生成的图片路径 |
| `--user-manifest` | ✅ | 用户调整后的 manifest JSON 路径 |
| `--user-image` | ✅ | 用户调整后的图片路径 |
| `--memory-db-path` | ❌ | 数据库存储路径（默认: `./data/user_preferences`） |

**输出示例：**

```
============================================================
User Preference Learning Mode
============================================================
User ID: test_user
Session ID: session_20260222_144135
Task: user_memory/data/class_20251204_212001_22/task.json
============================================================

────────────────────────────────────────────────────────────────────────────────
📸 LAYER 1: VLM Image Observation
────────────────────────────────────────────────────────────────────────────────
  Overall Intent: Unable to infer intent - diagram images were not provided...
  Structural Changes: magnitude=unknown
  Styling Changes: magnitude=unknown
  Layout Changes: magnitude=unknown

────────────────────────────────────────────────────────────────────────────────
🔍 LAYER 2: JSON Diff Extraction
────────────────────────────────────────────────────────────────────────────────
  Statistics:
    - Modifications: 7
    - Additions: 0
    - Deletions: 0

  Modifications (top 5):
    [1] Shape: shape:a19af425b2734d9aa087
        • props.dash: draw → dashed [styling]
    [2] Shape: shape:node:AddressBook
        • props.color: blue → red [styling]
    [3] Shape: shape:node:ContactGroup
        • x: 450.0 → 406.46 [layout]
        • y: 260.0 → 260.20 [layout]

────────────────────────────────────────────────────────────────────────────────
🧠 LAYER 3: LLM Semantic Preference Extraction
────────────────────────────────────────────────────────────────────────────────
  Total Preferences Extracted: 4
  Filtered (confidence < 0.7): 0

  Extracted Preferences:

    [1] Styling (confidence: 100%)
        Preference: Uses red color for all class entity nodes instead of default blue
        Rationale: Establishes a consistent visual identity for class entities
        Evidence: All 4 class nodes changed from blue to red

    [2] Styling (confidence: 100%)
        Preference: Prefers structured document format for node labels
        Rationale: Enables richer text formatting and future extensibility

    [3] Styling (confidence: 85%)
        Preference: Uses dashed line style for relationship edges
        Rationale: Creates visual hierarchy and helps differentiate relationship types

    [4] Layout (confidence: 70%)
        Preference: Makes fine-tuned positional adjustments for optimal spacing
        Rationale: Improves readability and visual balance

────────────────────────────────────────────────────────────────────────────────
💾 LAYER 4: Mem0 Storage
────────────────────────────────────────────────────────────────────────────────
  Session ID: session_20260222_144135
  User ID: test_user
  Preferences Stored: 4

============================================================
Learning Complete!
============================================================
Preferences Extracted: 4
  - Structure: 0
  - Styling: 3
  - Layout: 1
```

### 2. 生成时启用记忆 (Generation with Memory)

生成图表时启用用户记忆，系统会自动检索并注入偏好：

```bash
python -m evo_diagram.agentic_system.main \
    --example 1 \
    --enable-user-memory \
    --user-id "test_user"
```

**参数说明：**

| 参数 | 必需 | 描述 |
|------|------|------|
| `--enable-user-memory` | ✅ | 启用用户记忆检索 |
| `--user-id` | ❌ | 用户标识符（默认: `default_user`） |
| `--memory-db-path` | ❌ | 数据库路径（默认: `./data/user_preferences`） |

**输出示例：**

```
================================================================================
Processing example 1 (id: class_20251204_212001_22)
================================================================================
Example: 1 (id: class_20251204_212001_22)
Diagram Type: class
Content Area: Software Engineering
User Memory: enabled (user_id: test_user)
================================================================================

[1/4] Running StructureWorkflow...
Retrieving preferences: query='User preferences for class diagrams...', category=Structure
Retrieved 0 preferences                    # 没有 Structure 偏好
No user preferences found for category=Structure

[2/4] Running StylingWorkflow...
Retrieving preferences: query='User preferences for class diagrams...', category=Styling
Retrieved 3 preferences                    # ✅ 检索到 3 条 Styling 偏好
[StylingAgent] Invoking LLM...

[3/4] Running LayoutWorkflow...
Retrieving preferences: query='User preferences for class diagrams...', category=Layout
Retrieved 1 preferences                    # ✅ 检索到 1 条 Layout 偏好
[LayoutAgent] Invoking LLM...

[4/4] Running RenderWorkflow...
Workflow completed!
```

---

## 工作流集成

### 分阶段偏好注入

User Memory 实现了**分阶段偏好注入**，各阶段仅接收对应类别的偏好：

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Structure      │     │    Styling      │     │    Layout       │
│  Stage          │     │    Stage        │     │    Stage        │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│                 │     │                 │     │                 │
│ ◀── Structure   │     │ ◀── Styling     │     │ ◀── Layout      │
│     Preferences │     │     Preferences │     │     Preferences │
│                 │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
   检索 agent_category     检索 agent_category     检索 agent_category
   = "Structure"          = "Styling"            = "Layout"
```

### 实现代码

**workflow.py** 中的关键实现：

```python
def _get_stage_expertise(category: str) -> str:
    """Build design_expertise for a specific stage with user preferences."""
    stage_expertise = design_expertise
    if self.enable_user_memory and self.memory_system:
        user_prefs = self._retrieve_user_preferences(
            diagram_type=diagram_type or "unknown",
            content_area=content_area or "unknown",
            agent_category=category  # 按类别检索
        )
        if user_prefs:
            stage_expertise = f"{stage_expertise}\n\n{user_prefs}"
    return stage_expertise
```

### Prompt 注入格式

偏好会以以下格式注入到 Agent 的 `design_expertise` 字段：

```markdown
## Design Knowledge & User Preferences

### User Preferences (Learned from Previous Edits)

**IMPORTANT**: The following preferences were learned from this user's previous
diagram edits. If relevant to the current task, you SHOULD incorporate these
preferences into your design decisions. These represent the user's personal
style and design choices.

1. **[Styling]** Uses red color for all class entity nodes instead of default blue
   - Rationale: Establishes a consistent visual identity for class entities
   - Confidence: 100%

2. **[Styling]** Uses dashed line style for relationship edges
   - Rationale: Creates visual hierarchy and helps differentiate relationship types
   - Confidence: 85%
```

### Agent Prompt 模板

在 `styling_parameter_task.py` 和 `layout_parameter_task.py` 中：

```python
## Design Knowledge & User Preferences
{design_expertise}

## Runtime Directives
{runtime_directives}

## Input Data
- **User Query**: {user_query}
- **Semantic Topology**: {structure_instantiation}
```

---

## 实现逻辑

### Layer 1: VLM Image Observer

使用 VLM 比较前后两张图片，分析高层次视觉差异：

```python
# extractors/vlm_observer.py
class VLMImageObserver:
    def observe_differences(
        self,
        model_image_path: str,
        user_image_path: str,
        task_description: str
    ) -> VisualObservation:
        # 调用 VLM 分析图像差异
        # 输出: overall_intent, structural/styling/layout_changes
```

### Layer 2: JSON Diff Extractor

提取 manifest JSON 的精确差异：

```python
# extractors/diff_extractor.py
class EnhancedDiffExtractor:
    def extract_diff(
        self,
        model_manifest: dict,
        user_manifest: dict,
        visual_observation: VisualObservation
    ) -> GuidedDiff:
        # 对比 JSON 结构
        # 输出: modifications, additions, deletions
```

### Layer 3: LLM Preference Agent

使用 LLM 从 VLM 观察和 JSON 差异中提取语义偏好：

```python
# extractors/llm_preference_agent.py
class LLMPreferenceExtractionAgent:
    def extract_preferences(
        self,
        visual_observation: VisualObservation,
        guided_diff: GuidedDiff,
        task_context: dict
    ) -> PreferenceExtractionResult:
        # LLM 分析并提取偏好
        # 输出: SemanticPreference[] with confidence filtering
```

### Layer 4: ChromaDB Storage

使用 ChromaDB + HuggingFace Embedding 存储和检索偏好：

```python
# storage/mem0_storage.py
class Mem0PreferenceStorage:
    def __init__(self, user_id: str):
        # 初始化 HuggingFace Embedding
        self.embedding_function = HuggingFaceEmbeddings(
            model_name="Qwen/Qwen3-Embedding-0.6B"
        )
        # 初始化 ChromaDB
        self.preferences_collection = Chroma(
            collection_name=f"user_preferences_{user_id}",
            embedding_function=self.embedding_function
        )

    def store_preferences(self, ...):
        # 存储 VLM 观察、JSON 差异元数据、语义偏好

    def retrieve_preferences(
        self,
        query: str,
        agent_category: str,  # Structure/Styling/Layout
        diagram_type: str,
        min_confidence: float = 0.7
    ) -> List[dict]:
        # 按类别和条件检索偏好
```

---

## 数据存储

### 存储位置

```
./data/user_preferences/
├── chroma.sqlite3              # ChromaDB 数据库
└── {collection_id}/            # 向量索引
```

### 查询存储的偏好

```python
from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage

storage = Mem0PreferenceStorage(user_id='test_user')
prefs = storage.get_all_preferences(limit=20)

for pref in prefs:
    print(f"Category: {pref['metadata']['agent_category']}")
    print(f"Confidence: {pref['metadata']['confidence']}")
    print(f"Content: {pref['memory']}")
```

### 当前存储的偏好示例

```
Total stored preferences: 4
================================================================================
[1] semantic_preference | Styling | confidence=1.0
    Content: Uses red color (hex: red) for all class entity nodes instead of default blue

[2] semantic_preference | Styling | confidence=1.0
    Content: Prefers structured document format for node labels instead of plain strings

[3] semantic_preference | Styling | confidence=0.85
    Content: Uses dashed line style for relationship edges to visually distinguish them

[4] semantic_preference | Layout | confidence=0.7
    Content: Makes fine-tuned positional adjustments to nodes for optimal visual spacing
```

---

## 待实现功能

详细的待实现功能和 API 集成计划请参阅：[future_features.md](future_features.md)

**功能状态概览：**

| 功能 | 状态 |
|------|------|
| CLI 学习模式 | ✅ 已完成 |
| CLI 生成时检索 | ✅ 已完成 |
| 分阶段偏好注入 | ✅ 已完成 |
| ChromaDB 存储 | ✅ 已完成 |
| Backend API | ⏳ 待实现 |
| 前端集成 | ⏳ 待实现 |

---

## 测试

### 完整测试流程

```bash
# 1. 启动 Tool Services
cd agentic_system/tool_services && npm start

# 2. 学习偏好
python -m evo_diagram.agentic_system.main \
    --learn-from-edit \
    --user-id "test_user" \
    --task-json "user_memory/data_example/class_20251204_212001_22/task.json" \
    --model-manifest "user_memory/data_example/class_20251204_212001_22/4_render/diagram_manifest.json" \
    --model-image "user_memory/data_example/class_20251204_212001_22/4_render/rendered_diagram.png" \
    --user-manifest "user_memory/data_example/class_20251204_212001_22/user_adjusted/diagram_manifest.json" \
    --user-image "user_memory/data_example/class_20251204_212001_22/user_adjusted/rendered_diagram.png"

# 3. 验证存储
python -c "
from evo_diagram.user_memory.storage.mem0_storage import Mem0PreferenceStorage
storage = Mem0PreferenceStorage(user_id='test_user')
prefs = storage.get_all_preferences()
print(f'Stored: {len(prefs)} preferences')
for p in prefs:
    print(f'  - [{p[\"metadata\"][\"agent_category\"]}] {p[\"memory\"][:50]}...')
"

# 4. 生成时使用记忆
python -m evo_diagram.agentic_system.main \
    --example 1 \
    --enable-user-memory \
    --user-id "test_user"

# 5. 回归测试（不启用记忆）
python -m evo_diagram.agentic_system.main --example 1
```

---

## License

MIT License
