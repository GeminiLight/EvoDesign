# VA01 基线与对照可信度

A为Git 1ac838f原始Python/后端，B为本轮开始时Python，C为当前Node TS，D为浏览器包。A→B只修改StylingAgent及其Python测试；生产变化是图标兼容及名称校验修复，详见VA02。

基线清单冻结950个路径，事后确认其中263个是本地Next渲染服务的生成缓存；正式源码/资源687个。结束时687个源码/资源哈希均未改变；2个Next生成缓存变化单列drift-classified.json，不属于生产算法变更。139模块映射包括138个Python模块和1个TS语义运行时目录。

## 本轮基础测试

Node24全量Vitest：7个文件、1,199项通过。其中函数测试877项=739函数组+138模块报告项，不等于877条向量。现有34,962条向量：34,504按旧规则通过，458显式skip，0旧规则失败。109/138模块有函数向量，29无直接函数向量；它们中的一部分由阶段、cassette或本轮边界补证，具体见各包coverage。

skip共21函数组，主要为异步模型/渲染/CLI、tldraw、记忆加载。1,178条向量适配器关闭mutation比较；有些合理地重建状态/浮点表示，需逐项理解，不能把它们当作完整副作用验证。覆盖清单不等于分支覆盖率，也不将未记录函数自动计为等价。

## 独立比较器检查

- compare.ts:40实际先接受relative error<=1e-9，不受声明的绝对1e-6上限约束，也不计tolerated。2000000000与2000000001会零差异通过，恰好落入Excalidraw seed/nonce实际量级。现有fixture中72,184个数值节点可构造出超过1e-6却仍被放行的扰动；这是盲区规模，不是发现72,184个现存差异。
- Map分支找不到同名key时退回同一位置，只比较value；Map(expected_key→1)与Map(wrong_key→1)被判相同。57个向量包含119个Map节点，因此不是完全无关的数据类型。
- 预期空对象与Promise对象会因无枚举键被判相同；同步runner原本不await。已标记异步函数大多skip，故本轮没有证明该盲区已掩盖实际生产返回值差异。
- 106个预期异常向量只检查“任意throw”，不验证类型/消息；kwargs_after未在原runner中重建比较；无模块选择会出现1项通过。
- Browser smoke把事件的llm_calls填入expected值，无法独立证明事件与模型的实际交错位置。Node web harness对session.calls有实测。

独立strict_replay.ts保持旧fixture/adapter只读，另用Map键必需、精确整数、绝对浮点阈值、Promise等待及异常类型/消息检查重放。最终统计见strict-replay.json；它仍继承adapter的输入转换与skip/disabled-mutation限制，不属于对所有分支的形式化证明。异常文字中的300字符截断、临时路径与资源provider替换不能自动认定为生产差异。

最终独立重放：34,497条完全匹配（含匹配的异常契约），458跳过，7条异常消息差异；其中1条TypeError→ValueError为实际异常类型偏差。其余6条涉及被录制器截断的长消息、临时路径或provider路径，不列为新生产错误。返回值/副作用新差异0；31,918条无输入adapter且允许mutation比较的向量额外重建kwargs_after后也一致。原适配器关闭mutation或重建输入的部分仍保留限制。
