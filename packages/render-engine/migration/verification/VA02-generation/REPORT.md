# VA02 生成与决策算法核验报告

结论：不能认定迁移前后算法完全等价。已证实两项生产行为偏差：合法特殊语义ID在TS样式层丢失；非默认并发自一致性在浏览器发生预算串扰并改变多数票结果。图标修复另计为主动改变。生产代码、历史fixtures和harness未修改。

## 核验基线和范围

A=`1ac838f`原始Python；B=冻结工作区Python；C=Node TS；D=使用实际BrowserAsyncContext的TS。40个映射模块已登记，其中15个关键控制流模块作了定点源码审查；其余以提示词内容或fixture清单核验，不能表述为全部函数逐行证明。A→B仅StylingAgent源码改变，已经用git原文独立执行确认。

## 新增差分探针

- 2229个有效新探针：2217个一致，12个差异。差异全部是同一个`__proto__`根因的6种icon载荷×2个作用点，不能计成12项独立缺陷。
- 34个提示词/字符串常量SHA-256全部一致。
- 资源拼装与palette/图标/compact开关：474个组合全部一致。
- 覆盖输出本身、异常类型/消息与调用后参数；不使用原harness的“任意throw即通过”规则。独立脚本开发初次曾把Python keyword-only参数错误地按位置传递，已修正并完整重跑，当前2229项统计不含该探针错误。
- 新探针覆盖Unicode/JSON严格宽松解析、每个前缀截断、viewport阈值、schema随机变异、compact模板、布局元组、flow grid、特殊semantic key和真实资源拼装。
- 自一致性额外三端受控调用链：Python9请求/architecture、Node9请求/architecture、BrowserAsyncContext7请求/flowchart。此实验与2229同步探针分开计数。
- 规范化后的unified修复提示词另做对比：57771字符逐字相同；反馈受控注入，未作为完整真实失败链验收。

## 已证实差异

### G-D01 · D · P1 · 合法 __proto__ 语义节点在 Styling 字典写入时丢失并导致校验失败

Structure 包含合法字符串节点 id=__proto__，模型返回该 ID 的样式对象；无须开启图标。

迁移前：原始 A 和当前 B 均通过 Structure 和 Styling 校验，own 字典项保留。
迁移后：TS Structure 接受；processed[element_id]=copied 改变 processed 的原型，Object.keys(processed)=[]，validate_styling_instantiation 抛 StylingValidationError: Styling instantiation must be a JSON object; got Object.

影响：有效模型输出在生成阶段中断；与 R 发现的 converter 普通对象语义键问题属于同一跨阶段根因。

建议：所有 semantic-id map 使用 Map 或无原型字典并确保 deep-copy/validator/序列化兼容；禁止只修一个写入点。

复现命令（仓库根目录）：

```sh
export PATH=/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA02-generation/repro-baseline.py
node packages/render-engine/node_modules/tsx/dist/cli.mjs packages/render-engine/migration/verification/VA02-generation/repro-prototype.ts
```

证据：[baseline-diff.json](baseline-diff.json), [prototype-ts.json](prototype-ts.json), [probe-results.json](probe-results.json)

### G-D02 · D · P1 · 浏览器并发自一致性样本共用调用预算，改变有效样本与多数票结果

structure_self_consistency_n=3（默认1不触发）；每样本第一次返回坏JSON，修正请求遭遇一次可重试传输错误，接着提供有效响应。transport_attempts=2、json_retry_attempts=2。

迁移前：Python ContextVar 和 Node AsyncLocalStorage：每个样本请求3次，attempts=[3,3,3]，9请求，2:1选中 architecture，返回 sample1。
迁移后：相同请求/响应安排，production BrowserAsyncContext 下 attempts=[3,2,2]，7请求；两个样本因共用最后一个budget而提前失败，剩下 sample0 的 flowchart 胜出。

影响：仅一条pipeline/Worker也会触发，因为其内部自一致性样本并发。改变调用次数、失败容忍和图类型决策；平台变化已经影响算法。

建议：显式传递每次logical call预算或引入正确的async上下文隔离；不要通过关闭自一致性/串行化掩盖原并发算法差异。修复后加入该三端差分回归。

复现命令（仓库根目录）：

```sh
export PATH=/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA02-generation/repro-budget.py
node packages/render-engine/node_modules/tsx/dist/cli.mjs packages/render-engine/migration/verification/VA02-generation/repro-budget.ts node
node packages/render-engine/node_modules/tsx/dist/cli.mjs packages/render-engine/migration/verification/VA02-generation/repro-budget.ts browser
```

证据：[budget-python.json](budget-python.json), [budget-node.json](budget-node.json), [budget-browser.json](budget-browser.json)

### G-I01 · I · P2 · 图标字段兼容与内置图标校验是明确的主动行为修复

模型输出节点顶层 icon=outline_globe，或 props.icon=outline_globe。

迁移前：A：顶层icon原样留在节点但没有伴随图标；嵌套outline_globe被降级为label。
迁移后：B/C：顶层与嵌套均提取为 n:icon，保留outline_globe；新探针普通ID全部一致。

影响：此项改善缺图标，但意味着不能声称相对原始A完全相同；不是Python→TS翻译偏差。

建议：在总报告的主动差异台账中保留。

复现命令（仓库根目录）：

```sh
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA02-generation/repro-baseline.py
```

证据：[baseline-diff.json](baseline-diff.json), [probe-results.json](probe-results.json)

### G-U01 · U · P3 · 未覆盖全部统一生成修复及通用agent工具分支

统一生成normalize/validate多次失败、任意tools绑定、全部9样本并发混合时序等路径。

迁移前：本轮进行了源码关键分支检查及一个规范化后的受控修复提示词实验。
迁移后：该受控修复assistant echo逐字相同（57771字符），未发现旧notes所述整数浮点风险在此用例复现；这不证明全部失败路径等价。

影响：明确限制等价结论，不把未复现的历史风险升级为已证实缺陷。

建议：后续对实际normalize/validate失败链、tools和其他并发调度补全差分录制。

复现命令（仓库根目录）：

```sh
PYTHONPATH=. .venv/bin/python packages/render-engine/migration/verification/VA02-generation/repro-unified-repair.py
export PATH=/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
node packages/render-engine/node_modules/tsx/dist/cli.mjs packages/render-engine/migration/verification/VA02-generation/repro-unified-repair.ts
```

证据：[unified-repair-diff.json](unified-repair-diff.json)

## 可确认一致的局部算法

- 源码定点检查保留三阶段串行顺序，结构校验一次修正后再裁剪未实现ledger、严格/最终宽松JSON策略、图类型冲突拒绝、palette校验、显式边标签回填、group alias精确匹配、flow grid资格和边端口来源。
- 自一致性的取最高票/并列首样本策略在Node和Python源码一致；当前差异来自D的async context使样本先失败，并非投票公式本身改变。
- 生成资源内容、stage knowledge组合、常量提示词和palette组合在本轮输入域完全相同。

## 证据边界

- 本报告的legacy fixture向量数是清单计数，不是本子智能体新跑的通过数；全量函数由VA01主智能体负责，端到端回放由VA04负责，避免并发覆盖报告。
- Router/Structure/Styling/Layout/Unified的模型原始回复不能由真实模型两次出图比较来证明相同，本轮全为本地mock和固定输入。
- 没有真实外部模型调用、没有安装新依赖、没有提交部署。
- [完整覆盖清单](coverage.json)包含每模块新增探针数量、旧向量数量和未由新增探针直接触达的callable。
