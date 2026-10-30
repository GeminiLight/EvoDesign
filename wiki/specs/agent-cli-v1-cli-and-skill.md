<!-- Last verified: 2026-10-30 | Current stage: Agent CLI v1 implemented contract -->

# Agent CLI v1：CLI 与 Skill 契约

实际实现见 [cli](../../cli/) 与 [Skill](../../skills/evodesign/SKILL.md)。[中英文使用指南](../../docs/agent-collaboration.md) 给出可运行步骤；本页解释实现分工。架构见 [共享文档与版本边界](spec-agent-cli-v1.md)。

## 发行与文件

包名 `evodesign-cli`，入口 `evodesign`，版本 `0.1.0`，Python ≥3.11。仅依赖 httpx 及其依赖，不安装或导入后端、图表引擎、模型或渲染浏览器。后端与渲染器在服务器一端运行。

```text
cli/pyproject.toml
cli/src/evodesign_cli/
  __init__.py       # 版本
  __main__.py       # python -m 入口
  main.py           # argparse、配对、命令、输出和退出码
  client.py         # HTTP、服务地址、读取重试、超时与错误
  config.py         # profile 与私有凭据文件
cli/tests/test_cli.py
skills/evodesign/
  SKILL.md
  references/cli.md
  references/operations.md
examples/agent_cli/quickstart.py
```

首版保持薄客户端，没有尚未存在的 auth.py、output.py 或 commands 包。安装从源码 `python -m pip install ./cli`，不要求公共包已发布。多 profile 表达不同项目连接。

## 配对和本地状态

`connect --server ORIGIN --profile NAME` 发起配对，stderr 打印短码和批准链接；默认打开系统浏览器，`--no-browser` 仅打印。批准页使用既有 Web 登录，选择现有 Excalidraw 项目或创建真实空文档，明确“仅候选”或“可提交”。

CLI 轮询一次性领取，获准后保存不透明项目 token，不复制 Web JWT。默认目录 `~/.config/evodesign`，可由导出的 `EVODESIGN_CONFIG_DIR` 指定。目录私有，文件 0600，写入用临时文件替换。profile 元信息与凭据分文件，输出不包含 token。

连接二十四小时到期，首版无静默刷新。Web 可撤销，disconnect 撤销并清本地记录；如果服务不可用，明确报告未确认远端撤销，但本地记录仍移除。文件权限在 macOS/Linux 路径验证，Windows 存储不作已验证承诺。

## 实际命令

| 命令 | 结果 |
| --- | --- |
| connect / disconnect | 项目配对 / 撤销与本地清理 |
| connection status | 项目、状态、提交权限和到期 |
| project get / open | 元信息 / 在浏览器打开项目 |
| document get | 当前场景、版本、节点、约束、能力和 Web 链接 |
| document preview --output FILE [--version N] | 下载该正式版本的真实 PNG |
| context get | 已保存 DNA、硬锁、选区状态和交接版本 |
| proposal create --file FILE [--operation-id ID] | 不提交的不可变候选 |
| proposal get / wait ID | 启动或恢复检查、读状态；wait 超时不等于失败 |
| proposal preview ID --output FILE | 下载经认证的候选 PNG |
| proposal commit / reject ID | 显式提交 / 拒绝 |
| history list [--limit N] | 工作快照和检查点元信息 |
| history restore ID --base-version N [--operation-id ID] | 生成恢复候选，不回退计数器 |

没有 generation、任意 JSON patch、同步本地工程目录或 MCP 命令。完整语法以 [命令参考](../../skills/evodesign/references/cli.md) 和 `--help` 为准。

## 输出、超时和不确定写入

命令支持在子命令前后放置 `--profile` 和 `--json`。JSON 模式 stdout 只有一个 `{ok, protocol_version:1, data}` 或错误信封，诊断写 stderr；help/version 使用常规帮助和版本输出。

退出码：2 输入、3 凭据、4 权限或不存在、5 版本/上下文/状态冲突、6 无效编辑、7 检查失败、8 网络/服务/等待超时。框架字段错误不回显输入凭据；CLI 同时兼容标准 HTTP 验证错误。

GET 可在同一超时预算内有限重试。写入不盲目自动重试。候选创建的错误保留 operation_id，已知候选操作错误保留 proposal_id。相同操作 ID 与相同内容可找回原候选；不同内容复用 ID 被拒绝。提交成功结果可重复读取，不产生第二个正式版本。

机器调用应区分 queued、ready 和 committed。ready 只表示结构和渲染通过，仍须看图。断线或超时后先查已有结果，不能认为没有写入；真正冲突后重新读文档，准备新操作和新 ID。

## Skill 的职责

Skill 是方法和使用契约，状态保存在服务器。每批编辑前读取 document 与 context，比较用户目标和绑定项目，读取有效 DNA 和能力，不自动换项目或扩大范围。

新图先确定实体与关系，再选择尺寸、布局和颜色。局部编辑保留 ID、人工布局和无关对象。使用共享选区时带 context_version；空或过期选区不能当整图。独立新增和连接需要获授权的项目范围，绑定文字属于节点语义范围。

先创建候选，记录 ID，等待检查，下载真实 PNG，使用宿主看图能力检查。不能看图就明确说明，不能把未检查说成已检查。用户任务与连接权限允许时提交，否则交回 Web 审阅；不对已授权的普通动作反复要求确认。

版本冲突后重读并重做，最多自动尝试两次冲突恢复，保留候选。恢复也走同一预览/提交流程。输出应含项目链接、正式版本或待审候选 ID、修改摘要和未解决检查发现。

## 可运行示例与验证

先连接空项目，再运行 `python examples/agent_cli/quickstart.py --profile paper`。示例读取真实文档/上下文，创建两个节点与连接，等待并下载 PNG，不自动提交，且拒绝修改非空项目。

验证分为 CLI 包契约、HTTP 与版本边界、真实渲染、真实 Web 交接。一次配对或一张 PNG 不能代替完整协作验收。不同宿主可以安装同一 Skill；本次宿主验证使用已有 Codex 会话，不把这一结果宣称为已测试每一种 Agent CLI。
