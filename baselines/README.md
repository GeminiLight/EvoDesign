# Baselines

这个目录收集了 EvoDesign 之外的对照方法，用来做文本到图表生成、图表代码生成、像素图生成，以及论文方法复现类 baseline。它们的输出形态不同：有的输出可编辑画布 JSON，有的输出 Mermaid/TiKZ/DOT 代码，有的直接输出 PNG。

## 快速对比

| Baseline | 目录 | 主要入口 | 输出 | 适合对比什么 | 主要配置 |
| --- | --- | --- | --- | --- | --- |
| Direct LLM | `direct_llm/` | `python -m baselines.direct_llm.main` | Excalidraw/Tldraw JSON，可选 PNG | 直接让 LLM 一步生成可编辑画布结构 | `LLM_MODEL_NAME`, `LLM_MODEL_PROVIDER`, `LLM_ENDPOINT_URL`, `LLM_API_KEY` |
| Code Mermaid | `programmic/mermaid/` | `python -m baselines.programmic.mermaid.main` | `.mmd` 和 Kroki 渲染 PNG | 文本到 Mermaid 代码的程序化 baseline | `LLM_MODEL_NAME`, `LLM_MODEL_PROVIDER`, `LLM_ENDPOINT_URL`, `LLM_API_KEY` |
| Code TiKZ | `programmic/tlkz/` | `python -m baselines.programmic.tlkz.main` | 终端打印 TiKZ 代码 | 文本到 LaTeX/TiKZ 代码的轻量单样本 baseline | `LLM_MODEL_NAME`, `LLM_MODEL_PROVIDER`, `LLM_ENDPOINT_URL`, `LLM_API_KEY` |
| Pixel Gemini | `pixel/` | `python -m baselines.pixel.gemini_image_generator` | PNG | 直接图像生成模型的像素级 baseline | `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`, `GEMINI_IMAGE_MODEL` |
| Pixel Apimart | `pixel/` | `python -m baselines.pixel.apimart_image_generator` | PNG | 通过 Apimart 调多种图像模型 | `APIMART_API_KEY`, `APIMART_MODEL_NAME`, `APIMART_API_BASE` |
| DiagramAgent | `diagramagent/` | `python -m baselines.diagramagent.DiagramAgentEvaluator` | TikZ/DOT 编译后的 PNG、代码、`results.json` | Plan -> Code -> Check 风格的 diagram-code agent | `ELYSIVER_*` 或 `OPENAI_*`，本机需 LaTeX/Graphviz 渲染依赖 |
| SciSketch | `scisketch/` | `python -m baselines.scisketch.src.custom_main` | Draw.io/Mermaid/TiKZ/SVG 文件，可选 PNG | SciSketch 两阶段论文图生成流程 | `ELYSIVER_*` 或 `OPENAI_*`，PNG 导出可选 Docker |

## 数据集格式

大多数批处理入口默认使用 `dataset/test/data.json` 这类 JSON list。常用字段如下：

| 字段 | 说明 |
| --- | --- |
| `id` | 样本 ID，也会用于输出文件名 |
| `content` 或 `text` | 主要文本内容 |
| `query` 或 `query_v1` | 用户意图、图表标题或生成要求 |
| `diagram_type` 或 `type` | 可选图表类型提示 |
| `image_url` 或 `image` | coding/editing 或评估对齐时可用的参考图路径 |

## 统一运行脚本

根目录脚本 `scripts/run_baselines.sh` 可以批量跑部分 baseline：

```bash
DATASET=dataset/test/data.json \
MODELS=qwen3-vl-plus,glm-4.7 \
ALGORITHMS=mermaid,direct_llm,pixel,diagramagent,scisketch \
START=0 \
END=10 \
MAX_CONCURRENT=2 \
./scripts/run_baselines.sh
```

输出默认写入：

```text
experiments/{EVO_EXPERIMENT_ID 或当天日期}/outputs/baseline/
```

注意：`programmic/tlkz/main.py` 当前 CLI 只支持 `--input` 单条输入，还没有和 Mermaid 一样的 `--dataset/--output-dir` 批处理参数。因此使用统一脚本时，除非先补齐 TiKZ 批处理入口，否则不要把 `tlkz` 放进 `ALGORITHMS`。

## PROXY_A 配置

仓库根目录 `.env` 里已有 `PROXY_A_API_KEY` 时，可以把 OpenAI-compatible baseline 指向 PROXY_A：

```bash
export LLM_MODEL_PROVIDER=openai
export LLM_MODEL_NAME=gpt-5.5
export LLM_ENDPOINT_URL=https://api.your-proxy-endpoint/v1
export LLM_API_KEY="$PROXY_A_API_KEY"
```

也可以直接使用 `configs/models.yaml` 里的模型别名，例如 `gpt-5.5` 或 `kimi-k2.6`。不要直接 `source .env`，因为根目录 `.env` 里有一些说明/占位行不是 shell 语法；让 Python 的 dotenv/config loader 读取，或只手动导出需要的变量。

`diagramagent/` 和 `scisketch/` 使用 `ELYSIVER_*` / `OPENAI_*` 变量。如果要用 PROXY_A，可这样导出：

```bash
export ELYSIVER_API_KEY="$PROXY_A_API_KEY"
export ELYSIVER_BASE_URL=https://api.your-proxy-endpoint/v1
export ELYSIVER_MODEL=gpt-5.5
```

如果本地 `baselines/diagramagent/.env` 会覆盖这些变量，可以临时加：

```bash
export PYTHON_DOTENV_DISABLED=1
```

## Direct LLM

`direct_llm/` 是最直接的结构化画布 baseline：把文本和 query 交给 LLM，直接生成 Excalidraw 或 Tldraw JSON。它适合作为“没有拆分结构、布局、样式步骤”的强基线。

常用命令：

```bash
python -m baselines.direct_llm.main \
  --dataset dataset/test/data.json \
  --model qwen3-vl-plus \
  --canvas-library excalidraw \
  --max-concurrent 2 \
  --render
```

单条文本：

```bash
python -m baselines.direct_llm.main \
  --text "Create a flowchart for user login" \
  --output baselines/direct_llm/output/login.json \
  --render
```

配置方式：

```bash
LLM_MODEL_NAME=qwen3-vl-plus
LLM_MODEL_PROVIDER=openai
LLM_ENDPOINT_URL=https://apis.iflow.cn/v1
LLM_API_KEY=...
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=64000
LLM_OUTPUT_DIR=results/baselines/direct_llm
```

也可以通过命令行传 `--model`, `--provider`, `--base-url`, `--api-key`, `--temperature` 覆盖环境变量。

## Programmic

`programmic/` 是代码生成类 baseline，目标不是直接出画布 JSON，而是让 LLM 输出图表 DSL，再渲染为图片。

### Mermaid

Mermaid baseline 会生成 `.mmd`，并通过 Kroki 渲染 PNG。适合快速流程图、架构图、概念关系图的代码化对比。

```bash
python -m baselines.programmic.mermaid.main \
  --dataset dataset/test/data.json \
  --model qwen3-vl-plus \
  --output-dir experiments/dev/outputs/baseline/code_mermaid/qwen3-vl-plus \
  --start 0 \
  --end 10 \
  --max-concurrent 2
```

单条输入：

```bash
python -m baselines.programmic.mermaid.main \
  --input "User submits credentials, server validates them, then creates a session" \
  --query "Show the authentication flow"
```

### TiKZ

TiKZ baseline 当前是单样本入口，会把生成的 TiKZ/LaTeX 代码打印到终端。它适合快速检查模型能否生成出版级图表代码，但还不是完整的批处理评估入口。

```bash
python -m baselines.programmic.tlkz.main \
  --input "Create a pipeline diagram for retrieve, plan, render, evaluate" \
  --query "Show each stage and data flow" \
  --max-tokens 4096
```

Programmic 通用配置：

```bash
LLM_MODEL_NAME=qwen3-vl-plus
LLM_MODEL_PROVIDER=openai
LLM_ENDPOINT_URL=https://apis.iflow.cn/v1
LLM_API_KEY=...
TEMPERATURE=0.7
MAX_TOKENS=64000
TIMEOUT=300
```

Mermaid 渲染依赖 Kroki；如果网络或服务不可用，`.mmd` 仍会保存，但 PNG 渲染可能失败。

## Pixel

`pixel/` 是直接图像生成 baseline，不追求可编辑结构，重点对比最终视觉结果。

### Gemini

```bash
python -m baselines.pixel.gemini_image_generator \
  --dataset dataset/test/data.json \
  --model gemini-2.5-flash-image \
  --output experiments/dev/outputs/baseline/pixel/gemini-2.5-flash-image
```

单图：

```bash
python -m baselines.pixel.gemini_image_generator \
  --text "Create a clean architecture diagram for a FastAPI backend and React frontend" \
  --output baselines/pixel/output.png
```

配置：

```bash
GEMINI_API_KEY=...
# 或 GOOGLE_API_KEY=...
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
```

### Apimart

```bash
python -m baselines.pixel.apimart_image_generator \
  --text "Create a flowchart showing user login process" \
  --model gpt-4o-image \
  --size 1:1 \
  --output baselines/pixel/output.png
```

配置：

```bash
APIMART_API_KEY=...
APIMART_MODEL_NAME=gpt-4o-image
APIMART_API_BASE=https://api.apimart.ai/v1
```

Apimart 当前只提供 `apimart_image_generator.py` 单图生成入口；数据集批处理请使用 `gemini_image_generator.py`，或先补齐真实的 Apimart 批处理脚本。

## DiagramAgent

`diagramagent/` 实现 PlanAgent -> CodeAgent -> CheckAgent 流程：先扩展用户需求，再生成 TikZ/DOT 代码，最后编译检查并可用 LLM 做修复/语义验证。

```bash
python -m baselines.diagramagent.DiagramAgentEvaluator \
  --dataset dataset/test/data.json \
  --output baselines/diagramagent/results/dataset_test \
  --start 0 \
  --end 10 \
  --task generation \
  --use-gpt4o \
  --write-eval-artifacts \
  --eval-baseline-type diagramagent \
  --eval-model-name glm-5.1
```

配置：

```bash
ELYSIVER_API_KEY=...
ELYSIVER_BASE_URL=https://your-endpoint/v1
ELYSIVER_MODEL=glm-5.1

# 或使用 OpenAI 兼容配置
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# 可选：启用 image-to-code agent
DIAGRAMAGENT_ENABLE_D2C=1
```

本机渲染依赖：

```text
pdflatex
pdftoppm
dot
```

其中 `pdflatex/pdftoppm` 用于 TikZ -> PDF/PNG，`dot` 用于 Graphviz DOT -> PNG。

## SciSketch

`scisketch/` 是基于 SciSketch 的改造版入口，支持原始 parsed paper 输入，也支持本项目数据集格式。默认输出 Draw.io XML，也可以切到 Mermaid/TiKZ/SVG。

```bash
python -m baselines.scisketch.src.custom_main \
  --dataset dataset/test/data.json \
  --language drawio \
  --save_directory baselines/scisketch/generated_diagram \
  --start 0 \
  --end 10 \
  --export_png \
  --write_eval_artifacts \
  --eval_baseline_type scisketch \
  --eval_model_name glm-5.1
```

可选语言：

```text
drawio, mermaid, tikz, svg
```

配置：

```bash
ELYSIVER_API_KEY=...
ELYSIVER_BASE_URL=https://your-endpoint/v1
ELYSIVER_MODEL=glm-5.1

# 或
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# 兼容 SciSketch 原版配置
API_KEY=...
API_BASE=https://your-endpoint/v1
API_MODEL=gpt-4o-mini
```

如果使用 `--export_png` 导出 Draw.io PNG，需要 Docker，并会使用默认镜像：

```text
b1f6c1c4/draw.io-export:latest
```

没有 Docker 时仍可生成 `.drawio` 文件，但 PNG 导出会失败或被跳过。

## 结果组织

建议把所有 baseline 输出放在同一个实验 ID 下，方便后续评估：

```text
experiments/{exp_id}/outputs/baseline/
├── code_mermaid/{model}/{sample_id}/
│   ├── input.json
│   ├── diagram.mmd
│   └── render.png
├── direct_llm/{model}/{sample_id}/
│   ├── scene.json
│   └── render.png
├── pixel/{model}/{sample_id}/
│   └── image.png
├── diagramagent/{model}/{sample_id}/
│   ├── code.txt
│   └── render.png
└── scisketch/{model}/{sample_id}/
    ├── {sample_id}.json
    └── {sample_id}_final.drawio
```

带 `--write-eval-artifacts` 的入口会额外写出评估兼容结构，通常包含：

```text
{sample_id}/render.png
{sample_id}/reference.jpg
{sample_id}/input.json
mapping.json
```

## 验证入口是否可用

这些模块有一个轻量入口测试：

```bash
pytest tests/baselines/test_baseline_entrypoints.py
```

它只检查 `--help` 是否正常，不会真实调用模型 API。真实生成前请先确认对应 `.env`、模型 endpoint、渲染依赖和输出目录权限。
