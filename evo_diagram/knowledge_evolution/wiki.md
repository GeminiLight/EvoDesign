# 知识演化模块 (DiagramKnowledgeEvolver)

## 概述

**DiagramKnowledgeEvolver** 从数据集中自动发现、优化并编码图表知识。

核心机制：对每个样本跑「生成→验证→精炼」迭代循环，用 Δscore（精炼前后质量差）衡量每轮改进，迭代结束后从历史反馈中提取策略；Phase 1 只把策略蒸馏为准则，原则统一在维护阶段由跨图表类型晋升产生。

三层知识体系，从具体到抽象。只有正向策略进入 active memory；中性策略和反模式仅作为审计记录保留。

| 层级 | 来源 | 粒度 |
|------|------|------|
| 策略 (strategy) | 单样本迭代产出 | 单域单图表类型 |
| 准则 (guideline) | 跨域策略归纳 | 跨域 |
| 原则 (principle) | 跨图表类型准则归纳 | 跨图表类型 |

**极性 (polarity)**: strategy 级 KnowledgeEntry 有 `polarity` 字段：
- `positive` — 推荐做（Δscore > 0.5 的成功策略，以及由此蒸馏出的准则）
- `neutral` — 变化不显著，只写入 `neutral_strategy.json` 审计文件
- `negative` — 避免做（Δscore < -0.5 的失败策略，即 anti-pattern），只写入 `anti_pattern.json` 审计文件，不参与检索、蒸馏、合并或晋升

## 架构

一个编排器 + 三个能力目录：

```
                    engine.py (编排器)
                   ┌────────────────────────────┐
                   │  1. 检索已有知识            │──→ design_memory (ChromaDB)
                   │  2. 迭代精炼每个样本        │──→ iteration/
                   │  3. 增量蒸馏准则            │──→ distillation/ (promoters)
                   │  4. 周期性/末尾维护         │──→ maintenance/
                   │  5. 持久化到向量数据库       │──→ design_memory (ChromaDB)
                   └────────────────────────────┘
                                    │
                              distillation/
                           (LLM 代理，被调用)
```

**谁调用谁**:

| 调用方 | 调用的 distillation 代理 |
|--------|------------------------|
| iteration (RefineLoop) | curators: StrategyExtractorAgent (从迭代历史提取策略) |
| evolution_engine | promoters: GuidelineExtractorAgent (提取准则) |
| maintenance (MaintenanceCycle) | promoters: PrinciplePromoterAgent (晋升)；judges: DemotionJudgerAgent (降级)、MergeJudgerAgent (去重) |

## 目录结构

```
knowledge_evolution/
├── __main__.py              # CLI 入口
├── config.py                # 阈值、路径、角色配置
├── schemas.py               # KnowledgeEntry, DatasetItem 等数据模型
├── engine.py                # 主编排器
│
├── iteration/               # 能力1: 单样本迭代精炼
│   └── loop.py              # RefineLoop — 迭代循环 (含 objective score 计算)
│
├── distillation/            # 能力2: LLM 蒸馏代理
│   ├── curators.py          # StrategyExtractorAgent (从迭代历史提取策略)
│   ├── promoters.py          # GuidelineExtractorAgent + PrinciplePromoterAgent
│   └── judges.py            # DemotionJudgerAgent + MergeJudgerAgent
│
└── maintenance/             # 能力3: 全局知识质量维护
    ├── cycle.py             # MaintenanceCycle — run_full 编排器
    ├── promoters.py         # 晋升 + 降级逻辑
    └── mergers.py           # 聚类 + 合并逻辑
```

## 编排流程

`evolution_engine.run(dataset)` 分三个阶段：

### Phase 1: 迭代阶段

对数据集中每个样本依次执行：

```
for each sample in dataset:

  ① 检索已有知识
     query = sample.query + sample.content[:300]
     retrieved = design_memory.retrieve(query)
     → 从 3 个向量层 (strategy/guideline/principle) 检索相关历史知识
       (只检索 active positive knowledge；neutral/negative 不进入向量库)
     → 返回格式化文本 (retrieved_knowledge) + 命中条目 ID 列表 (retrieved_items)

  ② 迭代精炼 (iteration/loop.py — RefineLoop)
     strategies, history = RefineLoop.run_loop(sample, retrieved_knowledge)
     → 内部循环 max_iterations 轮，每轮:
       generate (Text2DiagramWorkflow, 带入 retrieved_knowledge 作为设计参考)
       → before_findings = 完整问题列表 (category, severity, message, element_id)
       → 精炼 (IterativeRefinerWorkflow: 确定性编辑 + LLM 编辑)
       → after_findings = 精炼后完整问题列表
       → Δscore = score(after) - score(before)
       → 记录 rich feedback:
         - findings_before: 具体问题 (如 "collision/major: Node A overlaps Node B")
         - findings_after: 精炼后剩余问题
         - edits: 应用的修复 + rationale (如 "move node right to avoid overlap")
         - resolved_categories / remaining_categories: 哪类问题被解决了
     → 迭代结束后: StrategyExtractorAgent 从 rich feedback 提取策略
     → 产出: strategies (每条带 avg_delta_score) + history (每轮记录)

  ③ 质量门控 (polarity 分流)
     Δscore > 0.5 → polarity="positive", 存入 all_strategies
     Δscore < -0.5 → polarity="negative", 存入 anti_patterns 审计列表
     -0.5 ~ 0.5 → polarity="neutral", 存入 neutral_strategies 审计列表

  ④ 更新使用统计
     对 ① 检索命中但本次未产生改进的条目，记录 failed_usage
     对产生改进的条目，success_count += 1

  ⑤ 增量蒸馏准则
     guideline_ops = GuidelineExtractorAgent(qualified, existing_guidelines)
     → 将新合格策略与已有准则对比，输出 ADD/UPDATE 操作
     → engine 执行操作，更新 current_guidelines
     原则生成集中在 Phase 2 维护阶段，由 PrinciplePromoterAgent 基于跨图类型证据晋升
```

### Phase 2: 维护阶段

全部样本处理完后，执行一次完整维护（`MaintenanceCycle.run_full`）：

```
1. Score  — 刷新 confidence (用 usage/success/Δscore 重新计算)
2. Prune  — 剪枝低效策略 (usage ≥ 3 且 success_rate < 20%)
3. Merge  — 同层语义去重 (标题 Jaccard 聚类 → LLM 裁判合并)
           ← 在晋升之前合并，合并后 support_count/domain 覆盖提升，增加晋升概率
4. Promote — 策略 → 准则 (跨 ≥3 域, success_rate ≥ 60%, 启发式)
           — 准则 → 原则 (跨 ≥2 种图表类型, LLM 裁判)
5. Demote  — 低表现准则/原则降级 (LLM 裁判，跳过本轮刚晋升的条目)
```

### Phase 3: 持久化

```
JSON 文件:
  samples.json    — 迭代历史 (仅存档，不入向量库)
  strategy.json   — active positive strategies
  neutral_strategy.json — 中性策略审计记录，不入向量库
  anti_pattern.json — 反模式审计记录，不入向量库
  guideline.json  — 准则
  principle.json  — 原则

向量数据库 (ChromaDB design_memory):
  3 个 collection: strategy, guideline, principle
  → 下次运行时 ① 只检索 active positive knowledge
```

## 核心数据流

一个样本从输入到最终影响知识库的完整路径：

```
DatasetItem (文本 + 查询)
  │
  ▼ iteration/loop.py
RefineLoop.run_loop()
  │ 生成 → 验证 → 精炼 × N 轮
  │ 每轮记录 rich feedback:
  │   - findings_before/after (具体问题 + element_id)
  │   - edits (操作 + rationale)
  │   - Δscore
  │ 迭代结束后: StrategyExtractorAgent 从 rich feedback 提取策略
  ▼
List[KnowledgeEntry] (strategies, 每条带 Δscore)
  │
  ▼ evolution_engine._filter_strategies()
  │ Δscore >= 0.5 → polarity="positive"
  │ Δscore <= -0.5 → polarity="negative" (anti-pattern)
  │ -0.5 < Δscore < 0.5 → polarity="neutral" (audit only)
  │ positive → all_strategies
  │ neutral/negative → neutral_strategy.json / anti_pattern.json
  │
  └─ positive strategies (deferred to phase boundary) → GuidelineExtractorAgent → guideline_ops
      → 执行操作 → 更新 current_guidelines

Phase 2:
  active positive strategies + guidelines + principles
    → MaintenanceCycle.run_full()
    → 剪枝 / 合并 / 策略晋升准则 / 准则晋升原则 / 降级

Phase 3:
  active positive KnowledgeEntry → JSON + ChromaDB
  neutral/negative strategy → audit JSON only
```

## 核心数据模型

**KnowledgeEntry** (schemas.py) — 贯穿全链路的知识单元：

| 字段 | 类型 | 含义 |
|------|------|------|
| `id` | str | 唯一标识，如 `flow_023_struc-00001` |
| `tags` | TagSet | 域 (domain)、图表类型 (diagram_type)、代理 (agent) |
| `tier` | str | 层级: `strategy` / `guideline` / `principle` |
| `polarity` | str | 极性: `positive` (推荐做) / `neutral` (审计) / `negative` (反模式审计) |
| `delta_score` | float | 质量增量 (精炼前后分数差) |
| `confidence` | float | 聚合置信度 (维护周期刷新) |
| `usage_count` | int | 被检索到的次数 |
| `success_count` | int | 被检索到且样本成功改进的次数 |
| `generalization_status` | str | `local` → `validated` → `promoted` / `demoted` / `merged` / `pruned` / `retired` |
| `active` | bool | 是否进入 active-positive 检索；归档条目为 `false` |

## 依赖

### Python 包

- `chromadb` — 向量数据库
- `sentence-transformers` — 嵌入模型
- `transformers` — sentence-transformers 依赖

### 内部模块

| 模块 | 路径 |
|------|------|
| LLM 工厂 | `core.llm_factory.LLMFactory` |
| 设计记忆 | `design_memory.DiagramDesignMemory` / `DiagramDesignRetriever` |
| 文本转图表工作流 | `agentic_system.workflow.Text2DiagramWorkflow` |
| 迭代精炼工作流 | `agentic_system.iterative_workflow.IterativeRefinerWorkflow` |
| 验证检查 | `agentic_system.verification_stage.checks.aggregator.run_all_checks` |
| PNG 渲染 | `canvas_environment.render_png_result` |
| 通用文件 I/O | `utils.io_utils` |

## 使用方式

```bash
# 在 repo root 目录下运行

# 推荐: 使用 models.yaml
python -m evo_diagram.knowledge_evolution --model-config configs/models.yaml --dataset dataset/test/data.json

# 指定不同模型角色
python -m evo_diagram.knowledge_evolution --model-config configs/models.yaml \
  --generation-role generator \
  --distillation-role distiller \
  --judge-role distiller \
  --dataset dataset/test/data.json

# 控制迭代次数
python -m evo_diagram.knowledge_evolution --model-config configs/models.yaml --max-iters 5 --dataset dataset/test/data.json

# 离线设计记忆模式: 不加载 ChromaDB/embedding，不做 DB seed、检索、持久化和 embedding merge
python -m evo_diagram.knowledge_evolution --design-memory-mode offline --dataset dataset/test/data.json

# 兼容模式: 使用 LLM_* 环境变量
python -m evo_diagram.knowledge_evolution --dataset dataset/test/data.json
```
