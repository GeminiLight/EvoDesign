# VA04 校验、修复、质量与总编排核验报告

## 结论

核心质量策略及正常录制路径基本对齐，但不能声明算法完全无差异。新增边界复现确认 4 类 D/P2 偏差；本工作包未确认默认有效输入上的 P0/P1。未改产品源码、历史录制或比较器。

本包 29 个映射模块的 Python 源码都与 Git `1ac838f` 逐字节相同（A=B）；因此下述 D 来自 B→C，而非当前 Python 主动修改。

## 本轮执行

- 环境：本地无外部模型调用。Node24.22.1 / 现有venv；初次Node20结果另存，未作为唯一环境依据。
- 全部函数向量的新执行由主智能体负责；本报告只统计可用向量，不能替代主智能体执行结果。
- 613 个独立边界输入：586 精确一致，27 原始差异；其中一部分为同样拒绝输入但错误文字不同，其余按4类根因归并。
- 17 个模型mock/双图比较用例：15 一致，2 个null text片段改变重试；5个comparison模块用例均一致，补足其无独立函数向量的缺口。
- 边界覆盖：426质量阈值/回归/收益、50几何检查、40编辑保护、36收敛（含停滞）、7条件边/轮次、23评审输入、23修复状态、8验证状态。

### 端到端回放

- node20: 35/36；LLM matched/expected=156/158，snapshots=830/853。
- node: 35/36；LLM matched/expected=156/158，snapshots=830/853。
- memory: 35/36；LLM matched/expected=156/158，snapshots=830/853。

每组回放另有13次调用的caller标识未被严格验证（请求内容仍比较）；不能把matched数等同于所有调用者身份已核验。

唯一旧fixture失败为 `paper_full_f2__multi` 的 styling 快照：此前图标修复剥离节点顶层icon、转为可渲染规范对象，旧录制不再匹配。NodeFS/MemoryFS出现同一首处分歧。本轮未重录以掩盖差异，也不能声称该例当前下游状态已由旧回放完整验收。

## 已复现差异

### VA04-D01 / P2：float()词法规则改变模型分数与编辑坐标

- Python：Python拒绝7_、1__0；float(١)=1。
- TS：TS删除所有下划线：7_变7、7__0变70后评分钳为10，1__0变10并应用编辑；١被拒绝。
- 影响：同一合法JSON里的畸形数值字符串会被不同地接受或拒绝，改变评审是否成功、质量分数与几何编辑。
- 可达性限制：默认数字类型分数/坐标已检查一致；未发现真实模型历史回复使用这些字符串。Unicode例是Python float支持的输入，但非正常JSON number。
- 源码：`evodesign/agentic_system/verification_stage/critic/critic_agent.py:80`, `evodesign/agentic_system/refinement_stage/fixers/primitives.py:185`, `packages/render-engine/src/py/number.ts:179`, `packages/render-engine/src/verification_stage/critic/critic_agent.ts:134`。
- 证据：boundary-diffs.json: cases 440,441,442,445,531,532。

### VA04-D02 / P2：VerifierState未校验objective_summary的整型值

- Python：Pydantic Dict[str,int]在构造时抛ValidationError。
- TS：TS仅检查dict，major=oops得到NaN，quality_passed=true、cli_exit_code=0；null/空容器也未拒绝。
- 影响：错误状态数据可进入质量判断，状态构造/恢复的输入域与Python不同。
- 可达性限制：正常aggregator只生成整型计数，本轮未证明默认网页自动流程会生成该错误状态；直接状态构造已可复现。
- 源码：`evodesign/agentic_system/verification_stage/state.py:67`, `packages/render-engine/src/verification_stage/state.ts:142`, `packages/render-engine/src/verification_stage/state.ts:214`。
- 证据：boundary-diffs.json: cases 472,473,474,475,476,477,478,479。

### VA04-D03 / P2：Refiner状态的整数及可选浮点强制转换不等价

- Python：Pydantic接受max_iterations=2.0字符串并转2，接受合法下划线浮点1_0、NaN，拒绝十六进制0x10。
- TS：TS拒绝2.0、1_0、NaN，却用Number接受0x10=16及0b10=2。
- 影响：程序化控制/状态恢复可能提前报错，或接受Python拒绝的状态；有效整数轮次1..20及终止条件测试一致。
- 可达性限制：浏览器UI通常传number，best_findings_score由程序内部计算；未证明默认UI路径可达字符串输入。
- 源码：`evodesign/agentic_system/refinement_stage/state.py:124`, `evodesign/agentic_system/refinement_stage/state.py:136`, `evodesign/agentic_system/refinement_stage/state.py:153`, `packages/render-engine/src/refinement_stage/state.ts:81`, `packages/render-engine/src/refinement_stage/state.ts:101`。
- 证据：boundary-diffs.json: refiner_state cases。

### VA04-D04 / P2：空文本片段改变critic/refiner的成功与重试路径

- Python：Python str.join遇None抛TypeError；critic重试3次后失败；refiner重试3次，last_exhaustion_error记录失败。
- TS：TS critic的join把null合为空串；refiner pyStr后解析仍找到JSON；均1次成功，refiner无exhaustion。
- 影响：注入模型或保留非文本parts的提供商响应会改变调用次数、校验成功/失败和降级信息。
- 可达性限制：本轮使用注入model mock；主智能体另外通过createOpenAIChatModel与mock fetch确认浏览器模型transport保留该parts不变（VA06-crosscheck/content-parts-transport.json），因此该类响应可经transport到达。未验证真实服务商会发送该异常parts，不能称已发现默认真实服务商故障。
- 源码：`evodesign/agentic_system/verification_stage/critic/critic_agent.py:208`, `evodesign/agentic_system/refinement_stage/agent/llm_agent.py:262`, `packages/render-engine/src/verification_stage/critic/critic_agent.ts:290`, `packages/render-engine/src/refinement_stage/agent/llm_agent.ts:374`。
- 证据：retry-diffs.json: cases 5,11。

## 已核查的关键策略

对读质量目标7.0、视觉回退容忍0.5、critical/major/minor字典序、候选严重问题/约束违规/回退拒绝、确定性修复先行、保留未回退快照、首轮准备、stagnant/fixed point/resolved/max iterations、失败不提升候选、不可变候选最终再评审、失败保留原图与产物路径。所测有效数字与相同模型回复下，相关决策一致。Verifier 4节点、Refiner 3节点及条件边逐段对读，异步await改变调用形式但正常顺序保持。

## 覆盖与限制

- 映射模块 29；可用向量 8938，函数组 189。向量不是独立输入域或分支覆盖率。
- 手工成对读关键路径 6 模块，定向读部分 10 模块，其余 13 模块依赖本轮端到端与主智能体函数向量，未做完整源码审计。逐模块标记在coverage.json。
- 未对每条OSError/渲染器故障路径做故障注入；未穷举所有几何、图像和schema边界；有些异常文字差异只在直接无效状态构造可见。
- 记忆/学习与tldraw不是浏览器迁移目标，本轮不把这些范围的缺失认定为缺陷。
- Browser端最终可达性、模型HTTP处理和并发预算由VA05负责；本报告的Node/MemoryFS不能替代真实Worker证据。

## 可复现命令

```sh
export PATH=/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
cd /Users/zhanyi/Code/EvoDesign
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA04-quality/boundary_compare.py
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA04-quality/retry_compare.py
cd packages/render-engine
npm run parity:runs
npm run parity:runs -- --fs memory
```

原始输入、两端结果和差异在本目录JSON；命令输出在boundary.log/retry.log/runs-*.log。build_report.py只生成本目录报告，不更改生产或历史fixture。
