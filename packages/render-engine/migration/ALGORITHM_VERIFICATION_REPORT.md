# 迁移前后算法核验报告

**结论：常规路径已有强一致证据，但现在不能保证迁移前后算法完全相同。** 本轮确认 **2项P1、8项P2、2项P3迁移偏差**；同一个 `__proto__` 根因在两个阶段复现，合并为一项。图标修复另列主动变化，共享模型策略与准备调度另列适配，不混算成翻译缺陷。

本轮按事先落盘的计划启动了三个子智能体，分别审计生成决策、确定性布局渲染、质量校验修复；主智能体负责基线、测试可信度、网页平台和关键发现交叉复现。生产代码、历史fixture及比较器均未修改，无真实外部模型请求、无提交或部署。

[核验计划](ALGORITHM_VERIFICATION_PLAN.md) · [机器可读差异清单](verification/findings.json) · [模块及覆盖台账](verification/coverage.json)

入库范围及大体量原始捕获的再生成方式见 [证据说明](verification/README.md)。

## 1. 四组基线

| 组 | 内容 | 本轮使用方式 |
|---|---|---|
| A | Git `1ac838f`：添加TS包之前的Python/后端 | Git原文读取；关键图标分支动态加载独立复现 |
| B | 开始核验时工作区Python | 对比A，仅StylingAgent与相关测试有改变 |
| C | 当前TS在Node运行时 | Node24.22.1；函数、阶段、pipeline、HTTP对照 |
| D | 当前TS在真实浏览器/Worker | 新构建包、MemoryFS、Chromium及本地mock |

当前HEAD为 `8504d46`，工作区有原有迁移改动，未重置。初始冻结950个路径；核验后拆分为687个源码/资源与263个Next生成缓存。687个源码/资源均无哈希漂移；2个Next缓存变化单列，不是生产算法修改。

## 2. 新执行的主要证据

| 检查 | 本轮结果 | 解释 |
|---|---:|---|
| 全套TS测试 | 1,199/1,199项 | 其中877项函数测试含138个模块报告项，不能当作向量数 |
| 原函数向量对照 | 34,504通过 / 458跳过 | 共34,962条，旧规则失败0；跳过不算已核验 |
| 独立收紧的函数重放 | 34,497匹配 / 7异常消息差异 / 458跳过 | 7条中1条异常类型真差异；其余含录制截断/路径适配。返回值及检查到的副作用新差异0 |
| kwargs副作用补验 | 31,918条一致 | 只计无需输入adapter且允许mutation比较的向量 |
| 渲染阶段串联 | 112/112样例 | 全部阶段最大数值差0，不只看最终manifest |
| 渲染阶段隔离 | 1,008/1,008阶段 | 每个阶段用Python上阶段输入隔离比较 |
| 完整pipeline NodeFS | 35/36 | 唯一paper失配由主动图标变化引起 |
| 完整pipeline MemoryFS | 35/36 | 同一个paper首处分歧；与Node一致 |
| backend→TS网页回放 | 27/28 | 同一paper在Layout提示词失配；未重录掩盖 |
| 新构建真实Worker | 自有模型3/3，共享模式1/1 | 固定mock/cassette，含取消验证；不代表所有配置 |
| 生成/决策新增探针 | 2,217一致 / 2,229组 | 12个差异归并为一个特殊ID根因 |
| 质量/修复新增边界 | 586一致 / 613组 | 27个原始差异按4类根因记录，含异常文字差别 |
| 评审/修复/双图mock | 15一致 / 17组 | 2组null text响应改变重试路径 |
| 特殊crop PNG | 7一致 / 8组 | 1-bit图片发生真实裁剪偏差 |
| 内置图标 | 399/399一致 | 133图标×3种颜色/无效颜色，SVG、dataURL、file ID均比较 |
| 新渲染像素抽样 | 2/2完全相同 | quickstart两个mode，字节/像素/crop一致；历史224图证据没有冒充本轮全量重跑 |
| 类型检查/浏览器构建 | 通过 | 62资源，bundle无node builtins |

另外，34个提示词/常量哈希一致；474个知识资源/调色板/compact组合一致；400个随机网格几何路线及memo key一致，其中26组仅负零表示不同。两次真实模型生成的视觉差别没有被用作算法等价或不等价的判断依据。

## 3. 两项优先修复的P1

### AUD-D01：合法节点ID `__proto__` 在TS字典中消失

两端schema都接受该ID。Python普通字典保留节点；TS `processed[id]=...` 和converter分桶使用普通 `{}`，该键会改写对象原型而不成为自有键。

- 样式阶段：Python通过，TS丢掉样式键后报 `StylingValidationError`。
- 渲染阶段：用同一布局绕过前者独立核验，Python产出20个元素，TS只有18个，丢节点与标签。
- 对照ID `n_control`、`constructor`、`toString` 均一致。影响需要特殊ID，不表示常规112例都失败。

应系统检查所有semantic-ID索引，改用Map或无原型字典并兼容copy/schema/序列化；只修单个赋值点不充分。

[生成证据](verification/VA02-generation/prototype-ts.json) · [渲染交叉复现](verification/VA06-crosscheck/mutants-recheck.log)

### AUD-D02：浏览器并发多样本投票会串用重试预算

设置 `structure_self_consistency_n=3`、`transport_attempts=2`、`json_retry_attempts=2`。固定每个样本先坏JSON，再遇一次可重试传输异常，随后可成功。Python ContextVar与Node AsyncLocalStorage分别保留预算；浏览器 `BrowserAsyncContext` 仅存一个全局store，内部并发样本互相干扰。

| 相同模拟响应安排 | 各样本请求数 | 总请求 | 最终图类型 |
|---|---|---:|---|
| Python | [3,3,3] | 9 | architecture |
| Node TS | [3,3,3] | 9 | architecture |
| 实际Chromium中的TS | [3,2,2] | 7 | flowchart |

主智能体已独立打包并在真实Chromium复现，非仅静态推测。默认单样本不触发；但一条Worker内也有并发，不能用“每次只跑一条pipeline”证明上下文安全。应显式传递每次logical call预算或提供正确的异步上下文隔离，保留原采样算法。

[三端原始证据](verification/VA02-generation/REPORT.md) · [真实Chromium复现](verification/VA06-crosscheck/budget-real-chromium.json)

## 4. 其它已确认偏差

| ID / 级别 | 触发与迁移前后差别 | 可达性/影响限制 |
|---|---|---|
| AUD-D03 / P2 | 1-bit PNG：Python crop 78×56，TS 100×11；packed像素未解包 | 常规网页导出8-bit RGBA不触发 |
| AUD-D04 / P2 | Python整数2^53写成`9007199254740992`，TS写成`.0`结尾 | 已知旧边界重新复现；未证明常规布局已有可见影响 |
| AUD-D05 / P3 | 网格Set规范化负零 | 几何相同，严格表示不同 |
| AUD-D06 / P2 | `7_`/`7__0`被TS接受为7/70再钳分，Python拒绝；`1__0`被TS应用为坐标10 | 正常JSON数字一致，畸形数值字符串改变评审/编辑决策 |
| AUD-D07 / P2 | `objective_summary.major='oops'`：Python拒绝，TS产生NaN却`quality_passed=true` | 内部状态/恢复输入边界，正常aggregator产整数 |
| AUD-D08 / P2 | refiner state用Number或严格字符串规则，区别于Pydantic的`'2.0'`、`'1_0'`、NaN/十六进制规则 | 普通UI传number，不是已证实默认UI故障 |
| AUD-D09 / P2 | 响应parts含`text:null`：Python重试3次失败，TS一次解析成功 | 两端实际HTTP模型mock均保留parts；未证明真实provider会发该异常payload |
| AUD-D10 / P2 | 网页`base_version='1'/'1.0'/true`：Python转1，TS拒绝 | 前端通常不传或传number，程序化API域不同 |
| AUD-D11 / P2 | 未显式use_icons且marker为空dict/list：Python false，TS true | 改变公共streamDiagram默认策略；当前前端显式传开关通常避开 |
| AUD-D12 / P3 | `get_styling_contract()`漏参数：Python TypeError，TS ValueError | 错误内部调用契约，原harness漏检 |

每项的源码位置、输入、两端结果、复现脚本、影响和建议保存在 [findings.json](verification/findings.json)。分域完整记录：[生成决策](verification/VA02-generation/REPORT.md)、[布局渲染](verification/VA03-render/REPORT.md)、[质量修复](verification/VA04-quality/REPORT.md)、[网页平台](verification/VA05-platform/REPORT.md)。

## 5. 主动改变与平台差异

**图标修复是A→B/C的主动变化**：原顶层icon未转换，内置outline图标还可能降级为label；现在两端统一提取为可见规范图标。不能为了声称等价撤销这次修复，也不能把旧paper录制失配判成TS独有错误。

该paper例主智能体用Git原始两个Styling方法动态载入验证：A的旧web回放成功且所有产物一致，B在Layout调用2与TS出现相同首处分歧。新行为在该例下游尚未通过原cassette完整核验；报告保留35/36、27/28，不写全绿。

**共享模型是不同配置**：强制服务器模型、非流式、thinking disabled、输出上限；默认text-only跳过视觉critic，allowlist还会省略部分字段。它符合第三期限定的服务模式，但不能外推为与自有模型/后端默认完全相同。

**refiner预准备调度不同**：Python并行准备，TS先await准备再verification；正常决策/结果回放一致，调度、等待和计时不是同一个行为。此处没有作新的性能基准。

## 6. “全绿”证据的限制及补验

原比较器接受相对1e-9，可能把seed量级整数相差1判为完全相同而不计容差；Map找不到键时按位置比值；预期异常只检查任意throw；Worker smoke的事件llm_calls引用expected值。这些是测试盲区，不能直接当成已发现的生产算法错误。

本轮独立strict重放固定整数/Map比较、等待Promise、校验异常，并对31,918条可比较向量补齐kwargs_after；**没有找到这些规则掩盖的现有返回值/副作用差异**，找到一条异常类型差异。其余六条消息差别包含fixture长文截断及资源路径适配，未升级为生产缺陷。原adapter仍有输入重建与mutation关闭，因此收紧重放也只对其实际比较域成立。

138个Python模块中29个没有直接函数向量；458向量跳过、1,178向量adapter关闭mutation。部分模块由阶段/端到端/新增探针补证，但本轮没有声称全量源码逐函数手工审阅或任意合法输入形式证明。具体未覆盖函数、路径逐项保存在覆盖台账。每组pipeline还有13次caller标识未被严格验证，模型请求内容仍有比较。

Python参考实际为仓库CPython3.11；项目允许的3.12+未执行。unified多轮失败、任意tools及更多并发时序、故障组合仍有证据缺口。账号/持久化/记忆/学习和tldraw是原迁移范围排除项，本轮不要求其功能等价。

## 7. 修复与复验顺序

1. 先修两个P1：semantic-ID映射和BrowserAsyncContext预算；增加Python/Node/真实Chromium三端回归，固定winner与各样本请求数。
2. 收紧测试harness并保留旧fixture；先确认整数、Map、异常、kwargs和真实事件序号，再以新增回归证明修复。
3. 对齐数值词法、Pydantic状态及网页schema语义；每项补正反输入，防止把Python拒绝变成TS静默成功。
4. 处理PNG位深/大整数等边界并明确支持域。图标主动修复的旧paper基准需要审阅后建立新版本，不覆盖旧证据。

**本轮核验已完成，发现尚未修复。** 结论是“在已测常规输入域有强一致证据，仍存在明确迁移偏差及覆盖缺口”，不是算法完全无差别保证。
