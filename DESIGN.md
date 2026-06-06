# 解题能手 — 设计规范（DESIGN.md）

**版本**: 2026-06-06  
**状态**: Phase 1 ✅ · **Phase 2 ✅**（P2-A～D 均已完成，见 [UI_PHASE2_NON_STEP3.md](docs/design/UI_PHASE2_NON_STEP3.md)）  
**技术栈**: Electron · 纯 HTML/CSS/JS · `src/renderer/`  
**关联 mockup**: [docs/design/](docs/design/)

---

## 1. 产品气质

> **学术生产力工具**，不是 landing page，也不是 3D 炫技 demo。

- 用户长时间阅读/复制实验报告文字 → **可读性优先**
- 主操作是「复制本节」「下载 Markdown/docx」→ **CTA 清晰、可发现**
- V5 定位：生成答案包，用户自行落笔 → **答案工作区是主舞台**

**参考气质**: Notion、Linear、Obsidian（深色生产力），而非 SaaS 营销页。

---

## 2. 动效与密度（Taste Skill 参数）

| 参数 | 值 | 含义 |
|------|-----|------|
| `MOTION_INTENSITY` | **3 / 10** | 适中：hover、步骤切换、tab 过渡；**禁止** scroll 磁吸、视差、全屏动画 |
| `VISUAL_DENSITY` | Step2 **6** · Step3 **4** | 配置页可稍密；答案工作区留白更多 |
| `DESIGN_VARIANCE` | **3 / 10** | 布局稳定、对称；不做 asymmetric 实验布局 |

### 允许的动效

- 按钮 hover：`background` + `transform: translateY(-1px)`，150–200ms
- 按钮 active：`scale(0.98)` 或 `translateY(1px)`
- 步骤条：完成态颜色填充过渡 300ms
- Tab 切换：opacity + translateY(4px) fade，200ms
- 上传区 drag-over：边框 accent 光晕 + 轻微 scale(1.01)
- Toast：slide-in 从右下，250ms
- 进度条：width 过渡，ease-out

### 禁止的动效

- Three.js / WebGL 全屏背景
- 粒子、旋转 3D 模型、视差滚动
- 无限循环 distracting 动画
- `top/left/width/height` 动画（用 `transform` + `opacity`）

### 无障碍

- 尊重 `prefers-reduced-motion: reduce` → 动效时长归零或禁用

---

## 3. 色彩（OKLCH 友好 · 深色默认）

基于现有 token 微调，保持 GitHub-dark 血统，略增层次：

```css
:root {
  /* 背景层级 */
  --bg-primary:   #0f1117;   /* 页面底 */
  --bg-secondary: #161b22;   /* 侧栏、标题栏 */
  --bg-card:      #1c2128;   /* 卡片 */
  --bg-elevated:  #21262d;   /* hover、输入框 */
  --bg-active:    #262c36;

  /* 边框 */
  --border:       #30363d;
  --border-subtle:#21262d;

  /* 强调色 — 单一 accent（P3-E1 偏靛），禁止多色渐变 */
  --accent:       #6b9fff;
  --accent-hover: #8ab4ff;
  --accent-dim:   #2a4a7a;
  --accent-muted: color-mix(in oklch, var(--accent) 15%, transparent);

  /* 语义色 */
  --green:        #3fb950;
  --green-dim:    #1a4a2a;
  --red:          #f85149;
  --yellow:       #e3b341;
  --purple:       #bc8cff;

  /* 文字 */
  --text-primary:   #e6edf3;
  --text-secondary: #8b949e;
  --text-muted:     #484f58;

  /* 圆角 */
  --radius-sm:  6px;
  --radius:     8px;
  --radius-lg:  12px;
  --radius-xl:  16px;

  /* 阴影 — 带色相，非纯黑 */
  --shadow-sm:  0 1px 2px rgba(0, 0, 0, 0.24);
  --shadow:     0 8px 24px rgba(0, 0, 0, 0.4);
  --shadow-accent: 0 4px 14px rgba(107, 159, 255, 0.15);

  /* 间距 — 8pt 网格 */
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  24px;
  --space-6:  32px;
  --space-8:  48px;

  /* 动效 */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-fast: 150ms;
  --duration-normal: 200ms;
  --duration-slow: 300ms;

  /* 字体 */
  --font-sans: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif;
  --font-mono: 'Cascadia Code', 'Consolas', 'Microsoft YaHei UI', monospace;
}
```

**对比度**: 正文 ≥ 4.5:1，UI 控件 ≥ 3:1（WCAG 2.1 AA）。

---

## 4. 字体层级

| 用途 | 大小 | 字重 | 行高 |
|------|------|------|------|
| 页面标题 | 20px | 600 | 1.3 |
| 区块标题 | 14–16px | 600 | 1.4 |
| 正文 | 14px | 400 | 1.6 |
| 辅助说明 | 12px | 400 | 1.5 |
| 标签/chip | 11–12px | 500 | 1.2 |
| 代码 | 13px mono | 400 | 1.5 |

- 报告正文区 `max-width: 72ch`，便于长文阅读
- 数字、校验码用 `--font-mono` + `tabular-nums`

---

## 5. 图标

- **逐步替换 emoji**（🏠📋⚙️）为 inline SVG（Lucide 风格，24×24，stroke 1.5）
- 保留语义：主页 / 历史 / 设置 / 上传 / 复制 / 下载
- 图标颜色：`currentColor`，active 态 `--accent`

---

## 6. 组件规范

### 按钮

| 变体 | 用途 |
|------|------|
| `btn-primary` | 主操作：解析并继续、执行计划、复制本节 |
| `btn-secondary` | 次要：下载、返回 |
| `btn-ghost` |  tertiary：取消、折叠 |
| `btn-run` | 运行代码（绿色，保留） |

- 最小点击区域 36×36px（桌面）
- Primary 最多每屏 1 个视觉焦点

### 卡片

- 背景 `--bg-card`，边框 `1px solid var(--border)`
- 内边距 `--space-4`（配置）或 `--space-5`（工作区）
- hover（可点击卡片）：`border-color: var(--accent-muted)`

### 验证徽章

| 状态 | 样式 |
|------|------|
| 已验证 | 绿色 pill + ✓ |
| 未验证 / skipped | 灰色 pill |
| 验证失败 | 红色 pill |

### 步骤条（✅ UI-4：3 步）

- **上传报告** → **计划确认** → **答案与导出**（原 Step4 导出卡片并入 Step3 底部）
- 完成：绿色填充 + 连线变绿；当前：accent 填充；待办：边框 only
- 切换步骤：`stepEnter` 淡入（200ms，`prefers-reduced-motion` 归零）

---

## 7. 页面优先级与布局方向

### P0 — Step 3 答案工作区（✅ UI-2 已落地）

**三栏布局**（方案 4：左节导航 C + 中正文 A + 右预览 A）：

```
┌──────────────────────────────────────────────────────────────┐
│ 答案工作区                    [回到主页]（完成后） [← 返回]   │
├──────────────────────────────────────────────────────────────┤
│ [已验证] 说明文字              [Markdown][docx][zip…]（次要）  │
├──────────┬─────────────────────────────┬─────────────────────┤
│ 报告结构 │  本节标题      [复制本节]★  │ 代码 │ 图表  [收起]  │
│ ──────── │  ─────────────────────────  │ ─────────────────── │
│ 步骤/分析│  报告正文（max 72ch）       │  代码块 / UML 缩略图 │
│ 结果说明 │                             │                     │
│ 总结     │                             │                     │
├──────────┴─────────────────────────────┴─────────────────────┤
│ 校验清单（折叠） · 修订选项（折叠）                              │
├──────────────────────────────────────────────────────────────┤
│ 提示文案 · [回到主页] · 高级填表（折叠，实验性）                 │
└──────────────────────────────────────────────────────────────┘
  └─ 思考过程侧栏（可折叠，默认收）

**完成后导航**（2026-06-06）：Agent 执行结束（`agentRunFinished`）后显示「回到主页」（`#step3HomeBtn`、`#exportActionHomeBtn`），调用 `startNew()` 重置任务并回到 Step 1。填表成功路径仍在 `#exportSuccessPanel` 保留「处理新报告」（同等行为）。执行中仅显示「取消执行」与「← 返回 Step 2」。

窄屏（<1200px）：右预览栏默认隐藏，「预览」按钮展开浮层；Esc / 遮罩关闭。
```

### P1 — Step 1 上传（Phase 1 ✅ · Phase 2 P2-A ✅）

- Phase 1：拖拽区加大、role chip、文档表格、主 CTA 在清单栏
- **P2-A**（2026-06-06）：`.step1-grid` 宽屏 `5fr 7fr` 双栏 — 左 `#uploadArea` hero · 右 `#documentListPanel`（flex + sticky「解析并继续」）；范文 `<details id="step1TemplateFold">` 默认折叠；拆分预览在 `.step1-secondary` 全宽；`setStep1PrimaryMode` 避免拆分态双 primary。详见 [UI_PHASE2_PACK_A.md](docs/design/UI_PHASE2_PACK_A.md)
- 窄屏 &lt;960px：`.step1-grid` 恢复单列

### P2 — Step 2 计划确认（Phase 1 ✅ · Phase 2 P2-B ✅）

- Phase 1：高级选项 `<details>` 折叠；默认语言+分节行
- **P2-B**（2026-06-06）：`.detect-hero` 摘要条 · `#step2QuestionsPanel` 折叠 · `.section-global-card` · `.section-row.section-card` + status badge · `.sections-action-bar` sticky；`#guidedModeContent` `max-width: 960px`

### P3 — 设置 / 历史 / 壳层（Phase 2 ✅）

- **P2-C**（2026-06-06）：`.settings-layout` 左 nav + 右 pane；`.run-mode-card`；`switchSettingsPane()` — [UI_PHASE2_PACK_C.md](docs/design/UI_PHASE2_PACK_C.md)
- **P2-D**（2026-06-06）：`.history-card` 两行 + 打开/删除；侧栏 `active::before` accent 条；步骤条 `bg-secondary` — [UI_PHASE2_PACK_D.md](docs/design/UI_PHASE2_PACK_D.md)

---

## 8. Mockup 选型（✅ 已确认 2026-06-06）

| 文件 | 风格 | 优点 | 缺点 |
|------|------|------|------|
| `variant-a-split.png` | 左右分栏 | 符合 V5 文档；读写并行 | 窄屏需折叠右栏 |
| `variant-b-cards.png` | 卡片堆叠 | 移动端友好；层次清晰 | 代码预览弱 |
| `variant-c-dashboard.png` | 三栏 dashboard | 节导航强；信息密度高 | 略复杂 |

**已选**: **方案 4 — A + C 混合** → Step3「左节导航（C）+ 中正文（A）+ 右预览（A）」三栏；思考过程侧栏可折叠。

---

## 9. 文件与 Skill 引用

| 路径 | 用途 |
|------|------|
| `src/renderer/styles.css` | 主样式（UI-1：`:root` token、按钮/表单、图标样式） |
| `src/renderer/icons.js` | Lucide 风格 inline SVG；`data-icon` 与 `Icons.iconHtml()` |
| `src/renderer/index.html` | 结构（UI-2：`#deliverable-workspace` 三栏） |
| `src/renderer/app.js` | 动态 UI 通过 `ico()` / `Icons.*` 渲染图标 |
| `.cursor/skills/lab-solver-ui/` | 项目 UI Skill，改 renderer 时自动读 DESIGN.md |
| `.cursor/skills/redesign-existing-projects/` | 改现有 UI 审计清单 |
| `.cursor/skills/effective-ui-design/` | 无障碍 / 间距 / 配色 |
| `.cursor/skills/ui-design-brain/` | 组件最佳实践 |

---

## 10. 实施顺序（UI-1 → UI-4）

1. **UI-1** ✅ token 统一 + SVG 图标 + 按钮/输入状态（2026-06-06）
   - `:root` 与 §3 对齐（含 `--bg-elevated`、`--accent-muted`、`--space-*`、动效 token）
   - 新增 `icons.js`；`index.html` / `app.js` 装饰性 emoji 已换为 SVG
   - 按钮 hover/active/focus-visible；表单 focus 光晕；`prefers-reduced-motion`
   - 标题栏窗口控件 `─ □ ✕` 保留（系统 chrome，非装饰 emoji）
2. **UI-2** ✅ Step3 三栏布局（2026-06-06）
   - `#deliverable-workspace`：左 `deliverable-nav` · 中 `deliverable-section-body` · 右 `deliverable-preview-col`
   - 主操作「复制本节」居中栏；导出按钮降为 toolbar 次要
   - 窄屏右栏可折叠（`preview-open` + backdrop）
3. **UI-3** ✅ Step1 上传 + Step2 高级折叠（2026-06-06）
   - Step1：`upload-area` 加大、role chip 色点 pill、`document-table` 三列清单
   - Step1：每屏 primary 仅「解析并继续」；上传区按钮降为 secondary/ghost
   - Step2：`step2-advanced-panel` 折叠约束 / 输出方式 / 工具箱模式切换
   - Step2：默认仅 `sections-essential-bar`（语言 + 勾选）+ 分节行
4. **UI-4** ✅ 步骤简化 + 空状态 + 动效（2026-06-06）
   - 步骤条 4→3；`#exportSuccessPanel` 并入 Step3（填表成功后内联展示，无独立 Step4）
   - 空状态统一：`empty-state-illustration` 圆形容器 + 标题 + 提示；`emptyStateHtml()` 复用
   - 动效：步骤圈/连线过渡、Toast 滑出、导出成功卡片 `visible` 淡入、进度条 width token 化
5. **P2-A** ✅ Step1 双栏布局（2026-06-06，属 Phase 2，见 §11）
   - `.step1-grid`：宽屏左上传 hero、右文档清单 + sticky「解析并继续」
   - `.step1-secondary`：范文 `<details>` 默认折叠；拆分预览全宽
   - `setStep1PrimaryMode`：combined 拆分态仅保留一个 primary
6. **P2-B** ✅ Step2 产品化（2026-06-06，属 Phase 2，见 §11）
   - `.detect-hero`：实验名 + 课程/专业 meta；PDF badge 在 `.detect-hero-badges`
   - `#step2QuestionsPanel`：题目列表默认折叠
   - `.section-row.section-card` + `.section-status-badge`；`.sections-action-bar` sticky
7. **P2-C** ✅ 设置左 nav + 模式卡片（2026-06-06，属 Phase 2，见 §11）
   - `.settings-layout`：`200px` 左 nav + 右 `.settings-pane`（默认解题模式）
   - `.run-mode-card`：标准 / 深度 / ReAct 卡片选择；radio 视觉隐藏
   - `switchSettingsPane()`；窄屏 nav 横向 chip
8. **P2-D** ✅ 历史卡片 + 壳层统一（2026-06-06，属 Phase 2，见 §11）
   - `.history-card`：标题/时间 + 节数摘要 + 打开·删除
   - `.nav-item.active::before` 3px accent 左条
   - `.step-circle` 待办态 `bg-secondary`；当前步 `shadow-accent`

**每阶段**: 只改 CSS/HTML 结构（及必要的前端 `app.js` 步骤逻辑），不动 agent 后端。

---

## 11. UI Phase 2 — 非 Step 3（✅ 已完成）

**用户确认**: Step 3 可定稿，不再改动。  
**完整 spec**: [docs/design/UI_PHASE2_NON_STEP3.md](docs/design/UI_PHASE2_NON_STEP3.md)

| Pack | 范围 | 状态 |
|------|------|------|
| P2-A | Step 1 左右分栏（`.step1-grid` / `.step1-secondary`） | ✅ 2026-06-06 |
| P2-B | Step 2 hero + 分节卡 + sticky 底栏 | ✅ 2026-06-06 |
| P2-C | 设置左 nav + 模式卡片 | ✅ 2026-06-06 |
| P2-D | 历史卡片 + 侧栏/步骤条统一 | ✅ 2026-06-06 |

**P2-A 落地文件**: `index.html`（`#step-1`）、`styles.css`（`.step1-grid` 等）、`app.js`（`setStep1PrimaryMode`）— [清单](docs/design/UI_PHASE2_PACK_A.md)

**P2-B 落地文件**: `index.html`（`#step-2` hero/questions/global-card）、`styles.css`（`.detect-hero`、`.section-card`、sticky bar）、`app.js`（`sectionStatusBadge*`、`updateQuestionsPanelSummary`）— [记录](docs/design/UI_PHASE2_PACK_B.md)

**P2-C 落地文件**: `index.html`（`#tab-settings` layout/panes）、`styles.css`（`.settings-nav`、`.run-mode-card`）、`app.js`（`switchSettingsPane`、`syncRunModeUI`）— [记录](docs/design/UI_PHASE2_PACK_C.md)

**P2-D 落地文件**: `index.html`（`#historyList`）、`styles.css`（`.history-card`、`.nav-item.active::before`、步骤条）、`app.js`（`renderHistory`、`openHistoryItem`、`deleteHistoryItem`）— [记录](docs/design/UI_PHASE2_PACK_D.md)

---

## 12. UI Phase 3 — 精致化抛光（✅ 2026-06-06 已完成）

**完整 spec**: [docs/design/UI_PHASE3_POLISH.md](docs/design/UI_PHASE3_POLISH.md)

Phase 2 完成后的 UI 复审：不改 Step 3 三栏结构，聚焦复制体验、导出收纳、面板层次、壳层与动效。

**用户决策（2026-06-06）**: 步骤条 **A2**（960px 左对齐）；Pack E 做 **E1 accent + E3 历史**，不做 display 字体与背景纹理。

| Pack | 范围 | 优先级 |
|------|------|--------|
| P3-A | `user-select`、步骤条 A2 对齐 | P0 |
| P3-B | Step 3 elevation + 导出 dropdown | P0 |
| P3-C | 侧栏状态、修订区 primary | P1 |
| P3-D | 节切换 / 思考侧栏动效 | P1 |
| P3-E | Accent 偏靛 + 历史 enrich | P1 |
| P3-F | 内联 style、loading、工具箱 | P2 |

### 12.1 P3-E1 accent（已写入 `:root`）

| Token | Phase 1～2 | Phase 3（当前） |
|-------|------------|-----------------|
| `--accent` | `#58a6ff` | `#6b9fff` |
| `--accent-hover` | `#79b8ff` | `#8ab4ff` |
| `--accent-dim` | `#1f4e8c` | `#2a4a7a` |
| `--shadow-accent` | `rgba(88,166,255,0.15)` | `rgba(107,159,255,0.15)` |
