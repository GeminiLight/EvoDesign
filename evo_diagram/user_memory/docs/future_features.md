# User Memory - 待实现功能

本文档记录 User Memory 系统的待实现功能和 API 集成计划。

---

## 为什么需要 Backend API？

### 当前状态：CLI 模式

目前 User Memory 通过命令行参数工作：

```bash
# 学习偏好
python -m evo_diagram.agentic_system.main --learn-from-edit --user-id "test_user" ...

# 生成时使用偏好
python -m evo_diagram.agentic_system.main --example 1 --enable-user-memory --user-id "test_user"
```

**这种模式下，一切都在本地运行，Python 代码直接调用 Python 函数，不需要 API。**

### 问题：前端无法直接调用 Python

当我们需要在 Web 前端（React/浏览器）中集成 User Memory 时，会遇到以下限制：

```
┌─────────────────────────────────────────────────────────────────┐
│                     浏览器的限制                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ❌ 浏览器无法运行 Python 代码                                    │
│     → 前端是 JavaScript/TypeScript，不能 import user_memory      │
│                                                                  │
│  ❌ 浏览器无法访问服务器文件系统                                   │
│     → 无法读取 ./data/user_preferences/ 目录                     │
│                                                                  │
│  ❌ 浏览器无法直接连接数据库                                       │
│     → 无法直接操作 ChromaDB                                      │
│                                                                  │
│  ❌ 安全限制                                                      │
│     → 浏览器运行在沙箱中，与服务器隔离                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 解决方案：HTTP API 作为桥梁

```
┌──────────────┐     HTTP 请求      ┌──────────────┐     直接调用     ┌──────────────┐
│              │ ─────────────────▶ │              │ ───────────────▶ │              │
│   Browser    │                    │   Backend    │                  │ User Memory  │
│   (React)    │ ◀───────────────── │   (FastAPI)  │ ◀─────────────── │   System     │
│              │     JSON 响应      │              │     Python 对象   │              │
└──────────────┘                    └──────────────┘                  └──────────────┘

     前端                              后端 API                         核心逻辑
   (JavaScript)                       (Python)                        (Python)
```

**Backend API 的作用：**
1. 接收前端的 HTTP 请求
2. 调用已有的 `UserPreferenceMemorySystem` Python 函数
3. 将结果转换为 JSON 返回给前端

### 代码量对比

| 部分 | 代码量 | 说明 |
|------|--------|------|
| 核心逻辑 | ~500 行 | `user_memory/` 已完成 |
| API 封装 | ~80 行 | 只是给现有函数包一层 HTTP 接口 |
| 前端调用 | ~30 行 | `fetch('/api/v1/memory/learn', {...})` |

### 什么时候需要 API？

| 场景 | 是否需要 API |
|------|-------------|
| 只用命令行 (CLI) | ❌ 不需要 |
| Web 前端集成 | ✅ 需要 |
| 移动端 App | ✅ 需要 |
| 其他服务调用 | ✅ 需要 |

---

## 功能状态总览

| 功能 | 状态 | 描述 |
|------|------|------|
| CLI 学习模式 | ✅ 已完成 | `--learn-from-edit` |
| CLI 生成时检索 | ✅ 已完成 | `--enable-user-memory` |
| 分阶段偏好注入 | ✅ 已完成 | Structure/Styling/Layout 分别注入 |
| ChromaDB 存储 | ✅ 已完成 | 使用 HuggingFace Embedding |
| Backend API | ⏳ 待实现 | `/api/v1/memory/*` |
| 前端集成 | ⏳ 待实现 | 调整后自动学习 |


---

## Phase 3: Backend API 集成

### 文件结构

```
backend/
├── app/
│   └── api/
│       └── v1/
│           └── endpoints/
│               ├── __init__.py      # 需要修改：注册 memory router
│               ├── generate.py      # 需要修改：集成记忆检索
│               └── memory.py        # 需要新建：Memory API
```

### API 设计

#### 1. POST /api/v1/memory/learn

学习用户偏好（前端精调后调用）。

**Request:**

```json
{
    "task_json": {
        "id": "class_001",
        "diagram_type": "class",
        "content_area": "Software Engineering",
        "content": "The AddressBook system models..."
    },
    "model_manifest": {
        "document": {
            "store": { ... }
        }
    },
    "model_image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "user_manifest": {
        "document": {
            "store": { ... }
        }
    },
    "user_image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "user_id": "user_123",
    "session_id": "session_001"
}
```

**Response:**

```json
{
    "success": true,
    "session_id": "session_001",
    "preferences_extracted": 4,
    "preferences_by_category": {
        "Structure": 0,
        "Styling": 3,
        "Layout": 1
    },
    "details": [
        {
            "category": "Styling",
            "preference": "Uses red color for all class entity nodes",
            "confidence": 1.0
        }
    ]
}
```

**实现代码示例:**

```python
# backend/app/api/v1/endpoints/memory.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import base64
import tempfile
import os

from evo_diagram.user_memory.main import UserPreferenceMemorySystem

router = APIRouter(prefix="/memory", tags=["memory"])


class LearnRequest(BaseModel):
    task_json: Dict
    model_manifest: Dict
    model_image_base64: str
    user_manifest: Dict
    user_image_base64: str
    user_id: str
    session_id: Optional[str] = None


class LearnResponse(BaseModel):
    success: bool
    session_id: str
    preferences_extracted: int
    preferences_by_category: Dict[str, int]
    details: List[Dict]


@router.post("/learn", response_model=LearnResponse)
async def learn_preferences(request: LearnRequest):
    """Learn user preferences from diagram edits."""
    try:
        # Initialize memory system
        system = UserPreferenceMemorySystem(user_id=request.user_id)

        # Save base64 images to temp files
        with tempfile.TemporaryDirectory() as tmpdir:
            model_image_path = os.path.join(tmpdir, "model.png")
            user_image_path = os.path.join(tmpdir, "user.png")
            model_manifest_path = os.path.join(tmpdir, "model_manifest.json")
            user_manifest_path = os.path.join(tmpdir, "user_manifest.json")

            # Decode and save images
            with open(model_image_path, "wb") as f:
                f.write(base64.b64decode(request.model_image_base64))
            with open(user_image_path, "wb") as f:
                f.write(base64.b64decode(request.user_image_base64))

            # Save manifests
            import json
            with open(model_manifest_path, "w") as f:
                json.dump(request.model_manifest, f)
            with open(user_manifest_path, "w") as f:
                json.dump(request.user_manifest, f)

            # Generate session_id if not provided
            session_id = request.session_id or f"session_{int(time.time())}"

            # Learn from edit
            result = system.learn_from_edit(
                task_json=request.task_json,
                model_manifest_path=model_manifest_path,
                model_image_path=model_image_path,
                user_manifest_path=user_manifest_path,
                user_image_path=user_image_path,
                session_id=session_id
            )

        return LearnResponse(
            success=True,
            session_id=session_id,
            preferences_extracted=result["preferences"]["extracted"],
            preferences_by_category=result["preferences"]["by_category"],
            details=[
                {
                    "category": p.agent_category,
                    "preference": p.preference_text,
                    "confidence": p.confidence
                }
                for p in result.get("raw_preferences", [])
            ]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

#### 2. GET /api/v1/memory/preferences

检索用户偏好。

**Request Query Parameters:**

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| user_id | string | ✅ | 用户标识符 |
| query | string | ❌ | 语义搜索查询 |
| agent_category | string | ❌ | 过滤类别 (Structure/Styling/Layout) |
| diagram_type | string | ❌ | 过滤图表类型 |
| min_confidence | float | ❌ | 最低置信度 (默认: 0.7) |
| top_k | int | ❌ | 返回数量 (默认: 5) |

**Response:**

```json
{
    "preferences": [
        {
            "id": "pref_abc123",
            "memory": "Uses red color for all class entity nodes",
            "metadata": {
                "agent_category": "Styling",
                "confidence": 1.0,
                "diagram_type": "class",
                "design_rationale": "Establishes consistent visual identity"
            }
        }
    ],
    "count": 3,
    "user_id": "user_123"
}
```

**实现代码示例:**

```python
class PreferencesResponse(BaseModel):
    preferences: List[Dict]
    count: int
    user_id: str


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    user_id: str,
    query: Optional[str] = None,
    agent_category: Optional[str] = None,
    diagram_type: Optional[str] = None,
    min_confidence: float = 0.7,
    top_k: int = 5
):
    """Retrieve user preferences."""
    try:
        system = UserPreferenceMemorySystem(user_id=user_id)

        if query:
            # Semantic search
            prefs = system.retrieve_preferences(
                query=query,
                agent_category=agent_category,
                diagram_type=diagram_type,
                min_confidence=min_confidence,
                top_k=top_k
            )
        else:
            # Get all preferences
            prefs = system.storage.get_all_preferences(limit=top_k)
            # Filter by category if specified
            if agent_category:
                prefs = [p for p in prefs if p.get("metadata", {}).get("agent_category") == agent_category]

        return PreferencesResponse(
            preferences=prefs,
            count=len(prefs),
            user_id=user_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

#### 3. DELETE /api/v1/memory/preferences

删除用户偏好。

**Request:**

```json
{
    "user_id": "user_123",
    "preference_ids": ["pref_001", "pref_002"],
    "delete_all": false
}
```

**Response:**

```json
{
    "success": true,
    "deleted_count": 2,
    "user_id": "user_123"
}
```

**实现代码示例:**

```python
class DeleteRequest(BaseModel):
    user_id: str
    preference_ids: Optional[List[str]] = None
    delete_all: bool = False


class DeleteResponse(BaseModel):
    success: bool
    deleted_count: int
    user_id: str


@router.delete("/preferences", response_model=DeleteResponse)
async def delete_preferences(request: DeleteRequest):
    """Delete user preferences."""
    try:
        # TODO: Implement delete functionality in Mem0PreferenceStorage
        # storage.delete_preferences(preference_ids) or storage.clear_all()

        raise HTTPException(
            status_code=501,
            detail="Delete functionality not yet implemented"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

### 前端集成流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
└─────────────────────────────────────────────────────────────────────────────┘
       │                                                    ▲
       │ 1. POST /api/v1/generate                          │ 6. Return diagram
       │    {text, user_id}                                │    with preferences applied
       ▼                                                    │
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Backend (FastAPI)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  generate.py                           memory.py                             │
│  ┌─────────────────────┐              ┌─────────────────────┐               │
│  │                     │  2. Retrieve │                     │               │
│  │  Generate Endpoint  │ ───────────▶ │  Memory Endpoints   │               │
│  │                     │              │                     │               │
│  │  - Check user_id    │ ◀─────────── │  - /learn           │               │
│  │  - Get preferences  │  3. Return   │  - /preferences     │               │
│  │  - Inject to prompt │     prefs    │  - /preferences     │               │
│  │                     │              │    (DELETE)         │               │
│  └─────────────────────┘              └─────────────────────┘               │
│           │                                    ▲                             │
│           │ 4. Run workflow                    │                             │
│           │    with preferences                │                             │
│           ▼                                    │                             │
│  ┌─────────────────────┐                      │                             │
│  │  Text2DiagramWorkflow                      │                             │
│  │  (enable_user_memory=True)                 │                             │
│  └─────────────────────┘                      │                             │
│                                                │                             │
└────────────────────────────────────────────────┼─────────────────────────────┘
                                                 │
                                                 │ 5. Store/Retrieve
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         User Memory System                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ChromaDB + HuggingFace Embedding (Qwen3-Embedding-0.6B)                    │
│  ./data/user_preferences/                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 前端交互序列

```
User                    Frontend                Backend              UserMemory
 │                         │                       │                     │
 │  1. Create Diagram      │                       │                     │
 │ ───────────────────────▶│                       │                     │
 │                         │  2. POST /generate    │                     │
 │                         │ ─────────────────────▶│                     │
 │                         │                       │  3. Retrieve prefs  │
 │                         │                       │ ───────────────────▶│
 │                         │                       │ ◀───────────────────│
 │                         │                       │  4. Run workflow    │
 │                         │ ◀─────────────────────│                     │
 │  5. Show Diagram        │                       │                     │
 │ ◀───────────────────────│                       │                     │
 │                         │                       │                     │
 │  6. Edit in Excalidraw  │                       │                     │
 │ ───────────────────────▶│                       │                     │
 │                         │                       │                     │
 │  7. Save Changes        │                       │                     │
 │ ───────────────────────▶│                       │                     │
 │                         │  8. POST /memory/learn│                     │
 │                         │ ─────────────────────▶│                     │
 │                         │                       │  9. Extract & Store │
 │                         │                       │ ───────────────────▶│
 │                         │                       │ ◀───────────────────│
 │                         │ ◀─────────────────────│                     │
 │  10. Confirm learned    │                       │                     │
 │ ◀───────────────────────│                       │                     │
 │                         │                       │                     │
```
