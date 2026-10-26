# Handy Direct LLM Refiner

## 快速开始

```bash
# 基础用法 (python -m 方式，从项目根目录运行)
python -m baselines.direct_llm.handydirectllmrefiner --method baselines_direct_llm_gpt-5.2 --iterations 1 --limit 1

# 指定范围
python -m baselines.direct_llm.handydirectllmrefiner --method baselines_code_mermaid_gemini-3-pro --start 10 --limit 20 --iterations 5

# 处理全部数据
python -m baselines.direct_llm.handydirectllmrefiner --method baselines_pixel_flux-2-flex --iterations 3

# 自定义VLM参数（temperature和max_tokens）
python -m baselines.direct_llm.handydirectllmrefiner --method baselines_direct_llm_gpt-5.2 --temperature 0.5 --max-tokens 8000 --iterations 3

# 或使用相对路径 (从 baselines/direct_llm/ 目录运行)
python handydirectllmrefiner.py --method baselines_direct_llm_gpt-5.2 --iterations 3 --limit 5

# 指定环境文件和输出后缀
python -m baselines.direct_llm.handydirectllmrefiner --method baselines_direct_llm_gpt-5.2 --env .env-tencent --output-suffix _vlmrefined --iterations 2
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--method` | 必填 | 方法名称，格式：`baselines_<type>_<model>` |
| `--iterations` | 3 | 优化迭代次数 |
| `--limit` | 0 | 限制处理数量，0表示全部 |
| `--start` | 0 | 起始索引（从0开始） |
| `--dataset` | `dataset/test/data.json` | 数据集路径 |
| `--output-suffix` | `_refined` | 输出文件后缀 |
| `--env` | `.env` | VLM配置文件路径（相对项目根目录） |
| `--temperature` | `REFINER_LLM_TEMPERATURE` 或 0.3 | VLM temperature参数 |
| `--max-tokens` | `REFINER_LLM_MAX_TOKENS` 或 4000 | VLM最大token数 |

### --method 可用值

**格式**: `baselines_<type>_<model>`
**路径解析**: `experiments/{exp_id}/outputs/baseline/<type>/<model>/`
**模型覆盖**: 解析 `--method` 的 `<model>` 并设置 `REFINER_LLM_MODEL_NAME=<model>`，例如：
`baselines_direct_llm_gpt-5.2` → `REFINER_LLM_MODEL_NAME=gpt-5.2`

> 说明：该目录必须存在（需要先完成对应 baseline 生成）。优化输出会与原始 PNG/JSON 保存在同一目录中。

#### Code Mermaid
```
baselines_code_mermaid_deepseek-r1
baselines_code_mermaid_gemini-3-pro
baselines_code_mermaid_glm-4.7
baselines_code_mermaid_gpt-5.2
baselines_code_mermaid_kimi-k2-0905
baselines_code_mermaid_qwen3-coder-plus
baselines_code_mermaid_qwen3-vl-plus
```

#### Code TLKZ
```
baselines_code_tlkz_deepseek-r1
baselines_code_tlkz_gemini-3-pro
baselines_code_tlkz_glm-4.7
baselines_code_tlkz_gpt-5.2
baselines_code_tlkz_kimi-k2-0905
baselines_code_tlkz_qwen3-coder-plus
baselines_code_tlkz_qwen3-vl-plus
```

#### Direct LLM
```
baselines_direct_llm_gemini-3-pro
baselines_direct_llm_glm-4.7
baselines_direct_llm_gpt-5.2
baselines_direct_llm_kimi-k2-0905
baselines_direct_llm_qwen3-vl-plus
```

#### Pixel
```
baselines_pixel_doubao-seedance-4-0
baselines_pixel_doubao-seedance-4-5
baselines_pixel_flux-2-flex
baselines_pixel_flux-kontext-pro
baselines_pixel_gemini-2.5-flash-image-preview
baselines_pixel_gemini-3-pro-image-preview
baselines_pixel_gpt-4o-image
baselines_pixel_gpt-4o-image_train
```

## 环境配置

在 `.env` 文件中添加：

```bash
# 必需配置
REFINER_LLM_MODEL_PROVIDER=openai
REFINER_LLM_MODEL_NAME=qwen3-vl-plus
REFINER_LLM_API_KEY=sk-xxxxxxxxxxxxx
REFINER_LLM_ENDPOINT_URL=https://apis.iflow.cn/v1

# 可选配置（可通过CLI参数覆盖）
REFINER_LLM_TEMPERATURE=0.3
REFINER_LLM_MAX_TOKENS=4000
```

**配置优先级**：CLI参数 > 环境变量 > 默认值

## 前置条件

1. 启动渲染服务: `cd evo_diagram/agentic_system/tool_services && npm run dev`
2. 配置 `.env` 中的 `REFINER_LLM_*` 变量
3. 确保 baseline 数据已生成

## 输出文件

```
experiments/{exp_id}/outputs/baseline/<type>/<model>/
├── {data_id}.json                      # 原始文件
├── {data_id}.png
├── {data_id}_refined_iter1.json        # 第1轮
├── {data_id}_refined_iter1.png
├── {data_id}_refined_iter2.json        # 第2轮
├── {data_id}_refined_iter2.png
├── {data_id}_refined_final.json        # 最终版本
└── {data_id}_refined_final.png
```

> 备注：`--output-suffix` 会替换 `_refined`，并影响 `*_iterN` 与 `*_final` 文件名。
