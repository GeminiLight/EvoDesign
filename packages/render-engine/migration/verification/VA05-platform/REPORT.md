# VA05 网页、模型传输与运行平台核验

网页常规回放与Worker主路径对齐；请求校验新增两类可复现P2偏差。共享模型策略和refiner准备调度另列适配，不把不同模型/配置生成的图当成算法差异。

## 实际结果

- Node24.22.1，新构建浏览器包：62资源、无node builtins，typecheck通过。
- 全量web cassette：27/28，一例paper因主动图标修复出现后续Layout提示词差异。
- 为该例独立运行原始A两个Styling方法与当前B：A成功且全部历史产物无差异，B在Layout调用2与TS出现相同首处分歧。没有重录或覆盖旧fixture。
- 新构建真实Chromium Worker：3/3自有模型用例、1/1共享模型用例，取消验证通过。调用全部本地cassette/mock，无真实模型访问。
- 现有HTTP模型/重试矩阵45项由主智能体全套测试新执行通过；这一矩阵不覆盖任意provider错误格式。
- 新增网页schema差分16组，10组相同，6组原始差异归为两类：3个base_version转换，3个空容器真值。
- BrowserAsyncContext问题已经交叉核实：实际Chromium bundle运行受控自一致性，attempts=[3,2,2]且winner=flowchart，Node/Python各[3,3,3]且architecture。详情在VA02和VA06。
- createOpenAIChatModel通过mock fetch接收带null text的parts后保留原样，补足VA04-D04的transport可达性；未验证某个真实provider会发该payload。

## 对应发现

`findings.json`记录D01严格整数转换、D02空容器真值、P01共享模型策略、P02串行准备和I01旧fixture漂移。共享模型强制model/stream/thinking/token cap，text-only跳过视觉评审是产品模式的实际差异，不应隐藏在“浏览器与后端一致”的表述中。

## 覆盖边界

静态检查浏览器入口/资源安装、web主编排、schema/settings/LLM构造、workflow port、Worker/client/前端请求与结果映射、模型HTTP包装、共享请求allowlist和MemoryFS上下文接口。其余web_runtime helper通过28组网页回放与关键路径源对读覆盖，没有声称每个函数逐行手工审计。持久化、账号、记忆、学习与tldraw按原计划排除。MemoryFS的全量Node等价回放由VA04执行，不等于实现任意文件系统/符号链接行为。

Worker smoke里LLM-call-position是用expected值构造，故不能把它当作浏览器实际事件/调用交错的独立证明；模型总次数、消息和最终结果有比较。Node端web回放才记录真实session.calls数量。默认Worker只测了3个自有模型案例、共享text-only1例，不能外推到任意采样数或模型协议。
