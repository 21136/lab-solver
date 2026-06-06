# UI Phase 3 — 精致化抛光（Polish）

**版本**: 2026-06-06  
**状态**: ✅ 2026-06-06 全部 Pack 已实施  
**前置**: [UI Phase 1](./README.md) ✅ · [UI Phase 2](./UI_PHASE2_NON_STEP3.md) ✅  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**来源**: 2026-06-06 UI 复审（Phase 2 完成后整体审计）

### 用户决策（2026-06-06）

| 项 | 决定 |
|----|------|
| 步骤条对齐 | **A2** — 与 Step 2 `#guidedModeContent` 同 `max-width: 960px`，左缘对齐 |
| Pack E 品牌 | **E1 + E3 实施**；**E2、E4 本期不做**（见 §9） |

**建议实施顺序**: **A → B → C → D → E → F**

---

## 1. 目标与边界

### 1.1 目标

在 **不改变产品流程与 Step 3 三栏结构** 的前提下，解决 Phase 2 之后仍存在的：

- 视觉辨识度不足（GitHub-dark 安全牌）
- 面板层次偏平（卡片套卡片同色）
- 细节债务（全局 `user-select`、工具栏按钮堆砌、内联 `style`）
- 动效「有但不精致」（关键路径缺编排）

将界面从 **「合格生产力工具」** 提升到 **「有打磨感、可复制体验顺畅」**。

### 1.2 明确不做

| 不做 | 原因 |
|------|------|
| 重写 Step 3 三栏 grid 或改 `renderDeliverableWorkspace()` 数据流 | 用户已确认 Step 3 结构定稿 |
| React / Tailwind / 新 UI 框架 | 维持 vanilla 栈 |
| 3D / WebGL / 视差 / scroll 磁吸 | `DESIGN.md` §2 · `MOTION_INTENSITY = 3` |
| 改 agent / Python 后端 | 纯前端（除必要 IPC 无） |
| 亮色主题 | 本期不展开；深色默认不变 |

### 1.3 允许改动范围（Step 3）

| 允许 | 禁止 |
|------|------|
| `.deliverable-toolbar` 导出区布局（dropdown / 分组） | 修改 `.deliverable-grid` 列宽比例或栏数 |
| 三栏 **背景/边框/阴影** 层次（CSS token） | 重排 `#deliverable-workspace` DOM 树主结构 |
| 节切换 / 预览 tab 的 **过渡动效** | 变更「复制本节」为主 CTA 的定位 |
| 窄屏预览浮层交互微调（遮罩、Esc） | 重做 mockup 选型（方案 4 已锁定） |

### 1.4 成功标准（整体）

- 用户在答案正文区 **可直接拖选复制**，无需依赖按钮
- Step 3 工具栏 **一眼可扫**：主操作「复制本节」突出；导出 ≤ 2 个可见控件（其余收纳）
- 三栏一眼能分清 **导航 / 正文 / 预览** 主次
- 步骤条与主内容区 **水平重心一致**
- 节切换、侧栏展开有 **200ms 级** 可感知但不打扰的过渡
- `prefers-reduced-motion: reduce` 下全部动效归零或禁用

---

## 2. 现状审计摘要

Phase 1～2 已完成 token、图标、三步条、Step1 双栏、Step2 hero、设置 nav、历史卡片。复审结论：**架构正确，精致度与辨识度仍不足**。

### 2.1 做得好的（保持）

- OKLCH 友好 token + 8pt 间距 + Lucide SVG
- Step 3 三栏 + `72ch` 正文 + `line-height: 1.6`
- 每屏 primary 原则在 Step 1 / Step 3 正文头已基本遵守
- `focus-visible`、`prefers-reduced-motion`、空状态统一

### 2.2 待改进（本期针对）

| 问题 | 严重度 | 涉及区域 |
|------|--------|----------|
| `body { user-select: none }` 与「复制型工具」冲突 | 高 | 全局 |
| Step 3 导出区 6+ 个同级 secondary 按钮 | 高 | `#deliverable-workspace` toolbar |
| 三栏均为 `bg-secondary` + 同边框，层次扁平 | 中 | `.deliverable-grid` 子列 |
| 步骤条 `max-width: 520px` 左漂，宽屏重心失调 | 中 | `.steps-bar` |
| 侧栏服务器状态 9px 竖排字可读性差 | 中 | `.sidebar-status` |
| 节切换内容区切换偏硬 | 低 | `app.js` + CSS |
| 思考侧栏展开/收起无过渡 | 低 | `.agent-thought-sidebar` |
| Step 2 修订区多个 `btn-primary` 并排 | 中 | `#agentRevisePanel` |
| `index.html` ~39 处内联 `style="display:none"` | 低 | 全局维护性 |
| 加载遮罩通用 spinner | 低 | `#loadingOverlay` |
| 历史卡片缺内容摘要 / 状态色点 | 低 | `#historyList` |
| 工具箱模式视觉弱于引导模式 | 低 | `#toolboxPanel` |
| 品牌辨识度低（GitHub-dark + 系统字体） | 低（需决策） | 全局 token |

---

## 3. 设计原则（继承 + 补充）

继承 [DESIGN.md](../../DESIGN.md) §1～§6，补充：

| 原则 | 说明 |
|------|------|
| **抛光不改流程** | 只减视觉噪音、加层次与过渡，不加新步骤 |
| **复制优先** | 默认可选中文本；仅拖拽区、按钮、chrome 禁用选择 |
| **收纳胜过堆砌** | 同类操作（导出格式）进 menu，不横向排 6 按钮 |
| **中间亮、两侧暗** | 答案正文栏 elevation 高于 nav / preview |
| **动效克制** | 仅 2～3 处关键路径；时长 150～300ms；可用 GSAP 编排但禁止 scroll 特效 |
| **一步一 PR** | Pack 可独立合并，降低回归风险 |

### 3.1 动效与 GSAP

- 默认：**纯 CSS** `transition` / `@keyframes`（与 Phase 1～2 一致）
- 可选：在 Pack D 对 **节切换 timeline、侧栏高度** 使用 GSAP，须：
  - 注册 `gsap.matchMedia()` 处理 `prefers-reduced-motion`
  - 不引入 ScrollTrigger / 视差
  - 打包体积需评估（Electron 可接受小幅增加）

---

## 4. Pack 划分与优先级

```
Pack A  全局体验修复（user-select、步骤条）     ★★★  P0
Pack B  Step 3 层次 + 导出收纳                  ★★★  P0
Pack C  壳层与状态区（侧栏、修订区 CTA）        ★★   P1
Pack D  动效精修（节切换、侧栏、Toast 编排）    ★★   P1
Pack E  品牌差异化（accent 微调 + 历史 enrich） ★  P1 — ✅ 方案已确认
Pack F  维护性（内联 style、loading skeleton）  ★    P2
```

建议实施顺序：**A → B → C → D → E → F**（E 在 A～D 之后、F 之前）。

---

## 5. Pack A — 全局体验修复 ✅

### 5.1 `user-select` 策略

**现状**

```css
/* styles.css — 全局禁用 */
html, body { user-select: none; }
```

**目标**

| 区域 | `user-select` |
|------|----------------|
| `body` 默认 | `text`（或移除全局规则） |
| 按钮、步骤条、侧栏 nav、标题栏 | `none` |
| `.deliverable-section-body`、`.form-input`、`textarea`、合规正文 | `text`（已有部分覆盖，改为正向声明） |
| 上传区拖拽 | `none`（避免误选） |

**验收**

- [ ] 答案正文、设置说明、历史标题可用鼠标拖选
- [ ] 点击按钮不会意外选中按钮文字（或可接受）
- [ ] 上传区拖拽不受影响

### 5.2 步骤条对齐 — ✅ 已选 **A2**

**现状**: `.steps-bar { max-width: 520px; }` 左对齐，宽屏与下方 grid 脱节。

**已定方案 A2**: 步骤条外包一层与 Step 2 正文相同的宽度容器，**左缘与 `.parse-result` 对齐**（非居中）。

**实现规格**

```html
<!-- index.html #tab-home -->
<div class="steps-bar-wrap">
  <div class="steps-bar" aria-label="解题流程">…</div>
</div>
```

```css
/* styles.css */
.steps-bar-wrap {
  max-width: 960px;          /* 与 .parse-result / #guidedModeContent 一致 */
  width: 100%;
  margin-bottom: var(--space-5);
  flex-shrink: 0;
}
.steps-bar {
  max-width: none;           /* 移除原 520px 上限 */
  width: 100%;
  margin-bottom: 0;          /* 外边距改由 wrap 承担 */
}
```

**Step 1 说明**: Step 1 `.step1-grid` 在极宽屏下可略宽于 960px；步骤条仍按 960px 左对齐，与 Step 2/3 重心一致（用户已确认）。

**验收**

- [ ] 1280px / 1920px 下步骤条左缘与 Step 2 `.parse-result` 左缘对齐
- [ ] 三步标签不换行、连线不断裂
- [ ] Step 1 / 2 / 3 切换时步骤条位置不跳动

### 5.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/renderer/styles.css` | `user-select`、`.steps-bar-wrap`、`.steps-bar` |
| `src/renderer/index.html` | 步骤条外包 `.steps-bar-wrap` |

---

## 6. Pack B — Step 3 层次 + 导出收纳

### 6.1 三栏 elevation 语言

**现状**: `.deliverable-nav-col` / `.deliverable-content-col` / `.deliverable-preview-col` 均为 `background: var(--bg-secondary)`。

**目标层次**

| 栏 | 背景 | 边框 | 说明 |
|----|------|------|------|
| 左 nav | `--bg-secondary` | `border-subtle` 或仅右边线 | 退后 |
| **中正文** | `--bg-card` 或 `--bg-primary` | 无全框 / 轻阴影 | **hero** |
| 右 preview | `--bg-secondary` | 同左 | 退后 |

可选：中间栏 `box-shadow: var(--shadow-sm)`，外框 `.deliverable-workspace` 保持 `bg-card`。

**验收**

- [ ] 不加载内容时三栏主次可区分
- [ ] 深色对比仍 ≥ WCAG AA（正文区）

### 6.2 导出工具栏收纳

**现状**（`index.html` `.deliverable-toolbar-actions`）:

- Markdown（复制）、Markdown（下载）、docx、代码 zip、图表 zip、JSON — 6 控件横排

**目标线框**

```
┌─────────────────────────────────────────────────────────────┐
│ [未验证] 说明…          [导出 ▾]  [docx]  [更多 ⋯]          │
└─────────────────────────────────────────────────────────────┘
```

| 控件 | 类型 | 内容 |
|------|------|------|
| 主外露 | `btn-secondary btn-sm` | **下载 docx**（或用户调研后最常项） |
| 导出 ▾ | `details` 或自定义 dropdown | Markdown 复制/下载、zip×2、JSON |
| 可选 | `btn-ghost` | 「更多」仅当 dropdown 不可用时 |

**交互**

- 点击外部 / Esc 关闭 menu
- `focus-visible` 可键盘操作
- 不改变现有 `onclick` 处理函数名，仅改 DOM 挂载点

**验收**

- [ ] 默认可见 secondary 按钮 ≤ 2 个（含 dropdown 触发器）
- [ ] 所有原导出能力仍可触达（无功能删减）
- [ ] 窄屏 toolbar 换行不遮挡「复制本节」（复制在内容头，已分离 — 保持）

### 6.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/renderer/styles.css` | `.deliverable-*-col` elevation、`.export-menu` |
| `src/renderer/index.html` | toolbar DOM 重组 |
| `src/renderer/app.js` | 可选：dropdown 开关、`closeExportMenu()`；**不改** `renderDeliverableWorkspace` 核心逻辑 |

---

## 7. Pack C — 壳层与 CTA 纪律

### 7.1 侧栏服务器状态

**现状**: `#serverStatusText` 竖排 `writing-mode: vertical-rl`，9px。

**目标**

```
┌────────┐
│  ●     │  ← status-dot
│ 在线   │  ← 10–11px 横排，或 tooltip 仅 hover 显示
└────────┘
```

- 宽屏侧栏仍 72px：默认只显示 **色点**；hover 或 `title` 显示「在线 / 连接中」
- 可选（P2）：hover 展开至 120px（`DESIGN_VARIANCE` 允许范围内需评估）

**验收**

- [ ] 状态可识别（色点绿/红/灰）
- [ ] 文字可读或不依赖竖排

### 7.2 Step 2 / Step 3 修订区 primary 纪律

**现状**: `#agentRevisePanel` 内「按选中范围修订」为 primary，与规范「每面板 1 primary」在展开态仍 OK；但与其他 secondary 并排时视觉权重需核对。

**目标**

- 展开修订区：**仅保留一个** `btn-primary`（「按选中范围修订」）
- 「全部重来」等降为 `btn-secondary` 或 `btn-ghost`（已是 secondary 的保持）
- Sticky 底栏「执行计划」与「生成计划」维持现有层级（生成 secondary、执行 primary）

**验收**

- [ ] 修订区展开后仅 1 个蓝色实心主按钮
- [ ] Step 2 sticky 底栏仅 1 个 primary

### 7.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/renderer/styles.css` | `.sidebar-status` |
| `src/renderer/index.html` | 侧栏状态 DOM；修订按钮 class |
| `src/renderer/app.js` | 可选：侧栏 hover 展开逻辑 |

---

## 8. Pack D — 动效精修

### 8.1 节切换（Deliverable nav）

**行为**: 点击左侧节项 → 中间正文 + 右预览更新。

**动效**（`MOTION_INTENSITY = 3`）

| 属性 | 值 |
|------|-----|
| 正文区 | `opacity` 0→1 + `translateY(4px→0)`，200ms `ease-out` |
| 并行 | 不阻塞数据渲染；`requestAnimationFrame` 或 GSAP `fromTo` |

**实现选项**

1. CSS：切换时对 `.deliverable-section-body` 加 `.is-entering` class，animation 结束移除
2. GSAP：`gsap.fromTo(body, { opacity: 0, y: 4 }, { opacity: 1, y: 0, duration: 0.2 })`

### 8.2 思考侧栏

**行为**: `#thoughtSidebarToggle` 展开/收起 `#agentThoughtBody`。

**动效**

- `max-height` + `opacity` 过渡（避免 animating `height` 用 `grid-template-rows` 或 JS 测高）
- `prefers-reduced-motion`: 即时切换

### 8.3 已有动效审计（保持）

- `stepEnter` 步骤切换 — 保持
- Toast slide-in — 保持
- 按钮 hover `translateY(-1px)` — 保持

**验收**

- [ ] 节切换有可感知淡入，无布局跳动
- [ ] reduced-motion 下无动画
- [ ] 无 `top/left/width/height` 动画（用 transform/opacity）

### 8.4 涉及文件

| 文件 | 改动 |
|------|------|
| `src/renderer/styles.css` | `.deliverable-section-body.is-entering`、侧栏过渡 |
| `src/renderer/app.js` | 节切换 hook、`toggleThoughtSidebar` |
| `package.json` / CDN | 仅当选用 GSAP 时添加依赖 |

---

## 9. Pack E — 品牌差异化（P1 · ✅ 已确认）

> 原则：**小步拉开与 GitHub-blue 的辨识度**，不引入新字体文件、不加背景纹理，避免偏离「学术生产力」气质。

### 9.1 选项与决定

| 选项 | 内容 | 决定 | 理由 |
|------|------|------|------|
| **E1 Accent 微调** | 主色略偏靛，仍单一 accent | ✅ **做** | 低风险、全站 token 一处改 |
| **E2 标题 display 字体** | woff2 仅用于标题 | ❌ **本期不做** | 打包体积 + 中英混排需额外调参；收益不如 E1/E3 |
| **E3 历史卡片 enrich** | 一行摘要 + 状态色点 | ✅ **做** | 纯前端、历史页立刻变「有用」 |
| **E4 背景微纹理** | noise / grain | ❌ **本期不做** | Electron 全屏纹理收益小；与扁平生产力风格易冲突 |

### 9.2 决策记录

| 决策项 | 选择 | 日期 |
|--------|------|------|
| 步骤条对齐 A1 / A2 | **A2** | 2026-06-06 |
| Accent 调整 | **E1 偏靛**（见 §9.3） | 2026-06-06 |
| Display 字体 | **不做** | 2026-06-06 |
| 历史卡片摘要 | **做** | 2026-06-06 |
| 背景纹理 | **不做** | 2026-06-06 |

### 9.3 E1 — Accent token（偏靛，非青色）

与 GitHub `#58a6ff` 区分，仍保持足够对比度与 `--green` 语义色可分辨。**实施时同步改 `styles.css` 与 [DESIGN.md](../../DESIGN.md) §3**。

| Token | Phase 1～2 | Phase 3（E1） |
|-------|------------|---------------|
| `--accent` | `#58a6ff` | `#6b9fff` |
| `--accent-hover` | `#79b8ff` | `#8ab4ff` |
| `--accent-dim` | `#1f4e8c` | `#2a4a7a` |
| `--accent-muted` | `color-mix(…15%)` | `color-mix(in oklch, var(--accent) 15%, transparent)`（随新 accent 自动更新） |
| `--shadow-accent` | `rgba(88, 166, 255, 0.15)` | `rgba(107, 159, 255, 0.15)` |

**不改动**: `--green` / `--red` / `--yellow` / `--purple` 语义色。

**验收**

- [ ] 主按钮、步骤当前圈、侧栏 active 条为新 accent，无遗漏硬编码 `#58a6ff`
- [ ] 正文与 accent 对比仍 ≥ WCAG AA

### 9.4 E3 — 历史卡片 enrich

**目标线框**

```
┌─ history-card ─────────────────────────────────────┐
│ ● 张三_实验二_python.docx          2026-06-05 14:32 │
│ 标准模式 · 4 节 · 已生成答案                        │
│ 摘要：步骤与分析、结果说明…（单行 ellipsis）          │
│                              [打开]  [删除]         │
└────────────────────────────────────────────────────┘
```

| 元素 | 规格 |
|------|------|
| **状态色点** `.history-card-status` | 绿=有 deliverable/已完成；灰=仅计划或未完成；8px 圆点，与标题同行 |
| **摘要** `.history-card-excerpt` | 单行 `text-overflow: ellipsis`；优先 `sections` 首节标题拼接，否则 `documentTitle` 前 60 字 |
| **meta 行** | 保留现有模式 tag + 节数；与 P2-D 卡片 footer 兼容 |

**数据来源**: 现有 `localStorage` 历史项；不新增后端字段。`renderHistory()` 内计算 excerpt。

**验收**

- [ ] 有摘要时卡片高度略增但不破 grid
- [ ] 无摘要数据时降级为仅 meta 行（不显示空 excerpt）
- [ ] 色点语义与记录状态一致

### 9.5 涉及文件

| 文件 | 改动 |
|------|------|
| `src/renderer/styles.css` | `:root` accent；`.history-card-status`、`.history-card-excerpt` |
| `src/renderer/app.js` | `renderHistory()` 摘要与色点 |
| `DESIGN.md` | §3 accent 表同步 |

---

## 10. Pack F — 维护性（P2）

### 10.1 内联 `style` 清理

- 将 `index.html` 中 `style="display:none"` 迁移为 `.is-hidden` 或 `[hidden]` + CSS
- 动态面板由 `app.js` 统一 `classList.toggle('is-hidden')`

### 10.2 加载态

- `#loadingOverlay`：spinner → 品牌化文案分步（「连接后端…」「加载编辑器…」已有 `#loadingStatus`）+ 可选 skeleton 形状

### 10.3 工具箱视觉对齐

- `.tool-card` 边框/hover 与 `.section-card` 统一
- toolbox header 与 Step 2 `.detect-hero` 间距 rhythm 对齐

---

## 11. 线框参考

### 11.1 Step 3 抛光后（Pack B）

```
┌─ deliverable-workspace (bg-card) ───────────────────────────┐
│ [badge] 提示…                    [导出▾] [docx]            │
├──────────┬─────────────────────────────┬─────────────────────┤
│ nav      │  CONTENT (bg-card, hero)    │ preview             │
│ secondary│  标题        [复制本节]★   │ secondary           │
│ 退后     │  正文 72ch / lh 1.6         │ 代码 | 图表         │
└──────────┴─────────────────────────────┴─────────────────────┘
```

### 11.2 步骤条对齐（Pack A2）

```
┌─ content padding ───────────────────────────────────────────┐
│     (1)──────(2)──────(3)     ← 与下方 960px 内容同左缘      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Step 1 grid / Step 2 parse-result                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 12. 测试与回归清单

| 场景 | 检查 |
|------|------|
| Step 1 拖拽上传 | 正常；不误选 UI 文字 |
| Step 2 生成/执行计划 | primary 唯一；sticky 底栏可见 |
| Step 3 切换各节 | 正文更新；动效不闪屏；复制本节可用 |
| Step 3 完成后 | 页头与 `#exportActionBar` 显示「回到主页」；点击回到 Step 1 并重置任务 |
| Step 3 导出 dropdown | 各格式功能等价于改前 |
| 窄屏 &lt; 1200px | 预览浮层；toolbar 换行 |
| `prefers-reduced-motion` | 系统开启后无动画 |
| 键盘 Tab | dropdown、nav、导出可聚焦 |
| 历史 / 设置 | 无布局回退 |

自动化：无新增 pytest；手动走查为主。若改 `app.js` 导出 DOM，可补一条轻量 DOM 结构测试（可选）。

---

## 13. 文件总览

| Pack | 主要文件 |
|------|----------|
| A | `styles.css`, `index.html` |
| B | `styles.css`, `index.html`, `app.js`（toolbar only） |
| C | `styles.css`, `index.html`, `app.js` |
| D | `styles.css`, `app.js` [, `package.json`] |
| E | `styles.css`, `app.js`, `assets/` |
| F | `index.html`, `styles.css`, `app.js` |

**不动**（除非 bug）：`renderDeliverableWorkspace()` 数据结构、`.deliverable-grid` 三列定义、agent 后端。

---

## 14. 实施进度

| Pack | 范围 | 状态 |
|------|------|------|
| P3-A | 全局 user-select + 步骤条对齐 | ✅ 2026-06-06 |
| P3-B | Step 3 elevation + 导出收纳 | ✅ 2026-06-06 |
| P3-C | 侧栏状态 + 修订 CTA | ✅ 2026-06-06 |
| P3-D | 节切换 / 侧栏动效 | ✅ 2026-06-06 |
| P3-E | Accent 微调 + 历史 enrich（E1+E3） | ✅ 2026-06-06 |
| P3-F | 内联 style / loading / 工具箱 | ✅ 2026-06-06 |

完成 Pack 后在此表更新，并在 [docs/design/README.md](./README.md) 同步状态。

---

## 15. 关联文档

| 文档 | 关系 |
|------|------|
| [DESIGN.md](../../DESIGN.md) | Token、动效上限、组件规范 |
| [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) | 已完成的前序 Phase |
| [.cursor/skills/lab-solver-ui/SKILL.md](../../.cursor/skills/lab-solver-ui/SKILL.md) | 实施时 Agent 读取 |
| GSAP 插件 skills | 仅 Pack D 可选参考 |
