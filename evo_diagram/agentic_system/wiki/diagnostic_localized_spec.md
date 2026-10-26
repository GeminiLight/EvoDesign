# Spec: Diagnostic / Localized 对齐修复

Verification (Diagnostic) 和 Refinement (Localized) 的对齐分析与修复记录。
所有 6 个 misalignment 点均已修复。

---

## 修复总览

| # | 问题 | 修复方案 | 状态 |
|---|------|---------|------|
| 1 | zorder fixer 全局批量 | 改用 per-element Finding，fixer 只改报告的元素 | ✅ |
| 2 | contrast fixer 全局扫描 | 改用 per-element Finding，fixer 只改报告的元素 | ✅ |
| 3 | delete_element 无安全检查 | 添加连接性验证，拒绝删除有连接的元素 | ✅ |
| 4 | overlap 无 deterministic fixer | 新增 `fix_node_overlap`（MTV 算法） | ✅ |
| 5 | audit 返回聚合字符串 | 改为返回 `AuditReport` 含 per-element `AuditIssue` | ✅ |
| 6 | convergence 无 stagnation 检测 | 新增 findings 指纹比较，连续相同则停止 | ✅ |

---

## 1. fix_group_frame_zorder — per-element targeting

### 问题

fixer 把**所有** group background 的 index 设为 `a00000`，而不是只修被报告异常的元素。

### 修复

`render_audit.py` 现在返回 per-element `AuditIssue`，每个 issue 带 `element_id`。
`check_render_audit` 将每个 issue 转为带 `element_id` 的 Finding。
`fix_group_frame_zorder` 优先使用 per-element Finding 的 `element_id`，仅修改被报告的 background。
没有 `element_id` 的聚合 Finding 会被忽略，避免一次修复改动未被报告的 group。

**文件变更**：
- `render_engine/shared/render_audit.py` — `_audit_group_frame_zorder` 返回 `List[AuditIssue]`
- `verification_stage/checks/render_validation.py` — `check_render_audit` 使用 `report.issues`
- `refinement_stage/fixers/deterministic.py` — `fix_group_frame_zorder` 按 element_id 定向修复

---

## 2. fix_low_contrast — per-element targeting

### 问题

contrast warning 是聚合字符串，fixer 重新扫描所有 text 元素。

### 修复

同 #1，`_audit_text_contrast` 返回 per-element `AuditIssue`。
`fix_low_contrast` 优先使用 per-element Finding 的 `element_id`，仅修改被报告的 text 元素。
没有 `element_id` 的聚合 Finding 会被忽略，避免重新扫描并修改未被报告的 text。

**文件变更**：
- `render_engine/shared/render_audit.py` — `_audit_text_contrast` 返回 `List[AuditIssue]`
- `refinement_stage/fixers/deterministic.py` — `fix_low_contrast` 按 element_id 定向修复

---

## 3. delete_element — 安全验证

### 问题

`op_delete_element` 无安全检查，LLM 误判可删除有连接的正常元素，导致 arrow 变 dangling reference。

### 修复

`op_delete_element` 新增连接性验证。拒绝删除以下元素（除非已 `isDeleted`）：
- 有 `containerId`（是某个容器的 bound text）
- 有 `boundElements`（有 bound children）
- 有 arrow 的 `startBinding`/`endBinding` 指向它

返回 `(False, "refusing to delete connected element ...")` + 具体原因。

LLM prompt 也更新了约束说明，要求先 `clear_arrow_binding` 断开连接再 `delete_element`。

**文件变更**：
- `refinement_stage/fixers/primitives.py` — `op_delete_element` 新增 3 项安全检查
- `refinement_stage/agent/prompts.py` — prompt 新增 delete_element 约束说明

---

## 4. fix_node_overlap — MTV 算法

### 问题

overlap 是最常见的视觉问题，但没有 deterministic fixer，全靠 LLM 用 `set_position` 猜。

### 修复

新增 `fix_node_overlap` deterministic fixer：
1. 解析 Finding 的 `location` 字段获取两个元素的 bbox
2. 计算重叠区域（overlap_w, overlap_h）
3. 沿较短轴（Minimum Translation Vector）推出去
4. 生成 `set_position` EditOp 移动较后添加的元素
5. 添加 padding（默认 10px）避免紧贴

在 `_FIXERS` 注册表中排在 `group_frame_zorder` 和 `low_contrast` 之前，确保 overlap 先修。

**文件变更**：
- `refinement_stage/fixers/deterministic.py` — 新增 `fix_node_overlap`，注册到 `_FIXERS`

---

## 5. render_audit — per-element AuditIssue

### 问题

`audit_excalidraw_manifest` 返回 `List[str]`（聚合警告），verification 层无法获得具体 element_id。

### 修复

新增 `AuditIssue` 和 `AuditReport` dataclass：

```python
@dataclass
class AuditIssue:
    category: str        # "zorder" | "contrast" | "empty_text" | "arrow_coverage"
    message: str
    element_id: Optional[str] = None
    severity: str = "MAJOR"

@dataclass
class AuditReport:
    warnings: List[str] = field(default_factory=list)   # 日志 / 报告展示
    issues: List[AuditIssue] = field(default_factory=list)
```

`audit_excalidraw_manifest` 返回 `AuditReport`。`.warnings` 用于日志和报告展示，`.issues` 提供 per-element 结构化数据。

调用方迁移：
- `verification_stage/checks/render_validation.py` — 用 `report.issues`
- `render_engine/excalidraw/converter.py` — 用 `report.warnings`（不变）
- `scripts/regression_render.py` — 用 `report.warnings`
- 测试 — 用 `report.warnings`

**文件变更**：
- `render_engine/shared/render_audit.py` — 新增 dataclass，修改返回类型
- `verification_stage/checks/render_validation.py` — 使用 `report.issues`
- `render_engine/excalidraw/converter.py` — 使用 `report.warnings`
- `generation_stage/unified/workflow.py` — 使用 `report.warnings`
- `scripts/regression_render.py` — 使用 `report.warnings`
- `tests/render_engine/test_render_fidelity.py` — 使用 `report.warnings`

---

## 6. Convergence — stagnation 检测

### 问题

当 LLM 的 EditOps 无效（apply 失败或不解决 findings）时，findings 不变但循环继续，直到跑满 max_iterations。

### 修复

新增 stagnation 检测：每轮迭代后计算 findings 的指纹（sorted (category, element_id, message) tuples），与上一轮比较。如果连续两轮指纹相同，判定为 stagnation，提前停止。

```python
def _fingerprint_findings(findings: List[Finding]) -> str:
    parts = sorted((f.category, f.element_id or "", f.message) for f in findings)
    return "|".join(f"{c}:{e}:{m}" for c, e, m in parts)
```

状态字段 `_prev_findings_fingerprint` 存储上一轮指纹（`exclude=True`，不序列化到日志）。

**文件变更**：
- `agentic_system/iterative_workflow.py` — 新增 `_fingerprint_findings`，stagnation 检查逻辑
- `refinement_stage/state.py` — 新增 `_prev_findings_fingerprint` 字段
