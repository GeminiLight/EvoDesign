# Design Memory 系统问题与风险分析

**日期**: 2026-05-05

## 架构风险

### 1. Embedding 模型强依赖

初始化时下载 HuggingFace 模型 (Qwen3-Embedding-0.6B)，网络不通则整个系统不可用。`--design-memory-mode offline` 会关闭设计记忆库初始化、DB seed、检索、持久化和 embedding merge，因此知识积累会被中断。

**影响**: 离线环境、hf-mirror.com 不稳定时无法使用。

**建议**: 支持本地预下载模型路径，或 fallback 到轻量级 embedding。

### 2. Embedding 模型与向量不匹配 (高风险) ✅ 已修复

换 embedding 模型后，已有 ChromaDB 向量与新模型不兼容，但无检测机制。查询静默返回垃圾结果，不会报错。

**影响**: 知识检索质量退化，难以排查。

**修复**: `_check_embedding_model_consistency()` 在初始化时将当前 embedding 模型名写入每个 collection 的 metadata。后续启动时比对，不匹配则输出 WARNING 日志。首次运行或 legacy 数据自动 stamp 当前模型。

### 3. 无版本控制 ✅ 已修复

知识条目用 ID 覆盖式写入。策略更新后旧版本丢失，无法回滚或追踪历史。

**影响**: 错误的知识更新无法撤销。

**修复**: `_next_version_id()` 在写入前检查 ID 是否已存在。若存在则追加 `_v2`、`_v3` 等后缀，旧版本保留在 DB 中。`add_design_item` 和 `save_design_memory` 均使用此逻辑，并把最终 ID 同步写回 `metadata.id`、`original_json_data.id` 和 document payload，避免跨 run 读回旧 ID。

## 检索风险

### 4. SequenceMatcher 做 reranking 太弱 ✅ 已修复

`_rerank_candidates` 用 `difflib.SequenceMatcher` 做文本相似度，纯字符串匹配，不理解语义。"node overlap" 和 "shape collision" 匹配度很低。

**影响**: 相关知识可能被遗漏。

**修复**: 用 embedding 余弦相似度替代 SequenceMatcher。`_rerank_candidates` 现在预计算 query 和所有候选的 embedding 向量，用 `_cosine_similarity()` 做 relevance boost 和 diversity penalty。同时修复了 `final_top_k` 未定义的 bug。

### 5. 硬编码权重 ✅ 已修复

`_utility_weight=0.25`, `_diversity_weight=0.20`, `_exploration_weight=0.10` 写死在代码里。

**修复**: 权重移至 `configs/settings.yaml` 的 `retriever` 节，`AppSettings` 新增 `retriever_utility_weight`、`retriever_diversity_weight`、`retriever_exploration_weight` 属性。`DiagramDesignRetriever.__init__` 从配置读取。

### 6. 检索窗口截断 ✅ 已修复

`search_query = f"{user_query}: {text_content[:300]}"`，只取前 300 字符。长文本的关键信息可能被截断。

**修复**: 三层改进 — (1) Router 现在输出 `retrieval_query`（15-25 词的设计术语描述），用于替代 raw text 截断；(2) 无 Router 时用 `"{diagram_type} diagram: {user_query}"` 替代截断；(3) 检索改为逐 layer 查询，支持 `diagram_type` metadata filter（匹配 `strategy_diagram_type_flowchart` 等扁平化 key），缩小搜索空间。

## 存储风险

### 7. Metadata 扁平化丢失信息

`_prepare_metadata_for_chromadb` 把列表展开成布尔标记：
```python
# 原始: {"domain": ["finance", "banking"]}
# 存储: {"guideline_domain_finance": True, "guideline_domain_banking": True}
```
原始结构丢失，无法做精确过滤。

**建议**: 保留原始 JSON 字符串在 metadata 中（已有 `original_json_data`），过滤时优先用它。

### 8. 无去重

不同样本产生相似策略时，重复写入 vector DB。同一条知识可能有多个副本。

**建议**: 写入前用相似度检查，阈值以上则合并而非新增。

### 9. 无备份/恢复

ChromaDB 数据目录损坏则全丢，无导出/导入机制。

**建议**: `_persist_results` 同时写一份 JSON 快照到 results 目录（已有，但需确认完整性）。

### 10. 线程安全 ✅ 已修复

`DiagramDesignMemory` 无锁保护。多进程同时写入同一 ChromaDB 目录可能损坏数据。

**影响**: 并行运行 KE pipeline 时有风险。

**修复**: 添加 `threading.Lock`，所有写操作（`add_design_item`、`save_design_memory`、`delete_design_item`）在 `with self._lock:` 块内执行。注意：多进程场景仍需外部文件锁，threading.Lock 仅保护同进程内的多线程。

---

## 第二轮审视 — Knowledge Evolution 全模块

**日期**: 2026-05-05
**范围**: `engine.py`, `iteration/loop.py`, `maintenance/{cycle,mergers,promoters}.py`, `distillation/{curators,judges,promoters}.py`, `design_memory/`

### 🔴 严重 (HIGH)

#### 11. RefineLoop 多次迭代实际上是空跑 [BUG] ✅ 已修复

`iteration/loop.py:123-179` 中,`state = self.generator.run(...)` 在 for 循环**外**只调用一次,生成 baseline manifest。
循环内每次读 `diagram_manifest = state.diagram_manifest`(同一份),refiner 输出的 `refined_manifest` 被赋给局部变量但**从未写回 `state.diagram_manifest`**。
结果:第二次及以后的 iteration 用的还是 baseline manifest,refiner 在重复"修同一份图",delta_score 也都是相对 baseline 计算的。

**影响**:
- `config.max_iterations > 1` 等价于 `max_iterations = 1`,多余迭代纯粹浪费 LLM 调用。
- 知识演化看到的"refinement trajectory"实际只有一步,不是真实多步轨迹。

**修复**:`diagram_manifest` 提到循环外初始化,循环末尾把 `refined_manifest` 赋给 `diagram_manifest`,
作为下一轮迭代的输入。后续 refiner 调用真正在前一轮的 refined manifest 基础上继续精炼。

---

#### 12. `_RunState` 不从 DB 加载,多次 run 不可累积 ✅ 已修复

`engine.py:105` 中 `state = _RunState()` 永远是空的。`_persist_results` 把所有 strategy/guideline/principle 写入 ChromaDB 后,
**下次 run 启动时不会读回来**。每次 run 是从零开始 distill,然后追加写入向量库。

**影响**:
- 跨 run 不能复用上次提取的 guideline/principle,LLM distillation 工作重复。
- 配合 #13(版本化保存),DB 体积每次 run 翻倍而不是收敛。

**修复**:
- `DiagramDesignMemory.load_all_items(layer)` 新方法:从 ChromaDB 读出整个 layer 的所有条目(优先用 `original_json_data` round-trip 完整 KnowledgeEntry,失败 fallback 到 document body)。
- `engine._seed_state_from_db(state)`:在 `run()` 入口处调用,把 strategy/guideline/principle 都装入 `state`。
- `_RunState` 新增 `loaded_ids: Dict[str, Set[str]]` 字段,记录哪些 ID 来自 DB —— 配合 #13 的修复用于区分 update vs new。

---

#### 13. 版本化保存放大 DB 体积,每次 run 翻倍 ✅ 已修复

`_next_version_id` 修复了"覆盖丢历史"的问题,但 `_persist_results:218-232` 用 `save_design_memory` 全量推送
**所有** strategy/guideline/principle。配合 #12,每 run 都把同样内容以 `_v2`、`_v3` 的形式重新插入。

**影响**: ChromaDB 体积线性增长且充斥近似重复条目,检索质量退化。

**修复**:
- `DiagramDesignMemory.update_design_items(items, layer)` 新方法:对已有 ID **不**追加版本后缀,使用 vector store 的安全 `update_documents` 原地替换。若当前 vector store 不支持安全 update,直接 fail-fast,不再走 delete-then-add fallback。
- `DiagramDesignMemory.archive_design_items(ids, layer)` 新方法:把维护流程移出的条目标为 `active=false` 和 `generalization_status=retired`,保留审计痕迹,不再物理删除。
- `engine._sync_layer_to_db(layer, entries, loaded_ids)` 三路同步:已加载 ID 走 update、新 ID 走 save_design_memory(保留 versioning 能力)、消失 ID 走 archive。
- 这样:重跑相同数据集 → DB 不再翻倍;真正修改的条目原地更新;真正新增的才创建 _v2;prune 出去的会退出 active-positive 检索,但历史仍可追溯。

---

#### 14. `confidence` 单位不一致 ✅ 已修复

- `maintenance/cycle.py:compute_confidence`:`0.45·success_rate + 0.35·(delta/10) + 0.20·(support/5)` ∈ [0, 1]
- `iteration/loop.py:238`:`confidence=avg_delta` —— 直接把平均 delta_score(范围 [-10, 10])当 confidence 写入 KnowledgeEntry

**影响**: 同一 KnowledgeEntry 在不同模块的 confidence 字段语义不同,后续筛选/排序基于错误数值。

**修复**:RefineLoop 创建 strategy 时先填好 `delta_score`,然后调用 `compute_confidence(entry)` 计算 confidence。
现在创建期、re-score 期、retriever 端三处都用同一个 [0, 1] 公式,数值可比。

---

#### 15. Promote 的 `success_rate` 检查实际上是 vacuous ✅ 已修复

`maintenance/promoters.py:59`(`promote_strategies`)和 `:122`(`promote_guidelines`)用
`sum(1 for s in srcs if s.delta_score > delta_threshold)` 估算 success 数。

但 `_filter_strategies` 已经只保留 `delta_score >= threshold` 的 strategies,所以**所有 source 都是 success**,
`success_rate` 恒等于 1.0,promotion 门槛 `success_rate >= 0.7` 永远成立。

**影响**:promotion gate 失效,任何达到 `min_support_count` 的 cluster 都会被提升。

**修复**:新增 `_is_promotion_success(item)` 双信号 gate —
- **In-the-wild evidence**: `usage_count >= promote_min_retrieval_usage` 且 `success_count/usage_count >= promote_per_strategy_success_rate`(基于真实检索数据,需要 #12 的 DB 加载支撑)。
- **Creation-time evidence**: `delta_score >= promote_strong_delta_score`(默认 1.0,即 2× delta_score_threshold 默认值,显著高于过滤阈值)—— 应对新创建 strategy 还没有 retrieval 数据的情况。

`promote_strategies` 和 `promote_guidelines` 都改用这个 gate。三个新参数(`promote_strong_delta_score`、`promote_min_retrieval_usage`、`promote_per_strategy_success_rate`)写入 `KnowledgeEvolutionConfig`,可调。

---

### 🟡 中等 (MEDIUM)

#### 16. 每个 sample 都跑全套 distillation —— O(N) LLM 成本 ✅ 已修复

`engine.py:_run_iteration_phase:155-167` 在每个 sample 循环里都调用
旧实现同时运行 guideline 更新和 Phase 1 principle 合成,每个又会按 (domain, diagram_type, agent) tuple group 后多次调用 LLM。

**影响**:对 2260-item 训练集,distillation 调用次数是 sample 数 × group 数,远高于必要。

**修复**:
- `_run_iteration_phase` 不再每个 sample 调 distillation;改为每个 phase 末尾跑一次 `_run_distillation(state)`(可选 `distillation_every_n_samples` 配置做 mid-phase checkpoint)。
- `_RunState.distilled_strategy_count` 高水位记录已 distill 过的 strategy 索引;重复调用 `_run_distillation` 只处理新增 slice,避免重复工作。
- Phase 1 只负责 strategy → guideline; guideline → principle 统一交给 `MaintenanceCycle.promote_guidelines`,避免两条生产路径同时写 principle。
- end-of-phase 总是跑一次,把 loop 内累积的 strategies 都 drain 掉。

---

#### 17. `delta_score` 在 (-threshold, +threshold) 区间静默丢弃 ✅ 已修复

`engine.py:_filter_strategies:347-352` 只收 `>= +threshold` 和 `<= -threshold`,中间区间(中性结果)的 strategy 被静默丢弃。

**影响**:中性结果(无伤大雅但也没改进的策略)其实是有信息量的,丢弃后 distillation 看不到完整的 success/failure 分布。

**修复**:`_filter_strategies` 现在返回三元组 `(qualified, neutral, anti_patterns)`。中性结果打 `polarity="neutral"` 进 `state.all_strategies` 用于全量记录与统计,但 `_update_guidelines` 跳过 negative 与 neutral,只把正向 signal 提炼成 guideline。`schemas.KnowledgeEntry.polarity` 注释也补上 "neutral" 取值。

---

#### 18. 标签精确等值匹配导致 distillation 找不到 existing ✅ 已修复

`engine.py:_update_guidelines:416-422`:
```python
relevant_existing = [
    g.model_dump()
    for g in existing_guidelines
    if g.tags.domain == list(domains)
    and g.tags.diagram_type == list(dtypes)
    and g.tags.agent == list(agents)
]
```
要求三个 tag 列表**完全相等**。

**影响**:
- 某 strategy tag 是 `["finance", "banking"]`,existing guideline tag 是 `["finance"]` —— 找不到,被当作全新 cluster。
- `_update_guidelines` 看到 `relevant_existing=[]`,LLM 倾向输出 `add` 操作,产生重复 guideline。

**修复**:新增 `DiagramKnowledgeEvolverEngine._tags_compatible(a, b)` —— 任一空当通配,否则要求集合有交集。`_update_guidelines` 走这个 helper,这样 `["finance"]` 既能匹配 `["finance", "banking"]` 也能匹配 `["finance", "tech"]`,distillation 能复用已有 guideline 而不是 spam 出新条目。

---

#### 19. 标题相似度聚类用裸 token Jaccard ✅ 已修复

`maintenance/mergers.py:_jaccard` 直接对 split 后的 token set 算 Jaccard,不去停用词、不 lemmatize。

**影响**:"Use a flowchart" 和 "Choose a flowchart" 共享 a/flowchart,Jaccard 偏高;
"Add icons to nodes" 和 "Annotate nodes with icons" 几乎语义相同,Jaccard 却很低。聚类质量不稳。

**修复**:
- 新增 `mergers._cluster_by_embedding(items, threshold, embed_documents)`:批量 `embed_documents` 一次拿到所有标题向量,然后跑 pairwise cosine + union-find;复用 `DiagramDesignMemory.embedding_function`(Qwen3-Embedding-0.6B),与 retriever 共用同一 embedding 模型保持一致性。
- `MaintenanceCycle.__init__(... embedding_function=None)` 新增可选参数;engine 默认把 `self._memory.embedding_function` 注进去,`--design-memory-mode offline` 时 fallback 到原 Jaccard。
- `MergerMixin._cluster_titles(items)` 内部派单:有 embedder 走 cosine,否则走 Jaccard。
- 配置:`merge_title_embedding_similarity=0.78`(cosine 单位)与原 `merge_title_similarity=0.6`(Jaccard 单位)分开存,各自合理阈值。
- 实测 paraphrase 对("Add icons to nodes" / "Annotate nodes with icons")在 cosine 模式下成功聚类,Jaccard 模式无法做到。

---

#### 20. UUID 随机 ID 无法复现 ✅ 已修复

`engine.py:_apply_memory_operations:502`:`new_id = f"{item_type}_{uuid.uuid4().hex[:8]}"`。

**影响**:
- 相同输入两次 run 产生不同 ID,无法做实验复现。
- 配合 #12(不读 DB)和 #13(全量重写),进一步加剧"同一概念多次写入不同 ID"。

**修复**:
- 新增 `mergers._content_hash(title, tags)`:对 `title`(normalize 后)和 `tags`(每个 list 排序)一起 sha1 取 8 字符,得到稳定 8-hex 摘要。
- `engine.py:_apply_memory_operations` 中 add 操作改用 `f"{item_type}_{_content_hash(title, tags)}"`;ID 与 `_seed_state_from_db` 加载的 ID 撞车时,直接 skip add(保留已加载 entry 的 usage_count/success_count),避免清零统计。
- `mergers._build_merged_entry` 中 `f"{tier}_merged_{uuid.uuid4().hex[:8]}"` 同样改用 `_content_hash`(基于 merged_title + union 后的 tags),merged 条目重跑也稳定。
- 验证 `_content_hash` 性质:tag 排序无关、title 大小写无关、empty tags 与 non-empty 不同 —— 全部通过。

---

#### 21. Embedding 在 `_rerank_candidates` 中重复计算 2 次

`design_memory/diagram_design_retriever.py:128, 137`:`_embed_query(text)` 对同一文本调两次,一次用作 doc embedding,一次塞回 `"emb"` 字段。

**影响**:每候选多消耗一次 embedding 调用,top-k=20 时 reranking 成本翻倍。

**修复**:计算一次后复用变量。

---

#### 22. 未被检索过的 strategy 永远不被 prune

`maintenance/cycle.py:_prune_strategies:162-169` 仅 prune 满足 `usage_count >= min_usage` 且 `success_rate < threshold` 的条目。
**`usage_count == 0`** 的 strategy(从未被检索使用)永远不进 prune 路径。

**影响**:无用 strategy 永久占据 DB,检索时拖慢相似度排序,稀释相关结果。

**建议**:增加"长期未被检索"的 prune 路径,如 `created_at` 距今超过 N 天且 `usage_count == 0` 即清除。

---

#### 23. `failed_usage` 不持久化,crash 即丢

`engine.py:_run_iteration_phase` 在 `state.failed_usage` 中累积失败样本的 retrieved item,
`_run_maintenance_phase` 用它跑 demotion judger。但若 Phase 1 中途崩溃,这些数据**没有写入 DB 也没有 JSON 快照**。

**影响**:长 run 中途失败后,demotion 输入丢失,不重跑就无法 demote。

**建议**:每 N 个 sample checkpoint 一次 `failed_usage` 到 JSON。

---

#### 24. 全 maintenance 仅 Phase 1 末尾跑一次

`engine.py:run` → `_run_maintenance_phase`:Score → Prune → Merge → Promote → Demote 在所有 sample 处理完才跑。

**影响**:
- 若 Phase 1 处理 2000 个 sample,前 1000 个 sample 用的检索结果是"未经 maintenance"的状态,质量较差。
- 若中途崩溃,maintenance 整个跳过,DB 留下大量未经清理的 strategy。

**建议**:周期性 maintenance(每 N 个 sample 跑一次轻量 prune),或至少在 checkpoint 时跑一次。

---

### 🔵 轻度 (LOW)

#### 25. distillation prompt 的 `{{` 转义风格不匹配

`distillation/promoters.py` 中 `GuidelineExtractor` prompt 含 `{{` 转义,意在配合 `.format()`。
但项目约定用 `.replace()` 替代 `{{placeholder}}` —— 这里的双花括号不会被处理,LLM 看到字面 `{{`。

**影响**:LLM 偶尔被混淆,模仿 `{{` 输出格式不一致的 JSON。

**建议**:统一用 `{{placeholder}}` + `.replace()`,移除残留的 `.format()`-style 转义。

---

#### 26. StrategyExtractor 输出 key 无 schema 校验

`iteration/loop.py:225`:`for key, value in summary.items():` 直接把 LLM 输出的 dict key(`"parse"`、`"styling"`...)作为 strategy 的 `agent` tag。

**影响**:LLM 偶尔输出 typo(如 `"styling-tips"`)就会污染 tag 体系。

**建议**:用 enum 校验 key,未识别 key 丢弃或归入 `"other"`。

---

#### 27. `promote_strategies` 修改 in-place 但 sources 仍在 list

`maintenance/promoters.py:90`:promote 后把 source strategies 标记 `generalization_status="validated"`,
但**没有从 `state.all_strategies` 移除**。

**影响**:
- 同一条知识同时以 strategy 和 guideline 形式存在 DB 中,占空间。
- 检索时可能两次返回相似内容,降低 diversity。

**建议**:promote 后从 source list 中移除,或在持久化时过滤 `generalization_status="validated"` 的 strategy。

---

#### 28. `_check_embedding_model_consistency` 在 legacy 数据上 silently stamp

`design_memory/diagram_design_memory.py:121` 对没有 metadata 的 collection 自动 stamp 当前模型名。

**影响**:如果 legacy DB 是用别的 embedding 模型生成的(用户之前换过模型),stamp 会把它伪装成当前模型,
反而**屏蔽**了真实的 mismatch。

**建议**:legacy 数据(无 metadata)输出明确 WARNING,要求用户显式确认或手动 reindex,而不是自动 stamp。

---

#### 29. Retriever 的 diversity penalty 太弱

`design_memory/diagram_design_retriever.py` 的 diversity weight 是 0.20。两条 cosine ≈ 0.95 的近似重复条目,
diversity penalty 0.20 × 0.95 = 0.19,不足以把第二条挤出 top-k。

**影响**:top-k 容易被同义近邻填满,真正多样的视角被挤出。

**建议**:对极相似条目(cos > 0.85)用阶梯式重罚,而不是线性加权。

---

#### 30. 6 个 distillation agent 共用同一个 role="distiller"

`config.py` 只暴露一个 `distiller` role,`StrategyExtractor`、`GuidelineExtractor`、`PrinciplePromoter`、`DemotionJudger`、`MergeJudger` 全用同一模型。

**影响**:无法对成本敏感的任务(如 MergeJudger 简单二分类)用便宜模型,对复杂任务(如 PrinciplePromoter)用强模型。

**建议**:细化 role(如 `distiller_extractor`、`distiller_judger`),或允许 agent 级别 role override。

---

#### 31. 无 sample-level 容错

`engine.py:_run_iteration_phase` 内 `refinement_service.run_loop` 抛异常时直接传播,整个 Phase 1 中断。
失败 sample 的局部成果(strategies、history)丢失。

**建议**:try/except 包裹单 sample 处理,失败时记录到 error log 并继续下一个 sample。

---
