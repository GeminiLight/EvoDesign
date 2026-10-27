# EvoDesign 中文入门

开源仓库包含算法、前端、后端、渲染服务、自动精修、可选图标、设计知识与个人设计记忆，以及评测工具。项目与算法名称统一为 **EvoDesign**；Python 内部包名 `evo_diagram` 为兼容已有脚本而保留。

## 在线体验

打开 **[EvoDesign Studio](https://evodesign.vercel.app/)**，在“模型设置”里填写你自己的 API 地址、模型 ID 和 key。接口需要支持浏览器跨域访问（CORS）。无需部署后端；项目和设计偏好保存在当前浏览器，建议导出备份。

浏览器版提供生成、内容评审、局部编辑与导出；完整本地版还包含论文的视觉精修、设计知识检索与自动经验学习。详见[浏览器版说明](browser-edition.md)。

## 启动

需要 Python 3.11+、Node.js 22.12+ 和支持图像输入的模型接口。模型调用使用你自己的账号额度。

```sh
git clone https://github.com/GeminiLight/EvoDesign.git
cd EvoDesign
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[backend,test]"
npm ci --prefix frontend
npm ci --prefix evo_diagram/agentic_system/tool_services
python scripts/setup_local.py
```

在生成的根目录 `.env` 中填写 `LLM_MODEL_NAME`、`LLM_ENDPOINT_URL`、`LLM_API_KEY`，然后执行 `./scripts/start_service.sh`，访问 http://localhost:5175。停止服务：`./scripts/stop_service.sh`。首次渲染可能需要在 `evo_diagram/agentic_system/tool_services` 内执行 `npx playwright install chromium`；Linux 原生依赖见主 README。

图标可选，默认使用 Excalidraw；画布类型属于高级配置。自动精修与设计记忆默认开启，首次语义检索可能下载嵌入模型。

## 个人设计记忆

网页的 Your DNA 管理结构、样式和布局规则，支持启停、置顶与项目范围。源码同时提供从编辑前后差异提取偏好的研究流程。不要把每次手动移动都理解成自动写入永久记忆；提取与确认入口见各模块文档。

提供八条蓝紫风格的公开示例，不自动覆盖任何人的规则。`python scripts/design_memory.py validate examples/design-memory/blue-violet.json` 可离线检查；导入导出参见[完整说明](design-memory.md)。本地账户数据库、密钥和真实向量库不会随代码公开。

## 研究使用

训练集和测试集暂不随代码发布；使用自备输入或仓库中的简单运行示例。公开主页上的成绩来自论文，并不是本次发布重新跑出的结果。详见[复现说明](reproducibility.md)。
