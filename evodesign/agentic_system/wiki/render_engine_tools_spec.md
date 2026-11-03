# Render Engine 工具规格：group_fitter / edge_router / normalizer

## 概述

三个工具均为纯机械操作（无 LLM），属于渲染引擎的 manifest 构建阶段。它们处理的对象是 LLM 已经完成的决策（节点位置、连接关系、样式），只做确定性的几何/格式修正。

---

## 1. group_fitter — 组框适配子节点

### 问题

布局 LLM 决定每个节点的 (x, y, w, h)，但 group background 矩形的尺寸可能偏小（LLM 不一定精确计算 bounding box），导致组框包不住子节点。

### 输入

| 来源 | 内容 |
|------|------|
| `diagram_manifest` | 当前 Excalidraw/TLDraw manifest，含所有元素坐标 |
| `structure_instantiation` | `groups[].members` 列表，定义组-子节点归属关系 |

### 算法

```
for each group in structure_instantiation.groups:
    shapes_to_wrap = [member shapes...] + [group title shape if exists]
    bbox = bounding_box(shapes_to_wrap)
    bg_elem = manifest.lookup(group:background)
    bg_elem.x = min(bg_elem.x, bbox.min_x - padding)
    bg_elem.y = min(bg_elem.y, bbox.min_y - padding)
    bg_elem.width  = max(bg_elem.right, bbox.max_x + padding) - bg_elem.x
    bg_elem.height = max(bg_elem.bottom, bbox.max_y + padding) - bg_elem.y
```

关键：只扩大、不缩小（`min`/`max` 保证 layout 阶段的意图被保留）。

### 输出

修改后的 manifest（组框尺寸更新）。

### 调用状态

| 后端 | workflow 中是否调用 | 位置 |
|------|-------------------|------|
| Excalidraw | **已调用** | `_build_excalidraw_workflow` 第 4 步（arrows 之后、zorder 之前） |
| TLDraw | **未调用** | `_run_group_fitter` 方法存在但未加入 `_build_tldraw_workflow` 的节点图 |

### 依赖

需要 `structure_instantiation` 提供 group-member 关系。如果结构图中没有 groups，直接跳过。

---

## 2. edge_router — 箭头折线路径规划

> **当前状态。** `excalidraw/arrow_adder.py` 仍调用 `compute_waypoints()` 生成显式 `points` polyline。当前 ArrowAdder 不写 `startBinding` / `endBinding`，因此这些 `points` 是 PNG 渲染路径的权威几何来源。`elbowed` / `roundness` 只表达 routing 风格，不替代 waypoint 计算。

### 问题

LayoutAgent 只输出离散 `start.side` / `end.side`，不输出坐标。渲染阶段需要把 side pair 转成 2~4 点折线路径，并支持 fan-out stagger、crossing detector、label placement 使用同一条显式 polyline。

### 输入

| 参数 | 含义 |
|------|------|
| `start_side` | 源形状连接边：`top` / `bottom` / `left` / `right` |
| `end_side` | 目标形状连接边 |
| `src_bbox` | 源形状 `{x, y, w, h}` |
| `tgt_bbox` | 目标形状 `{x, y, w, h}` |

### 算法

16 种 (start_side, end_side) 组合，分三类：

| 类型 | 条件 | 路径 | 点数 |
|------|------|------|------|
| **直线** | 对面 + 对齐（如 bottom→top 且 x 差 < tol） | 直接连接 | 2 |
| **Z 形** | 对面 + 偏移 | 经中间 y/x 折一下 | 4 |
| **L 形** | 垂直面（如 bottom→left） | 在转角处折一次 | 3 |
| **U 形** | 同面回环（如 top→top） | 沿法线方向绕出 | 4 |

### 输出

```python
(points, focus_start, focus_end)
# points: [{"x": float, "y": float}, ...] 绝对坐标，2~4 个点
# focus: [-1, 1] 面上位置（目前固定 0.0 = 中点）
```

辅助函数：
- `to_relative_points(points)` → `(origin_x, origin_y, [[dx, dy], ...])` 转为 Excalidraw 相对坐标格式
- `waypoints_bbox(points)` → `(width, height)` 折线包围盒，用于设置 arrow 元素的 width/height

### 调用状态

| 调用方 | 是否调用 | 说明 |
|--------|---------|------|
| `excalidraw/arrow_adder.py` | **已调用** | 用 `compute_waypoints()` 生成显式 `points`；再按 `routing` 设置 `elbowed` / `roundness` |

**结论：edge_router 是当前 Excalidraw arrow path 的主路径，不是 legacy。**

### 依赖

被 `excalidraw/arrow_adder.py` 导入使用。`tldraw/arrow_adder.py` 不使用它（TLDraw 有自己的箭头机制）。

---

## 3. normalizer — manifest 规范化

### 问题

converter（pipeline 模式）在构建 manifest 时保证了三个正确性：

1. **z-order**：按 layer 排序，group frame (100) < node (200) < icon (220) < text (300)
2. **重复标题去重**：有 `:title` sibling 的组 frame 不再生成 bound-text 标题
3. **零填充 index**：`f"a{counter:05d}"` 避免 `a10 < a2` 排序问题

但存在另一条路径：`--mode oneshot`（LLM 直接输出完整 Excalidraw 场景），绕过了 converter。normalizer 就是为这条路径准备的补丁。

### 输入

一个已构建的 Excalidraw manifest dict（pipeline 或 unified 模式产出均可）。

### 算法

三步，全部幂等。核心逻辑已提取到 `shared/normalization.py`：

**Step 1: 检测 group frame IDs** — `shared.normalization.detect_group_frame_ids(structural=True)`
- 显式信号：`is_group=True`、id 前缀 `g_`、id 后缀 `:background`
- 结构信号：矩形/椭圆/菱形包含 ≥2 个同 groupIds 的非 bound-text 元素

**Step 2: 去重重复标题** — `shared.normalization.deduplicate_group_titles()`
- 对每个 frame 的 bound-text，查找是否存在内容相同、位置相近的 standalone text
- 如果有，删除 bound-text（保留 standalone，因为它是 LLM 选择的位置）

**Step 3: 重排 index** — normalizer 自有的 `_reassign_indices()`（使用 manifest 级别的 layer 分类）
- 按 (layer, 原始顺序) 稳定排序
- 重新分配零填充 index：`a00000`, `a00001`, ...

### 输出

修改后的 manifest（elements 重排、index 重分配、重复标题删除）。

### 调用状态

| 调用方 | 是否调用 |
|--------|---------|
| `excalidraw/workflow.py` | **未调用** |
| converter（pipeline 模式） | **不需要调用**（converter 内部已实现同等逻辑） |
| unified 模式 | **应该调用但未调用** |

**结论：normalizer 是为 unified 模式写的，但目前 unified 路径也没有调用它。Pipeline 模式下不需要它，因为 converter 已经做了同样的事。**

### 与 converter 的关系

| 保证 | converter（pipeline） | normalizer | 共享模块 |
|------|----------------------|------------|---------|
| z-order 排序 | `layer_for()` + sorted | `_layer_for_element()` + sorted | `shared.normalization` |
| 重复标题去重 | `titled_bases` 检测 | structural detection | `deduplicate_group_titles()` |
| 零填充 index | `a{counter:05d}` | `a{idx:05d}` | `sort_and_reindex()` |

核心逻辑已统一到 `shared/normalization.py`。converter 使用命名约定模式（`layer_for`），normalizer 使用结构启发模式（`detect_group_frame_ids(structural=True)`）+ manifest 级别的 layer 分类。

---

## 总结

| 工具 | 状态 | 行动 |
|------|------|------|
| `group_fitter` | Excalidraw + TLDraw 均已用 | 已完成 |
| `edge_router` | Excalidraw ArrowAdder 当前主路径 | 保持测试覆盖；后续可优化 offset / fan-out |
| `normalizer` | 核心逻辑提取到 `shared/normalization.py`，converter 和 normalizer 共用 | 如不支持 unified 模式可暂不集成到 workflow；如要支持则需在 unified 路径调用 |
