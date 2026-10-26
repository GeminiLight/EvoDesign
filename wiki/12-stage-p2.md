<!-- Last verified: 2026-03-17 | Current stage: P1 | May be outdated after Stage P2 starts -->

# P2 — 体验优化与商业化 [planned]

**关联 PRD：** PRD-007 ~ PRD-012
**目标：** 产品完善、用户体验提升、企业级功能启动
**前置依赖：** P1 完成

---

## PRD-007：落地页输出预览

**背景：** 首屏无图表展示，用户无法在点击前了解输出质量。

**需求：**
- Hero 区下方增加"样本输出"区域：2-3 张真实生成图表（静态截图）
- 或横向滚动展示 6-8 张图表截图，点击可查看生成 Prompt
- Prompt 类型 Pill 下方增加单行说明文案（随 Pill 切换）

---

## PRD-008：工作台 Agent 面板体验优化

**背景：** P0 · TASK-002-C 已做基础优化，仍有改进空间。

**需求：**
- 状态消息改为小型内联 Badge
- 快捷 Prompt Chips 紧接状态 Badge 展示
- Chips 样式改为 Pill Button（`rounded-full border`）
- Canvas 切换按钮从全局导航栏移入画布工具栏区域

---

## PRD-009：项目空页状态 + 模板引导

**需求：**
- 项目页空状态替换为紧凑设计（最大高度 200px）
- 空状态下展示 3 张"流行模板"卡片（微服务架构 / 用户流程 / 数据管道）
- 模板卡片含 SVG 预览，点击进入工作台并预填 Prompt

---

## PRD-010：DNA 页布局基因扫描空态优化

**需求：**
- 布局基因扫描中不再显示"0/10 key traits"空状态
- 替换为 3 张灰显占位基因卡片（Grid Density / Padding Rhythm / Column Strategy）
- 随 Agent 学习逐步"点亮"占位卡

---

## PRD-011：企业品牌 VI 注入

**背景：** Team/Enterprise 付费的核心价值主张（见 `00-product-proposal.md` §2.1）。

**需求：**
- 工作台右侧属性区提供"品牌记忆"上传入口
- 用户可上传：品牌色盘（Hex）、字体名称、Logo SVG
- 上传后转化为风格设计 Agent 的硬性约束
- 工作台可一键预览"应用企业 VI"效果
- Enterprise 专属，Free/Pro 可见入口但需升级

**API 设计（预估）：**
```
GET  /api/v1/brand/profile
POST /api/v1/brand/profile
POST /api/v1/brand/apply/{project_id}
```

---

## PRD-012：项目自动命名

**需求：**
- 生成完成后，结构提取 Agent 输出 2-4 字关键词作为项目默认标题
- 替换当前 "图表 1 / 图表 2" 自增命名
- 用户手动修改后不再自动覆盖

---

## 任务拆解

> P2 启动时再详细拆解。以上为需求定义，具体 TASK 分解待 P1 完成后进行。
