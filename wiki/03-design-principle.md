<!-- Last verified: 2026-03-17 | Current stage: P1 -->

# EvoDesign — 设计准则

从 `tailwind.config.js`、`index.css`、组件实际使用中提取。**这是 Agent 写 UI 代码的硬性约束。**

---

## 视觉语言：Glassmorphism + Gradient Mesh

整体风格定义为"毛玻璃面板浮在多彩渐变网格上"。所有容器都应有半透明背景 + 模糊 + 微弱边框高光。

---

## 色彩系统

### Brand 色阶（蓝）

| Token | Hex | 用途 |
|-------|-----|------|
| `brand-50` | `#f2fbff` | 输入框 focus 底色、hover 行底色 |
| `brand-100` | `#d8f1ff` | — |
| `brand-200` | `#b4e1ff` | focus ring、输入框 branded 边框 |
| `brand-300` | `#84cbff` | hover 边框强调 |
| `brand-400` | `#52aeff` | 次要强调、selection 底色 `rgba(82,174,255,0.35)` |
| `brand-500` | `#318dff` | **主色**。按钮渐变起点、focus-visible outline、发光动画 |
| `brand-600` | `#1e6ef5` | 按钮渐变终点 |
| `brand-700` | `#1756d1` | — |
| `brand-800` | `#1a49a5` | — |
| `brand-900` | `#1a3f81` | — |

### 中性色

使用 Tailwind `slate` 色阶，不自定义。

| 场景 | Light | Dark |
|------|-------|------|
| 正文 | `text-slate-700` / `text-slate-600` | `text-slate-300` / `text-slate-400` |
| 标题 | `text-slate-900` | `text-slate-100` |
| 次要文字 | `text-slate-500` | `text-slate-400` |
| 页面底色 | 渐变 mesh（见下文） | `#020617` + 渐变 |
| 画布底色 | `canvas: #f5fbff` | — |
| 滚动条 | `#cbd5e1` → hover `#94a3b8` | — |

### 页面背景 Mesh

```css
/* Light */
radial-gradient(#f8d6ea, transparent),   /* 左上粉 */
radial-gradient(#dbeafe, transparent),   /* 右上蓝 */
radial-gradient(#cffafe, transparent),   /* 下方青 */
#eef4ff                                  /* 基底 */

/* Dark */
radial-gradient(rgba(59,130,246,0.16), transparent),   /* 左上蓝 */
radial-gradient(rgba(168,85,247,0.12), transparent),   /* 右上紫 */
#020617                                                 /* 基底 */
```

组件内局部 mesh 使用 `.bg-soft-mesh` / `.bg-soft-mesh-dark`。

### Dark Mode

- 策略：`darkMode: 'class'`（`html.dark`）
- 每个组件必须同时声明 `dark:` 对应值
- 玻璃面板暗色：`dark:border-white/10 dark:bg-slate-900/{55-65} dark:ring-white/10`

---

## 字体

| Token | 字体族 | 用途 |
|-------|--------|------|
| `font-sans` | `"Inter", system-ui, sans-serif` | 正文、UI 控件、H3+ 小标题 |
| `font-display` | `"Space Grotesk", sans-serif` | **H1 标题（必须）**、H2 标题（推荐）、Hero 区大字 |

### 字体层级规则

| 级别 | 字体 | 强制性 |
|------|------|--------|
| H1 (`text-3xl`+) | `font-display` | **必须** — 所有页面 H1 统一使用 Space Grotesk |
| H2 (`text-xl` ~ `text-2xl`) | `font-display` 推荐 | 可视上下文选择 |
| H3+ / 正文 / UI | `font-sans` | 默认 |

- 字体通过 CSS 声明加载（非 Google Fonts `<link>`）
- 全局开启 `text-rendering: optimizeLegibility` + `-webkit-font-smoothing: antialiased`

---

## 玻璃面板（核心组件类）

| 类名 | 圆角 | 模糊 | 场景 |
|------|------|------|------|
| `.card-glass` | `rounded-3xl` (24px) | `backdrop-blur-2xl` | 大卡片：Hero 区、Pricing 卡 |
| `.surface-glass` | `rounded-2xl` (16px) | `backdrop-blur-xl` | 中面板：Auth 面板、侧栏、DNA cabin |

两者共享的 Light/Dark 模式属性：

```
Light: border-white/{55-65} bg-white/{60-70} ring-white/70
       shadow-[0_22px_50px_rgba(148,163,184,0.28)]

Dark:  border-white/10 bg-slate-900/{55-65} ring-white/10
       shadow-[0_25px_65px_rgba(2,6,23,0.55)]
```

### 行内玻璃

用于局部覆盖（Modal、悬浮卡片），直接内联：

```
rounded-[28px] border border-white/40 bg-white/45 backdrop-blur-xl
shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_30px_60px_-35px_rgba(15,23,42,0.45)]
```

**规则：** 不要使用 `bg-white` 纯白；所有面板必须带透明度（`/45` ~ `/70`）+ `backdrop-blur`。

---

## 按钮

| 类名 | 样式概要 | 用途 |
|------|---------|------|
| `.btn-primary` | `rounded-xl` + brand 渐变 + 白字 + 阴影 + hover 上浮 1px | 主操作 |
| `.btn-muted` | `rounded-xl` + 白底 + slate 边框 + hover 变 brand | 次要操作 |
| Pill 按钮 | `rounded-full border px-3 py-1.5 text-xs font-medium` | Quick Prompt Chips、Tab |
| 图标按钮 | `rounded-lg px-2 py-2` + hover 背景 | 返回、关闭、设置 |

### .btn-primary 完整定义

```
inline-flex items-center justify-center rounded-xl
bg-gradient-to-br from-brand-500 to-brand-600
px-5 py-2.5 text-sm font-semibold text-white
shadow-lg shadow-brand-500/30
transition-all hover:shadow-brand-500/40 hover:translate-y-[-1px]
active:translate-y-[0px]
focus-visible:ring-2 focus-visible:ring-brand-200
disabled:opacity-70 disabled:cursor-not-allowed
```

---

## 卡片

| 场景 | 圆角 | 边框 | 特效 |
|------|------|------|------|
| Gallery 作品卡 | `rounded-2xl` | `border-slate-200/60` / `dark:border-slate-700/80` | hover 时 JS 注入 `glowColor` box-shadow |
| 项目卡 | `rounded-2xl` | 同上 | hover `shadow-lg` |
| 空态模板卡 | `rounded-2xl` | `border-dashed border-slate-300/80` | hover 变 `border-brand-400` |
| DNA 基因卡 | `.card-glass` | 自带 | — |

**规则：** 所有卡片统一 `rounded-2xl`（16px），只有 Hero 区大面板才用 `rounded-3xl`。

---

## 模态框

```
/* 遮罩 */
fixed inset-0 z-50 flex items-center justify-center
bg-slate-900/50 backdrop-blur-sm px-4

/* 内容面板 */
surface-glass rounded-2xl p-6
shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_10px_40px_-20px_rgba(15,23,42,0.45)]

/* 进入动画 */
.gallery-modal-enter: 340ms cubic-bezier(0.22, 1, 0.36, 1)
transform: translateY(16px) scale(0.97) → translateY(0) scale(1)
```

---

## 导航

| 元素 | 实现 |
|------|------|
| 全局 Header | `sticky top-0 z-50 border-b border-white/60 bg-white/45 backdrop-blur-2xl` |
| 侧栏 | `.surface-glass` 内含项目列表 |
| Tab 切换 | `rounded-full` pill 按钮组 |

---

## 图标

- 库：**Lucide React**（`lucide-react`）
- 尺寸：UI 内 `w-4 h-4` / `w-5 h-5`；Hero 装饰 `w-6 h-6`
- 颜色：跟随文字颜色（`currentColor`）

---

## 间距规律

| 场景 | 值 |
|------|-----|
| 面板内边距 | `p-4` (紧凑) / `p-6` (标准) / `p-7 sm:p-8` (宽松) |
| 卡片间距 | `gap-4` / `gap-5` / `gap-6` |
| 按钮内边距 | Primary: `px-5 py-2.5`；Muted: `px-4 py-2.5`；Pill: `px-3 py-1.5` |
| Section 垂直间距 | `mb-3` (紧) / `mb-6` (标准) / `mb-10` (大段) |
| 图标与文字间距 | `gap-1` / `gap-1.5` / `gap-2` |

---

## 响应式

| 断点 | 用途 |
|------|------|
| 默认 | 移动端单列 |
| `sm` (640px) | Gallery 2 列 masonry；表单 padding 增大 |
| `lg` (1024px) | Gallery 3 列 masonry；Auth 双栏布局 `lg:grid-cols-[1.05fr_0.95fr]` |
| `xl` / `2xl` | 偶尔用于宽屏微调 |

- 移动端优先（`mobile-first`）
- Gallery masonry 使用 CSS `columns`（非 Grid），在 `@layer utilities` 中定义

---

## 动画体系

### 设计原则

- 缓动曲线统一使用 `cubic-bezier(0.22, 1, 0.36, 1)`（快进慢出，偏弹性）
- 入场动画 300-560ms，退场 ≤300ms
- 所有动画尊重 `@media (prefers-reduced-motion: reduce)` → `animation: none !important`

### 动画分类

| 类别 | 前缀 | 典型用法 |
|------|------|---------|
| Hero 入场 | `hero-*` | `hero-fade-up` + `hero-delay-{1-5}`（80ms 递增交错） |
| Gallery | `gallery-*` | timelapse 节点脉冲、masonry 骨架、modal 弹入、重力漂移 |
| DNA | `dna-*` | 螺旋飘移、扫描线、粒子上升、光环扩散 |
| Toast | `toast-*` | `toast-slide-in` / `toast-slide-out`：从右滑入/滑出 |
| 通用 | `animate-*` | `animate-pulse-glow`、`animate-float-node`、`animate-draw-line` |
| 交互 | `send-btn-glow` | 发送按钮蓝光呼吸 |

### 关键帧速查

| 动画 | 时长 | 效果 |
|------|------|------|
| `heroRiseIn` | 560ms | translateY(14px) + scale(0.995) → 正常 |
| `heroSurfaceIn` | 520ms | translateY(10px) + blur(2px) → 正常 |
| `galleryModalIn` | 340ms | translateY(16px) + scale(0.97) → 正常 |
| `toastSlideIn/Out` | 300ms | translateX(100%) ↔ 0 |
| `pulseGlow` | 3s 循环 | opacity 0.5↔1 + scale 1↔1.05 |
| `dnaHelixDrift` | 8s 循环 | translateY(0↔-6px)，交替方向 |

---

## Focus & 无障碍

```css
:focus-visible {
  outline: 2px solid #318dff;    /* brand-500 */
  outline-offset: 2px;
  border-radius: 4px;
}
:focus:not(:focus-visible) {
  outline: none;                  /* 鼠标点击不显示 outline */
}
```

- 项目卡片：TD-002 待修复 — `<div>` 应改为 `<button>` 以支持键盘访问
- Gallery masonry：TD-003 待修复 — 缺 `role="list"` 语义
- Canvas 切换按钮：TD-004 待修复 — 缺 `aria-pressed`

---

## 不做什么

| 禁止 | 原因 |
|------|------|
| 使用纯白 `bg-white` 作面板底色 | 破坏玻璃效果；必须带透明度 |
| 引入第三方 UI 组件库（MUI、Ant Design 等） | 与 glassmorphism 风格冲突 |
| 使用 `i18next` | 已有自研 LanguageProvider，仅 zh/en |
| 新增 Google Fonts `<link>` 标签 | 字体通过 CSS `font-family` 声明 |
| 跳过 `dark:` 变体 | 所有新组件必须同时写 light + dark |
| 动画不加 `prefers-reduced-motion` | `index.css` 底部已有全局 reduce 规则，新增 utility 类必须追加到该规则中 |
| 为 primary CTA 自定义渐变色 | 统一使用 `.btn-primary`（`from-brand-500 to-brand-600`），不允许偏淡变体 |
| H1 标题使用 `font-sans` | 所有页面 H1 必须使用 `font-display (Space Grotesk)`，维护品牌字体层级 |
| 玻璃面板透明度低于 `/50` 或高于 `/70` | 收窄到 `/55` ~ `/65` 范围，确保可读性与层次感平衡 |
