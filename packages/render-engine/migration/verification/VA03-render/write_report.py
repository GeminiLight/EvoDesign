import json
from pathlib import Path
OUT=Path(__file__).resolve().parent
findings=[
 {'id':'VA03-D01','classification':'D','severity':'P1','title':'合法 __proto__ 语义节点在 TS 渲染分类时被丢弃','python_location':'evodesign/agentic_system/render_engine/excalidraw/converter.py:657-668','ts_location':'packages/render-engine/src/render_engine/excalidraw/converter.ts:690-700,719','trigger':'quickstart-service 的首个节点和所有引用替换为 __proto__。Python/TS 的 validate_structure_instantiation 均接受，Python 9 阶段无异常。','before':'Python excalidraw_convert 生成20个元素，保留该节点与标签。','after':'TS excalidraw_convert 生成18个元素；从该阶段开始首个差异。','cause':'regular_elements 是普通 {}，赋值 regular_elements["__proto__"]=element_data 修改原型，不形成可枚举自有键；Object.entries 随后省略此节点。','controls':['n_control','constructor','toString'],'reproduction':'cd packages/render-engine; PYTHONPATH=../.. ../../.venv/bin/python migration/verification/VA03-render/gen_mutants.py; node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/compare_mutants.mts','evidence':['mutants-python.json','mutants-comparison.json','check_schema.mts'],'impact':'有效节点及其标签丢失，随后关系/布局可能继续偏移。触发需使用特殊ID，常见描述性ID未受影响。','suggestion':'后续修复应将语义ID索引映射改为无原型对象或Map，并审查全流水线其它按ID赋值位置；若选择拒绝特殊ID，必须两端同步并记录为主动行为改变。'},
 {'id':'VA03-D02','classification':'D','severity':'P2','title':'smart_crop 将低位深 PNG 的 packed 字节当成逐像素采样值','python_location':'evodesign/agentic_system/render_engine/shared/image_cropper.py:51-52','ts_location':'packages/render-engine/src/render_engine/shared/image_cropper.ts:65-84','trigger':'100×80 黑白1-bit PNG，黑色矩形和单像素横线，padding=0，canvas_engine=excalidraw。','before':'Python/OpenCV 裁剪78×56，RGB SHA-256 efe17a8561f2e812413fc91cd8e9f12199ff999931c9d8376e39c1468790e705。','after':'TS 裁剪100×11，RGB SHA-256 4fb01fe65f50ab63d7b43a85296e1d09abd5ff2941bd91ad40bd976e0143c209。','cause':'fast-png 对低位深PNG返回packed样本；当前 _imread 按 src[p * channels] 逐像素读取，未根据bit depth和每行padding解包。','reproduction':'cd packages/render-engine; PYTHONPATH=../.. ../../.venv/bin/python migration/verification/VA03-render/gen_crop_cases.py; node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/compare_crop.mts','evidence':['crop-python.json','crop-comparison.json','crop-cases/onebit.png','crop-cases/onebit.py.png','crop-cases/onebit.ts.png'],'impact':'通用裁剪函数的合法低位深PNG输入错误；当前 Excalidraw 导出8-bit RGBA，常规网页出图未发现该触发条件。','suggestion':'后续修复先正确解包depth<8样本/调色板索引，再做BGR转换；将低位深PNG纳入独立回归。'},
 {'id':'VA03-D03','classification':'D','severity':'P2','title':'2^53 整数的 Python JSON/字符串格式仍不等价','python_location':'Python 3.11 json.dumps(2**53)','ts_location':'packages/render-engine/src/py/json.ts:92-94; src/py/str.ts:numberStr','trigger':'值为9007199254740992的Python int，经过pyJsonDumps或numberStr。','before':'9007199254740992','after':'9007199254740992.0','reproduction':'cd packages/render-engine; PYTHONPATH=../.. ../../.venv/bin/python migration/wp11/gen_json.py migration/verification/VA03-render/numeric-vectors.json; node node_modules/tsx/dist/cli.mjs migration/wp11/run_json.mts migration/verification/VA03-render/numeric-vectors.json','evidence':['numeric-vectors.json','numeric-comparison.log'],'impact':'跨语言大整数序列化与潜在hash输入不同；未在常规布局/seed输入中复现用户可见变化。该问题是旧WP11已记载且本轮重新复现的边界限制。','suggestion':'限定安全整数域或保留整数字面量/BigInt，明确JSON类型策略。'},
 {'id':'VA03-D04','classification':'D','severity':'P3','title':'可见性网格通过 Set 规范化了负零','python_location':'evodesign/agentic_system/render_engine/excalidraw/arrow_routing/grid_router.py:_find_orthogonal_visibility_route','ts_location':'packages/render-engine/src/render_engine/excalidraw/arrow_routing/grid_router.ts:227-228','trigger':'起点含-0.0且轴坐标集合合并正负零。400组样本中26组带符号零表示不同。','before':'示例路线 [[-0.0,60],[-0.0,120]]','after':'示例路线 [[-0,60],[0,120]]','reproduction':'cd packages/render-engine; node node_modules/tsx/dist/cli.mjs migration/wp11/run_grid_signed_zero.mts migration/verification/VA03-render/grid-vectors.json','evidence':['grid-vectors.json','grid-comparison.log','grid-signed-zero.log'],'impact':'坐标数值和路线几何相同，本轮未观察可见图形变化；严格序列化并非逐位相同。旧WP11记录过，本轮独立重生成样本复现。','suggestion':'在等价定义中明确signed zero边界；若要求序列化相同，需保留原始零符号。'},
 {'id':'VA03-U01','classification':'U','severity':'P2','title':'Python 3.12+ 的数值语义未被当前 3.11 证据覆盖','python_location':'pyproject.toml:requires-python >=3.11','ts_location':'packages/render-engine/src/py/number.ts:191-195; src/py/math.ts:vectorNorm','trigger':'Python部署升级到3.12+，浮点sum等行为可能与绑定3.11的TS helper不同。','evidence':['coverage.json','numeric-comparison.log'],'impact':'本轮实际对照使用仓库.venv CPython3.11，不能外推为所有requires-python允许版本均等价。','suggestion':'在单一实现前固定Python参考版本，或增加所支持版本差分CI。','reproduction_status':'静态支持范围缺口；本轮没有安装/运行额外Python版本，不声称在3.12部署上实测到图形偏差。'}
]
(OUT/'findings.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2)+'\n')
report='''# VA03：确定性布局、连线路由与渲染算法核验

结论：现有常规样例与高风险计算分支具有强等价证据，但不能声称迁移前后所有合法输入上的算法完全相同。本轮发现并复现 **1 项 P1 与 1 项 P2 新偏差**，另复现 2 项旧数值表示限制，保留 1 项版本覆盖缺口。没有修改产品源码或旧 fixtures。

## 1. 基线与范围

- A=`1ac838f` 原始 Python，B=当前 Python。模块映射范围内的 **46/46** Python 源文件与 A 内容逐字相同，因而本包内 Python 参考未因最近图标修复发生漂移。
- 范围：WP01–10 的42个映射模块，加WP14 canvas_render/service/image_cropper/png_validation四个模块；额外检查9个数值/字典/字符串运行时helper与前端pipelineRenderer。
- `coverage.json` 登记46模块的文件、17,102条录制向量、362个有向量函数、零向量/未记录函数，以及本轮明确逐段抽查的12个关键模块。17,102是现存fixture数量，并非由本报告另跑一次全量函数向量得到的通过数；主智能体负责全量函数对照。
- 其余模块通过模块映射、A/B源差分、已有函数证据及阶段回放核验。本轮不声称逐函数完整人工审阅46模块全部源码，未有运行证据的分支仍列作缺口。

## 2. 本轮实际运行结果

| 检查 | 新鲜结果 | 证据 |
|---|---|---|
| 阶段串联 | 112/112个样例一致 | stages.log、stages.json |
| 阶段隔离 | 1008/1008个阶段一致 | stages.json |
| 阶段数值严格检查 | 112/112，容差命中0、key顺序差异0、最大数值差0 | stage-tolerance.json |
| 网格路由独立随机样本 | 400/400几何路线与memo key一致；26个signed-zero表示差 | grid-vectors.json、grid-comparison.log |
| Python half-even round边界 | 315/315一致 | numeric-comparison.log |
| str/repr边界 | 25/25一致 | numeric-comparison.log |
| JSON dumps边界 | 184/188一致，4个失败均为同一个2^53 int的不同选项 | numeric-comparison.log |
| 全部内置图标 × 3种颜色/无效颜色 | 133图标、399/399，完整SVG dataURL及file ID逐字一致 | icons-comparison.json |
| Browser vs service新抽样 | quickstart-service × product/analysis，2/2原图字节与像素完全一致，crop结果也一致 | renderer-sample/summary.json |
| 合成crop PNG边界 | 7/8消息、尺寸、RGB SHA相同；1-bit PNG失败 | crop-comparison.json |
| 特殊ID变形 | n_control、constructor、toString三对照9阶段一致；__proto__首个差异在convert | mutants-comparison.json |

历史`reports/wp28/summary.json`保存了112×2=224组服务端/浏览器全像素一致证据，本轮只重新运行1个case的两种mode，未将历史224组表述为本轮重跑。新抽样脚本输出位于VA03目录，未覆盖历史报告。

## 3. 新发现

### VA03-D01 · D / P1：合法 __proto__ 节点在TS中丢失

将quickstart-service首个节点及引用重命名为`__proto__`。两端结构schema均接受，Python运行全部9阶段成功。`excalidraw_convert` Python有20个元素，TS只有18个，丢掉节点及其标签。

`converter.py:657–668`的Python字典分桶在TS `converter.ts:690–700`被翻译成普通`{}`。`regular_elements[element_id]=element_data`碰到`__proto__`会设置原型而不是插入自身键，后续719行`Object.entries`便不再处理该节点。控制ID `n_control`、`constructor`、`toString`没有此问题。

触发需要特殊节点ID；标准描述性ID的112个样例均一致。但它是当前schema允许的有效输入，节点丢失属于语义差异。后续建议改为无原型对象/Map，并检查全流程其它同类映射；若改成拒绝ID，需要同步两端且登记行为变化。

### VA03-D02 · D / P2：1-bit PNG裁剪算法读取了错误像素

同一100×80的黑白PNG（黑色矩形和一像素横线），Python/OpenCV得到78×56，TS得到100×11。`image_cropper.ts:65–84`假定fast-png的`data`是逐像素数组，而低位深PNG返回的是packed字节，缺少按位和行stride解包。

当前Excalidraw导出8-bit RGBA，此问题不是普通网页出图的已证实故障；它是通用crop函数对合法低位深PNG的实际迁移偏差。RGB、淡线、RGBA透明度、暗背景、8-bit灰度、8-bit调色板和负padding对照均与Python一致。

## 4. 旧限制重新复现与证据边界

- **VA03-D03，P2**：Python int `2**53`序列化为`9007199254740992`，TS写成`9007199254740992.0`。当前常规hash/seed未观察到这么大的整数字面量，故未声称已有可见图形影响。round等一般数值分支均通过。
- **VA03-D04，P3**：JS Set将`-0`规整为`+0`；400个网格输入中26组路线只有符号零不同。几何与memo key均相同。默认比较器忽略这个区别，因此“完全相同”需附带数值表示边界。
- **VA03-U01，P2**：TS `pySum`绑定CPython3.11左到右求和，项目允许>=3.11。当前参考venv是3.11，3.12+未执行；本轮不把未来版本行为算作已复现部署故障。
- 旧WP11的纯数字ID问题已经在本轮基线前通过两端拒绝整数式ID处理，不能把旧报告当作当前问题。新增`__proto__`问题是另一类普通对象键语义，不受整数ID门禁保护。
- tldraw路径按原迁移计划排除；非PNG输入也不是浏览器渲染链的输入域。无向量的image_cropper通过本轮独立合成图补证，但未覆盖任意PNG编码/位深组合。完整分支/函数覆盖见coverage.json。

## 5. 复现

在仓库`packages/render-engine`目录，Node使用项目要求的>=22.12运行时（本轮用bundled Node24.22.1）：

```sh
export PATH=/Users/zhanyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
npm run parity:stages
PYTHONPATH=../.. ../../.venv/bin/python migration/verification/VA03-render/gen_mutants.py
node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/compare_mutants.mts
node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/check_schema.mts
PYTHONPATH=../.. ../../.venv/bin/python migration/verification/VA03-render/gen_crop_cases.py
node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/compare_crop.mts
PYTHONPATH=../.. ../../.venv/bin/python migration/verification/VA03-render/gen_icon_cases.py
node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/compare_icons.mts
node node_modules/tsx/dist/cli.mjs migration/verification/VA03-render/renderer-sample.ts --case quickstart-service --concurrency 1
```

网格与数值重新生成及对照的命令见findings.json。所有新报告、输入、脚本、图片只写入VA03目录。3001只读使用，未改动3000、未调用真实模型、未提交或部署。
'''
(OUT/'REPORT.md').write_text(report)
print('Saved REPORT.md, findings.json')
