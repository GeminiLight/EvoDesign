# 图表评估系统

## 概述

图表评估系统是一个基于多模态大语言模型（VLM-as-Judge）的自动质量评估工具。系统使用聚合 Prompt 对生成的图表从 **4 个维度** 进行打分，每个维度 1–5 分。

| 维度 | 评估内容 |
|------|----------|
| **content_dimension** | 内容保真度、概念逻辑、语义相关性 |
| **visual_dimension** | 视觉美感、风格一致性、流程连贯性、空间平衡 |
| **cognitive_dimension** | 认知易读性、理解准确度、自包含解释 |
| **judge_preference** | 与真实参考图的整体偏好对比（相对评估） |

### 加权平均分（Human-Centered Calibration）

为防止信息覆盖度高但视觉粗糙、认知负荷大的图表只靠"内容齐全"取胜，`average_score` 不再是各维度的算术均值，而是按"人类阅读效用"加权：

- `content_dimension`: **0.25**
- `visual_dimension`: **0.35**
- `cognitive_dimension`: **0.40**

同时 prompt 内置了若干硬性上限（text-dump、模板化、单调配色、缺少视觉焦点等场景下相关分数被强制压低），以惩罚"把原文塞进框框"式的伪高分图表。详见 `prompts/metric_prompts_merged.py` 中的 `HUMAN_CENTERED_CALIBRATION` 段落。

这些上限的触发条件全部是**与渲染技术无关的可观测特征**（节点视觉权重是否一致、配色是否编码语义、标签是否迫使线性阅读等），
prompt 中不出现任何具体渲染工具名。理由是：点名某种渲染技术会把质量判断变成技术判罚，同一张图仅因产出工具不同而被封顶。
`tests/evaluation/test_prompt_neutrality.py` 会守住这一点。

## 模块结构

```
evaluation/
├── run_evaluation.py          # 批量评估 CLI 入口
├── metric_scorer.py           # MetricScorer 评估器（核心）
├── path_resolver.py           # 根据方法名解析图像/输出路径
├── utils.py                   # 图像编码、结果保存、文本报告
├── evaluate.sh                # Bash 包装脚本 (in scripts/)
├── analysis/
│   ├── analysis_results.py    # 统计聚合与报告生成
│   ├── stats.py               # 标准库实现的 bootstrap / Wilcoxon 检验
│   └── test_data_availability.py  # 检查数据集项的图像可用性
├── metrics/
│   ├── __init__.py            # METRIC_CLASSES 注册表
│   ├── base_metric.py         # BaseMetric、MetricResult 基类
│   ├── content_metrics.py     # ContentDimensionMetric
│   ├── visual_metrics.py      # VisualDimensionMetric
│   └── cognitive_metrics.py   # CognitiveDimensionMetric + JudgePreferenceMetric
└── prompts/
    ├── __init__.py
    └── metric_prompts_merged.py   # 4 维度聚合 Prompt 模板
```

## 核心组件

### 1. MetricScorer

**文件**: `evaluation/metric_scorer.py`

继承自 `BaseAgent`，负责管理指标实例并执行图像评估。

```python
from evo_diagram.core.llm_factory import LLMFactory
from evaluation.metric_scorer import MetricScorer

model = LLMFactory.create(
    model="qwen3-vl-plus",
    temperature=0.3,
    max_tokens=4000,
)
scorer = MetricScorer(model, metrics_to_use=["content_dimension", "visual_dimension"])

results = scorer.evaluate_image(
    image_path="diagram.png",
    context_text="source text",
    reference_image_path="reference.png",  # judge_preference 需要参考图
)
```

主要方法：
- `evaluate_image()` — 使用所有配置的指标评估单张图像
- `evaluate_single_metric()` — 使用单个指标评估
- `generate_summary()` — 静态方法，聚合多张图像的评估结果

### 2. 指标（Metrics）

**目录**: `evaluation/metrics/`

| 指标类 | 维度 | 文件 |
|--------|------|------|
| `ContentDimensionMetric` | content | `content_metrics.py` |
| `VisualDimensionMetric` | visual | `visual_metrics.py` |
| `CognitiveDimensionMetric` | cognitive | `cognitive_metrics.py` |
| `JudgePreferenceMetric` | cognitive | `cognitive_metrics.py` |

所有指标均继承自 `BaseMetric`（`base_metric.py`），返回类型为 `MetricResult`。

### 3. 提示词（Prompts）

**文件**: `evaluation/prompts/metric_prompts_merged.py`

包含 4 个维度的聚合提示词模板。每个 Prompt 包含：
- 评估维度描述
- 子项定义
- 评分标准（1–5 分）
- 要求的 JSON 输出格式

### 4. 路径解析器

**文件**: `evaluation/path_resolver.py`

根据方法名解析生成图像路径和输出目录：

```python
from evaluation.path_resolver import parse_method_paths

image_path, output_dir, ref_path = parse_method_paths("evodiagram", "data_001")
```

支持的方法名格式：

| 格式 | 说明 | 示例 |
|------|------|------|
| `evodiagram` | 自动检测子模型 | `evodiagram` |
| `evodiagram/<submodel>` | 显式指定子模型 | `evodiagram/gpt-5.2` |
| `evodiagram_wo_refiner` | 无 Refiner 版本 | `evodiagram_wo_refiner` |
| `evodiagram_wo_refiner/<submodel>` | 无 Refiner + 子模型 | `evodiagram_wo_refiner/gpt-5.2` |
| `evodiagram-local` | 本地实验目录 | `evodiagram-local` |
| `evodiagram_*` | 其他旧格式变体 | `evodiagram_claude` |
| `baselines/<type>/<model>` | Baseline 斜杠格式 | `baselines/code_mermaid/gemini-3-pro` |
| `baselines_<type>_<model>` | Baseline 下划线格式 | `baselines_code_mermaid_gemini-3-pro` |

### 5. 工具函数

**文件**: `evaluation/utils.py`

- `encode_image_to_base64()` — 图像转 base64
- `get_image_mime_type()` — 根据扩展名获取 MIME 类型
- `save_results()` — 将字典保存为 JSON 文件
- `create_evaluation_report()` — 生成人类可读的文本报告
- `list_image_files()` — 列出目录中的图像文件

## 环境配置

评估系统使用根目录 `configs/settings.yaml` 中的 `evaluation.role` 选择评估模型角色，并通过 `configs/models.yaml` 解析 provider、模型名、endpoint 与 API key 环境变量引用。`.env-evaluation` 仍可用于本地覆盖 API key 环境变量，但不再作为模型选择的主配置。

| 变量 | 说明 |
|------|------|
| 配置 | 说明 |
|------|------|
| `configs/settings.yaml` → `evaluation.role` | 评估使用的角色，默认 `eval` |
| `configs/settings.yaml` → `roles.eval` | `eval` 角色绑定的模型 |
| `configs/models.yaml` → `models` / `providers` | 模型、provider、endpoint 与 API key 环境变量引用 |

## 使用方式

### 批量评估（CLI）

```bash
# 默认数据集，评估全部指标
python -m evaluation.run_evaluation --method evodiagram

# 显式指定子模型
python -m evaluation.run_evaluation --method evodiagram/gpt-5.2

# 指定配置文件
python -m evaluation.run_evaluation --method evodiagram --settings configs/settings.yaml --model-config configs/models.yaml

# 临时指定评估角色
python -m evaluation.run_evaluation --method evodiagram --eval-role eval

# 评估某个 baseline
python -m evaluation.run_evaluation --method baselines/code_mermaid/gemini-3-pro

# 评估 Mermaid baseline（baselines/mermaid 是 code_mermaid 的别名，路径自动归一）
python -m evaluation.run_evaluation --method baselines/mermaid/gpt-5.5

# 评估 direct_llm baseline
python -m evaluation.run_evaluation --method baselines/direct_llm/gpt-5.5

# 并行评估
python -m evaluation.run_evaluation --method evodiagram --workers 4

# Judge 重采样：每个 (样本, 指标) 独立评 3 次，最终分取中位数
python -m evaluation.run_evaluation --method evodiagram --judge-runs 3

# 仅评估指定指标
python -m evaluation.run_evaluation --metrics content_dimension visual_dimension

# 强制重新评估（默认会跳过已有结果）
python -m evaluation.run_evaluation --method evodiagram --regeneration

# 指定数据范围（1-based）
python -m evaluation.run_evaluation --method evodiagram --start 1 --end 50

# 显示详细日志
python -m evaluation.run_evaluation --method evodiagram --verbose
```

### Bash 包装脚本

```bash
./scripts/evaluate.sh --method evodiagram --workers 4
```

### Judge 重采样（--judge-runs）

评委端点强制 `temperature=1`，同一张图重复评分存在采样方差，单次评分的数字不足以支撑论文结论。
`--judge-runs k`（默认 1，行为与旧版完全一致）让每个 (样本, 指标) 被独立评 k 次（串行），再聚合回一个分数：

- **最终分 = k 次有效分的中位数**。分数是 1–5 整数，中位数比均值更稳且保持整数语义；
  有效分为偶数个时取两个中间值中较小的那个（lower median），保证结果仍是整数且偏保守。
- **有效分**：`status: scored`、无 error、分数落在 1–5 区间内的 run。error / N/A 的 run 不参与中位数。
- **失败阈值**：有效分数 < `ceil(k/2)` 时，整个 (样本, 指标) 记为 `error`（不允许用少数派聚合出分数）。
  唯一例外：k 次全部 `not_applicable`（如 `judge_preference` 缺参考图）时保持 `not_applicable`，
  因为这是永久性条件而不是采样失败。
- k > 1 时每个指标结果新增 `judge_runs` 字段：
  `{k, values, n_valid, n_error, n_not_applicable, errors, mean, std, median}`；
  `score` 即中位数，`reason` / `sub_scores` / `details` 取自第一个命中中位数的 run 的真实评委输出。
  k = 1 时不写该字段，输出与旧版一致。
- `run_signature` 记录 `judge_runs`：k 改变后旧结果被判 `stale` 并重跑；
  该字段出现之前写入的结果文件按 k=1 处理，默认（k=1）运行仍可复用它们。
- 聚合端 `analysis_results.py` 在 `dimension_stats` 中为每个指标输出 `judge_retest_variance`
  （所有样本 judge 内 std 的均值 `mean_within_sample_std`、最大值、range 均值），
  即论文可报告的「评委重测信度」。仅当结果文件携带 `judge_runs` 数据时出现该字段。

```bash
# CLI 单方法
python -m evaluation.run_evaluation --method evodiagram --judge-runs 3

# 批量脚本（JUDGE_RUNS 环境变量透传，默认 1）
JUDGE_RUNS=3 ./scripts/run_evaluation.sh
```

### 结果分析（CLI）

```bash
# 分析单个算法
python evaluation/analysis/analysis_results.py experiments/{exp_id}/scores/evodiagram

# 对齐到完整测试集，缺失样本单独统计（推荐：论文数字必须带 --dataset）
python evaluation/analysis/analysis_results.py experiments/{exp_id}/scores \
    --dataset dataset/test/data.json --summary

# 把"未生成图"的样本按 0 分计入（默认是 exclude）
python evaluation/analysis/analysis_results.py experiments/{exp_id}/scores \
    --dataset dataset/test/data.json --missing-policy zero

# 与某个方法做配对显著性检验（Wilcoxon signed-rank + bootstrap CI）
python evaluation/analysis/analysis_results.py experiments/{exp_id}/scores \
    --dataset dataset/test/data.json --compare-to evodiagram/evodiagram/gpt-5.2

# 显式指定方法目录（关闭自动发现）
python evaluation/analysis/analysis_results.py experiments/{exp_id}/scores \
    --method baseline/code_mermaid/gpt-5.2 --method evodiagram/evodiagram/gpt-5.2
```

#### 缺失样本口径

`--missing-policy` 决定"方法没有生成图"的样本如何进入均值：

| 口径 | 含义 |
|------|------|
| `exclude`（默认） | 只对打出分的样本求均值，同时报告 `missing_rate` 与 `valid_n` |
| `zero` | 未生成图的样本按 0 分计入均值 |

默认取 `exclude`，因为 0 分不在 prompt 定义的 1–5 量表内，零填充后的均值与量表分不可直接比较。
无论选哪种口径，`dimension_stats` 中都同时给出 `mean` 与 `mean_missing_as_zero`，两种读法都不会被隐藏。

评测本身失败（judge 报错）、指标 N/A（缺参考图导致 `judge_preference` 无定义）、以及根本没有结果文件的样本，
在两种口径下都被排除并单独计数，因为它们不是方法本身的失败。

### 数据可用性检查

```bash
python evaluation/analysis/test_data_availability.py \
    --input-json dataset/test/data.json \
    --diagram-dir experiments/{exp_id}/outputs/evodiagram/evodiagram
```

检查脚本只验证图片是否存在；正式评估仍通过 `--method` 和 `--exp-id` 解析路径：

```bash
python -m evaluation.run_evaluation \
    --input-json dataset/test/data.json \
    --method evodiagram/gpt-5.5 \
    --exp-id {exp_id}
```

## 输出格式

### 单条评估 JSON

```json
{
  "timestamp": "2026-01-27T10:30:00",
  "data_id": "example_001",
  "method": "evodiagram",
  "status": "success",
  "reference_image_available": true,
  "run_signature": {
    "signature_version": 1,
    "judge_role": "eval",
    "judge_model": "step-3.7-flash",
    "judge_temperature": 0,
    "judge_max_tokens": 8000,
    "metrics": ["cognitive_dimension", "content_dimension", "judge_preference", "visual_dimension"],
    "prompt_versions": { "content_dimension": "a1b2c3d4e5f6" }
  },
  "dimensions": {
    "content": {
      "content_dimension": {
        "metric": "content_dimension",
        "score": 4,
        "sub_scores": {
          "content_fidelity": 4,
          "concept_logic": 4,
          "semantic_relevance": 4
        },
        "reason": "..."
      }
    },
    "visual": { ... },
    "cognitive": { ... }
  },
  "scores": {
    "content_dimension": 4,
    "visual_dimension": 3,
    "cognitive_dimension": 4,
    "judge_preference": 3
  },
  "average_score": 3.5
}
```

### 分析汇总 JSON

```json
{
  "analysis_directory": "experiments/{exp_id}/scores",
  "dataset": "dataset/test/data.json",
  "missing_policy": "exclude",
  "bootstrap_resamples": 10000,
  "bootstrap_seed": 12345,
  "total_algorithms": 3,
  "algorithms": [
    {
      "algorithm_name": "baseline/pixel/flux-2-flex",
      "missing_policy": "exclude",
      "sample_counts": {
        "full_set_n": 210,
        "full_set_source": "dataset",
        "result_files_n": 205,
        "success_n": 188,
        "failed_n": 5,
        "missing_output_n": 12,
        "no_result_file_n": 5,
        "missing_rate": 0.081
      },
      "missing_output_data_ids": ["..."],
      "dimension_scores": { "content_dimension": 1.91 },
      "dimension_stats": {
        "content_dimension": {
          "n": 188, "valid_n": 188, "full_set_n": 210, "excluded_n": 22,
          "excluded_reasons": { "missing_output": 12, "evaluation_error": 5, "no_result_file": 5 },
          "mean": 1.91, "std": 0.74, "sem": 0.054,
          "ci95_bootstrap": [1.80, 2.02],
          "mean_missing_as_zero": 1.80, "zero_filled_n": 12
        }
      },
      "sub_scores": { "content_dimension_content_fidelity": 1.87 },
      "sub_score_stats": { "content_dimension_content_fidelity": { "n": 188, "std": 0.8 } }
    }
  ],
  "comparisons": [
    {
      "algorithm_name": "baseline/pixel/flux-2-flex",
      "reference": "evodiagram/evodiagram/gpt-5.2",
      "metric": "content_dimension",
      "n_pairs": 185,
      "mean_difference": -1.42,
      "wilcoxon": { "statistic": 812.0, "p_value": 0.0001, "method": "normal-approximation-with-tie-correction" },
      "bootstrap_ci95_of_mean_difference": [-1.58, -1.26]
    }
  ],
  "summary": {
    "total_algorithms": 3,
    "dimension_averages": { },
    "coverage": { "baseline/pixel/flux-2-flex": { "full_set_n": 210, "missing_rate": 0.081 } }
  },
  "warnings": ["..."]
}
```

> `total_files` 字段已移除。它统计的是结果文件数，而 `extract_scores` 会跳过失败样本，
> 于是报告中的 n 大于真正参与均值的 n。现在 `sample_counts` 与每个指标的 `valid_n` 分别给出「全集 n」和「有效 n」。

## 评分标准

| 分数 | 含义 |
|------|------|
| 5 | 优秀 — 完全符合要求 |
| 4 | 良好 — 有小瑕疵 |
| 3 | 可接受 — 达到最低标准 |
| 2 | 较差 — 存在明显问题 |
| 1 | 不可接受 — 严重缺陷 |

## 添加新指标

1. 在 `metrics/` 下创建继承 `BaseMetric` 的类
2. 在 `prompts/metric_prompts_merged.py` 中添加提示词模板
3. 在 `metrics/__init__.py` 的 `METRIC_CLASSES` 中注册
4. 在 `metric_scorer.py` 的 `DIMENSION_METRICS` 中分配维度

## 依赖

- Python 3.11+
- `langchain-core`
- 支持视觉输入的多模态 LLM（如 Qwen-VL、GPT-4o）

## Refiner asymmetry

### 不对称的存在

EvoDesign 默认启用 refiner 做多轮迭代精修（`evo_diagram/agentic_system/main.py` 的
`--refiner-iterations` 默认 3；经 `scripts/run_evodiagram.sh` 运行时由 `REFINER_ITERS`
环境变量控制上限，当前脚本默认 1），而所有 baseline 都是单次生成、0 轮精修。
直接拿 EvoDesign（full）与 baseline 比较，会把 refiner 带来的增益全部归因于系统设计本身，
审稿人有理由质疑该比较不公平。

### 两种处理选项

1. **给每个 baseline 也接上 refiner**：消除不对称，但成本高（每个 baseline 多 k 轮
   生成/评审调用），且本仓库的 refiner 是围绕 EvoDesign 的 canvas 契约设计的，
   接到 mermaid / direct-LLM / pixel 等异构产物上会引入新的实现混淆变量。
2. **用 wo_refiner 消融变体与 baseline 对齐**：EvoDesign 额外跑一个关闭 refiner 的
   变体（`ABLATION=wo_refiner`），它与 baseline 一样是 0 轮精修，作为对齐比较行；
   full 结果同时报告，full 与 wo_refiner 的差值单独量化 refiner 的贡献。

**本仓库采用选项 2**：论文主表同时报告 EvoDesign `full` 与 `wo_refiner` 两行，
与 baseline 的对齐比较使用 `wo_refiner` 行。该方案不需要修改任何生成代码，
只依赖 `scripts/run_evodiagram.sh` 已有的消融变体机制。

### wo_refiner 变体怎么跑

`scripts/run_evodiagram.sh` 用 `ABLATION` 环境变量选择变体预设。`ABLATION=wo_refiner`
会向 main.py 传 `--variant evodiagram_wo_refiner`，该预设在 Python 侧置
`enable_refiner=False`（不再传 `--refiner-iterations`），产物写入
`experiments/{exp_id}/outputs/evodiagram/evodiagram_wo_refiner/{model}/{item_id}/`：

```bash
# 生成（可与 MODELS / DATASET / START / END 组合）
ABLATION=wo_refiner ./scripts/run_evodiagram.sh
ABLATION=wo_refiner MODELS=kimi-k3 ./scripts/run_evodiagram.sh

# 评估：--evodiagram_wo_refiner 会把 method 切换为 evodiagram_wo_refiner
python -m evaluation.run_evaluation --method evodiagram --evodiagram_wo_refiner

# 等价的显式写法（推荐：显式指定子模型，避免多 backbone 歧义）
python -m evaluation.run_evaluation --method evodiagram_wo_refiner/kimi-k3

# 批量评估脚本
METHODS=evodiagram_wo_refiner/kimi-k3 ./scripts/run_evaluation.sh
```

得分写入 `experiments/{exp_id}/scores/evodiagram/evodiagram_wo_refiner/{submodel}/`，
在 `analysis_results.py` 报告中呈现为独立算法行（如
`evodiagram/evodiagram_wo_refiner/kimi-k3`），与 full 行（`evodiagram/evodiagram/kimi-k3`）
使用同一个 `--dataset` 对齐口径。

## 结果口径约定

- **分数区间**：所有指标分数必须落在 1–5。落在区间外（含 0）视为解析/生成失败，
  以 `status: "error"` + `error` 记录，不进入任何均值。
- **N/A 指标**：`judge_preference` 的 1–5 锚点全部按「Image A 优 / Image B 优」定义，
  缺参考图时该指标记为 `status: "not_applicable"`，从聚合中排除，而不是降级成绝对打分。
- **缺图样本**：找不到生成图时写入 `status: "missing_output"` 的显式失败记录，
  聚合端按 `--missing-policy` 处理并报告缺失率。
- **断点续跑**：结果文件带 `run_signature`（评委模型、温度、重采样次数 `judge_runs`、指标集合、prompt 哈希）。
  签名不匹配时重跑而不是复用；`--rerun-failed` 只重跑不可复用的样本。
  `judge_runs` 字段出现之前的旧结果按 k=1 处理。
- **Judge 重采样**：`--judge-runs k`（k>1）时每个 (样本, 指标) 独立评 k 次，最终分取有效分的中位数
  （偶数个有效分取 lower median）；有效数 < ceil(k/2) 记 error；k 次全 N/A 保持 N/A。
  详见「Judge 重采样」一节。
- **可复现性**：评委温度取自 `configs/models.yaml`（当前为 0），CLI 不再硬编码覆盖。
