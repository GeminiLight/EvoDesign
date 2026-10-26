# 数据集图片重建管线设计

基于论文三阶段管线（`research/evo_diagram/sections/appendix/canvas-benchmark.tex`），
但按仓库数据的真实结构调整：检索单位为数据集中实际出现的
`(diagram_type, vertical_domain)` 组合，而不是论文的 21×30 固定矩阵。

## 数据现状（实测）

- 记录：train 5,854 + test 420 = 6,274 条
- 图表类型：22 种（21 种 + 示例记录 `react`）
- 垂直领域：125 个原始取值（MMMU 大领域 + 细粒度主题混杂，如 `Payroll`、`dashboard`），
  经 `domain_to_mmmu.json` 映射到 MMMU 30 标准领域（对齐论文口径）
- 唯一组合：原始口径 2,057 个；**MMMU 口径 625 个**（每组合 1–64 条记录，中位 6）

## 阶段总览

```
data.json ──► [S1 检索下载] ──► [S2+S3 过滤+对齐(合并)] ──► [S4 导出]
              candidates/       final/ + mapping + logs      dataset/images/
```

### S0 查询构造（已并入 S1，无独立脚本与中间文件）

设计决策：query 是 `(diagram_type, vertical_domain)` 的确定性派生，模板只有一个
`"{type_label} diagram of {mmmu_domain}"`，分组统计读 data.json 即可在内存
完成，不单独落 manifest 文件。

- 领域口径：对齐论文，原始 125 个领域词经 `domain_to_mmmu.json` 映射到
  MMMU 30 标准领域（4 个无领域语义词映射为空，query 省略 "of ..." 子句）。
  映射后组合 **625 个**（≈论文 21×30 矩阵），每组合 1–64 条记录（中位 6）。
- `type_label` 归一化：`er→ER`、`orgchart→org chart`、`dataflow→data flow`、
  `mindmap→mind map`、`swot→SWOT analysis`，其余原样。
- `needed` = 组内记录数 × 过采样系数（默认 3，上限 30）。
- `react` 示例记录跳过。
- 补检机制：大组合一轮配不满（候选上限 30、过滤存活 30–50%），未配上的记录
  进入补检轮，query 追加原始细粒度领域词作关键词
  （如 `"flowchart diagram of Biology DNA sequencing"`）。
- 审查方式：`fetch_candidates.py --dry-run` 打印检索计划（组合数、query、
  needed、总请求数）而不调 API。

### S1 检索下载 — `fetch_candidates.py`

- 读 `dataset/train|test/data.json`，内存中按组合分组并用单一模板构造 query
  （见 S0 说明）；`--dry-run` 只打印检索计划不执行。
- 主用 Serper `/images`（单次返回量大，每组合 1 次请求即可；环境变量 `SERPER_API_KEY`）；
  备选 Google CSE（`GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX`，需翻页）。
- 每个组合请求一次，取 top-`needed` 个结果下载，记录**原始图片 URL 和来源页面 URL**
  （这次必须留底，论文复现和溯源都靠它）。
- 下载校验：Content-Type 为图片、尺寸 ≥ 200×200、文件 ≥ 10KB；
  按 URL + 感知哈希去重。
- 输出：`dataset/raw/<combo_slug>/<idx>.jpg` + `dataset/candidates.json`
  （台账，`{image_url, page_url, combos, local_path, status, phash}`）
- 断点续跑：已完成的组合跳过；失败计入 `logs/`。

### S2+S3 过滤与对齐（合并） — `filter_and_match.py`

设计决策：S2（canvas-recoverability 过滤）与 S3（记录对齐）合并为同一轮 VLM 调用。
过滤是对齐的前置条件，且两者输入相同（同组合的候选图 + 记录），合并后
VLM 调用量从 ~3–4 万次降到 ~2,400 次。

- 模型：Qwen3-VL-Max（与论文一致；可配置）。并发 + 原始输出落 `logs/` 缓存，
  重跑时读缓存不重复调用。
- 每个组合一次调用（候选 >8 张时按 8 张分块，块间代码仲裁）：
  - 输入：该组合 N 张候选图 + 组合内全部记录的 `content`（中位 3 条）。
  - 输出（结构化 JSON）：每张图 `{keep, reject_reason}`（剔除手绘草图、
    复杂数据可视化、照片型信息图、模糊文档）；每张 keep 图
    `{best_record_id, match_score: 0-5}`。
- 仲裁：一条记录被多块匹配取最高分；一图配一记录；score < 3 的记录标记补检
  （回 S1 加大返回量或 LLM 改写 query）。
- 测试集保险：420 条测试记录（评估 ground truth）的最终配对再做一次
  单图独立校验（"该图能否作为该 content 的参照图" yes/no），仅 +420 次调用。
- 预期存活率 30–50%；存活不足的组合标记回 S1 补检。
- 输出：`final/<record_id>.jpg` + `mapping.json` `{record_id: {image_path, score}}`
  + `filter_results.jsonl` `{path, keep, reason}`

### S4 导出校验 — `export_dataset.py`

- 按各记录 `image_url` 的路径约定拷贝到 `dataset/images/diagrams/`（train）
  和 `images/images_test/`（test，路径为 `../images/...`，需确认落盘位置）。
- 校验：每条记录都有图、文件可读、尺寸合法；产出覆盖率报告。
- 未对齐记录单独列清单，决定补检或暂时留空。

## 成本估算

| 项目 | 量级 | 备注 |
|---|---|---|
| Serper 检索 | ~2,057 次 | 免费 2,500 次额度内，补检需另算 |
| 图片下载 | ~15–20k 张 | 免费，带宽为主 |
| VLM 过滤+对齐（合并） | ~2,400 次调用 | 每组合 8 图/次；主要成本 |
| 测试集二次校验 | 420 次调用 | 仅测试集，保 ground truth 质量 |

## 与论文的差异（需知悉）

- 检索单位：论文是 21×30 矩阵（630 查询），实际数据是 2,057 个组合 —— 说明
  原始构建在矩阵基础上做了查询扩展/细化，论文附录的描述与实际数据不完全一致。
- 原管线第 3 阶段（从图逆向合成 content/query）**不需要重跑**：content/query
  已在 JSON 中，本管线只需反向找回与文本匹配的图。
- 无法恢复原图，只能恢复"等价分布"的图片；评估结论的可比性依赖 S2/S3 的过滤对齐质量。
