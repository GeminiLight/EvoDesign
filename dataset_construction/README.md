# Dataset Construction

按论文 CanvasBench 管线（`research/evo_diagram/sections/appendix/canvas-benchmark.tex`）重建数据集图片。

## 背景

`dataset/train/data.json`（5,854 条）与 `dataset/test/data.json`（420 条）中的
`image_url` 均为本地相对路径，图片文件与原始 URL 均未保存在仓库中。
本目录用于重新检索、下载、过滤图片，并与现有 (query, content) 记录对齐。

## 管线（对应论文三阶段）

1. **检索**：以 `dataset/*` 记录中的 `diagram_type × vertical_domain` 构造查询
   （`"<diagram_type> diagram of <vertical_domain>"`），调用图片搜索 API 下载候选图。
   - API 选项：Serper `/images`（注册送 2,500 次，单请求返回量大，推荐）；
     Google CSE（100 次/天免费，单请求最多 10 张，需翻页）。
2. **过滤**：用 VLM（论文用 Qwen3-VL-Max）剔除手绘草图、复杂数据可视化、
   照片型信息图、模糊文档等高熵图片，保证 canvas-recoverability。
3. **对齐**：校验候选图与记录已有 `content`/`query` 的语义匹配度，
   产出新的 (image, query, content) 三元组。

## 目录结构

- 代码、CSV、映射、日志在本目录 `dataset_construction/`
- 数据产物在 `dataset/` 下：
  - `candidates.json` — 候选台账（每张图的 URL、来源页、状态、phash 等元数据）
  - `filtered.json` — S2+S3 过滤+对齐产物
  - `final.json` — S4 导出产物
  - `raw/<combo_slug>/` — 所有候选图片文件

详细设计见 `PIPELINE.md`（S2 过滤与 S3 对齐已合并为一轮 VLM 调用）。

## 目标规模

- 对齐论文口径：2,260 张（测试 210 + 进化 2,050）
- 对齐仓库全量：6,274 张（训练 5,854 + 测试 420）

## 重建结果（2026-07-24）

- `dataset/final.json`：**3,150 条**（630 组合 = 21 类型 × 30 MMMU 领域 × 5 张），
  每条含 image_url(本地)/source_url(原始)/page_url/content/query/bench/other_queries(8变体)
- 每组合 1 条 bench 标杆（共 630 条）
- `dataset/design_memory.json`：**126 条**三层设计专家记忆
  （K^s 84 + K^g 30 + K^p 12，schema 对齐论文附录）
- 图片不进 git（版权与体积考虑）；可用 `candidates.json`（42k URL 台账）
  + `python dataset_construction/main.py download` 重建
- 管线：plan / collect / download / filter / bench / assemble / variants / memory，
  详见 `PIPELINE.md`
