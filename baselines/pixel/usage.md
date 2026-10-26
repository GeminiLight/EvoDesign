# Pixel Baseline 使用指南

本目录保留两类真实可用入口：

- `apimart_image_generator.py`：通过 Apimart API 生成单张图片。
- `gemini_image_generator.py`：通过 Google GenAI/Gemini 生成单张图片或批量处理数据集。

Apimart 当前没有数据集批处理 CLI，因此不要把 Apimart 单图脚本当作批处理入口。

## 环境变量

Apimart 单图生成：

```bash
APIMART_API_KEY=your-api-key
APIMART_MODEL_NAME=gpt-4o-image
APIMART_API_BASE=https://api.apimart.ai/v1
```

Gemini 图片生成：

```bash
GEMINI_API_KEY=your-api-key
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
```

也可以通过项目根目录 `.env` 注入环境变量；两个脚本都会调用 `ensure_env_loaded()`。

## Apimart 单图生成

```bash
python -m baselines.pixel.apimart_image_generator \
  --text "Create a flowchart showing user login process" \
  --model gpt-4o-image \
  --output output.png
```

可选参数：

| 参数 | 说明 |
| --- | --- |
| `--model` | 覆盖 `APIMART_MODEL_NAME` |
| `--size` | 图片比例，例如 `1:1`、`16:9` |
| `--resolution` | 部分模型支持的分辨率，例如 `1K`、`2K`、`4K` |
| `--image-urls` | 参考图片 URL 列表 |

当前 `apimart_image_generator.py` 没有数据集批处理 CLI。如果需要批量跑 Apimart，应先补一个真实脚本并接入 `evo_diagram.core.experiment.get_baseline_output_dir()`，不要复用已经不存在的旧命令名。

## Gemini 单图生成

```bash
python -m baselines.pixel.gemini_image_generator \
  --text "Create a simple architecture diagram" \
  --output output.png
```

也可以从文本文件读取：

```bash
python -m baselines.pixel.gemini_image_generator \
  --input prompt.txt \
  --output output.png
```

## Gemini 数据集批处理

```bash
python -m baselines.pixel.gemini_image_generator \
  --dataset dataset/test/data.json \
  --output experiments/manual_pixel/gemini-2.5-flash-image
```

数据集每条样本会输出到：

```text
{output_dir}/{sample_id}/image.png
```

如果未提供 `--output`，脚本会使用：

```text
baselines/pixel/experiments/{GEMINI_IMAGE_MODEL}/
```

## 注意事项

1. `gemini_image_generator.py` 当前没有 `--start`、`--end`、`--regeneration`、`--max-concurrent` 等批处理参数。
2. `apimart_image_generator.py` 当前只支持单图生成。
3. 需要对齐正式 baseline 产物目录时，优先使用 `experiments/{exp_id}/outputs/baseline/pixel/{model}/{sample_id}/image.png` 这种当前实验目录结构。
4. 大规模批处理前先用 1-2 个样本做 API、模型名、输出路径的 smoke test。
