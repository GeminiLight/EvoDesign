# 用已有 Agent 与 EvoDesign 协作

[English](agent-collaboration.md) · [项目说明](../README.zh-CN.md)

让终端里的 Agent 读取论文、代码或笔记，准备一张可编辑图，检查真实预览，再接着你在 Web 中的修改继续工作。Skill 描述工作方法，独立 CLI 负责连接项目。

首版支持**后端版的 Excalidraw 项目**。公开浏览器版把项目保存在本机浏览器中，这些项目不能与 CLI 共享。MCP 和 TLDraw 编辑留待后续。

## 安装与连接

按 [本地运行说明](../README.zh-CN.md#本地运行) 启动后端、前端和渲染服务。`FRONTEND_URL` 应指向批准连接的 Web 地址。使用自定义渲染端口时，还需将 `EXCALIDRAW_RENDER_URL` 设为该服务的 `/renderers/excalidraw` 页面地址。

在仓库根目录，用独立 Python 3.11+ 环境安装 CLI：

```sh
python3 -m venv .venv-cli
source .venv-cli/bin/activate
python -m pip install ./cli
evodesign --version
evodesign connect --server http://localhost:3010 --profile paper
```

CLI 只依赖 `httpx` 及其依赖，不安装或导入图表引擎。后端和渲染器运行在保存项目的一端。Agent 编辑使用确定性操作、结构检查和 PNG 渲染，不调用 EvoDesign 的生成模型；Web 中原有的生成流程使用自己的模型配置。

在 Web 登录，输入终端显示的配对码，选择一个 Excalidraw 项目，也可以新建空白项目。默认选择“由我审阅并应用”；选择“允许 Agent 直接应用”后，Agent 可以提交。每个连接只访问一个项目，24 小时后到期。可在项目的 Agent 面板撤销，或运行 `evodesign disconnect --profile paper`。

如需自行打开批准链接，添加 `--no-browser`。远程后端要求 HTTPS，本机回环地址支持 HTTP。`--server` 填服务根地址，不带 `/api/v1`。

## 让已有 Agent 使用 Skill

如需先跑通一个完整候选，在批准连接时选择空白项目，再运行：

```sh
python examples/agent_cli/quickstart.py --profile paper
```

它会创建两个节点的候选并下载真实 PNG，不自动提交，也不会修改非空项目。到 Web 审阅并接受即可；这个例子不需要模型密钥。

Skill 位于 [skills/evodesign/SKILL.md](../skills/evodesign/SKILL.md)，旁边有命令和操作参考。按当前 Agent 的 skill 安装方式注册该目录。也可以先直接对 Agent 说：

> 读取本仓库的 `skills/evodesign/SKILL.md` 并按其中流程工作。使用已经连接的 `paper` profile，把我的材料画成可编辑图。检查真实 PNG，后续修改时保留其他节点的人工调整。

Agent 需要能够调用终端中的 `evodesign`。视觉检查还需要宿主的看图能力；如果不能看图，应说明并把视觉确认交给你。CLI 不另外启动一个 Agent 或模型会话。

## 读取、准备、审阅、提交

```sh
evodesign document get --profile paper --json
evodesign context get --profile paper --json
# Agent 使用返回的版本、元素 ID 和约束摘要编写 ops.json。
evodesign proposal create --profile paper --file ops.json --operation-id YOUR_UNIQUE_ID --json
evodesign proposal wait PROPOSAL_ID --profile paper --timeout 90 --json
evodesign proposal preview PROPOSAL_ID --profile paper --output preview.png --json
# 查看 preview.png 和检查报告，再决定提交。
evodesign proposal commit PROPOSAL_ID --profile paper --json
```

将大写占位值替换为真实结果。[操作参考](../skills/evodesign/references/operations.md) 定义输入格式。支持新增节点、连接、改字、改样式、移动节点和删除节点六类操作。每批操作声明整个项目或明确的元素范围；首版不支持任意原生 JSON 补丁，也没有 CLI 生成命令。

创建候选不会修改正式文档。`ready` 表示结构校验和 PNG 渲染成功。仍需阅读几何问题并查看真实图片；服务端没有对 Agent 候选进行视觉模型评审。失败候选保留报告，应修正后用新的操作 ID 准备候选。

提交时会检查原始版本和已保存约束，创建检查点并递增版本。重复提交同一个已提交候选会返回已有结果，不重复创建版本。写入响应丢失时，先查询该候选，再决定是否重试。

Web 的 Agent 面板可查看连接、带标识的候选、图片预览和检查点，也可以接受无提交权限的 Agent 产生的候选。画布干净且页面可见时，约每两秒检查一次外部更新；离线时放慢检查，页面重新可见或网络恢复时继续。

## 在 Web 审阅设计

打开画布右上角的 **Agent**。候选设计、连接和检查点各有入口。审阅区左侧选择方案，右侧查看真实 PNG；可切换原尺寸检查细节。图片成功加载后，点击 **应用到画布**，再回到可编辑画布继续修改。失败、过期、冲突和已提交记录都可以在“全部”中查看。

![真实候选的桌面审阅界面](screenshots/agent-collaboration/review-desktop.jpg)

连接页提供终端命令、配对步骤、权限与到期时间；断开前可以取消。检查点恢复先准备候选，仍需审阅后应用。

## 接着 Web 中的修改继续

保存人工修改后，让 Agent 重新读取文档。只编辑另一个节点时，已保存的人工位置和无关元素会保留。Web 与 Agent 使用同一份有效 DNA：存在项目规则时优先使用项目规则，清空项目规则后继承账号规则。未同步的本地偏好不会被当作 Agent 已知的服务端约束。

在画布选中元素，打开目标连接的“共享选区”。系统先保存，再发布选中 ID，绑定保存版本并保留十分钟。Agent 使用这次交接时携带返回的 `context_version`。过期或空选区不会自动扩大为整个项目。原生锁定元素、绑定文字和锁定图片数据受到保护。

如果外部版本到达时 Web 还有未保存修改，会暂停自动保存并保留当前画布。打开 Agent 面板，可看正式版本的 PNG、下载本地 `.excalidraw` 草稿，再明确选择是否替换。查看旧检查点时，也会保留当前历史视图，直到你选择使用正式版本。

如果候选创建后版本或 DNA 发生变化，提交会返回冲突并保留候选。应重新读取，结合最新修改准备新候选，不能把旧场景套上新版本号提交。

## 恢复与检查

```sh
evodesign project open --profile paper
evodesign document preview --profile paper --output saved.png --json
evodesign history list --profile paper --json
evodesign history restore SNAPSHOT_ID --profile paper --base-version CURRENT_VERSION --operation-id YOUR_UNIQUE_ID --json
```

恢复操作先从检查点创建候选，仍需经过预览和提交。它创建一个新版本，不回退版本计数器，也不修改旧检查点。历史通过 `is_checkpoint` 区分工作快照和检查点；检查点之后的自动保存会另建工作快照。

## 自动化与凭据

所有命令都接受 `--profile` 和 `--json`。JSON 模式只向 stdout 输出一个协议 v1 信封，诊断写入 stderr。[CLI 参考](../skills/evodesign/references/cli.md) 列出全部命令与退出码：2 输入，3 凭据，4 权限或项目不存在，5 冲突，6 无效操作，7 预览失败，8 网络、服务或等待超时。

Profile 和不透明的项目凭据默认保存在仓库外的 `~/.config/evodesign`。目录设为私有，凭据文件权限为 `0600`；也可通过 `EVODESIGN_CONFIG_DIR` 指定另一个私有位置。不需要复制 Web token。文件权限已在 macOS/Linux 路径上验证，首版尚未验证 Windows 凭据存储。

共享 API、版本检查和模块边界见 [架构与实施契约](../wiki/specs/spec-agent-cli-v1.md)。
