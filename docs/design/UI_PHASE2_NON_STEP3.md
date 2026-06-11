# UI Phase 2 — 非 Step 3 界面改造

**版本**: 2026-06-06  
**状态**: ✅ Phase 2 完成（**P2-A/B/C/D** 均已落地）  
**前置**: [UI Phase 1](./README.md) 已完成（token、图标、Step3 三栏）  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**用户反馈**: Step 3 可接受；设置 / 历史 / 壳层仍与 Step 3 精致度有差距（Step 1/2 已于 P2-A/B 落地）。

---

## 1. 目标与边界

### 1.1 目标

将 **Step 1、Step 2、设置、历史、全局壳层** 的视觉与交互层级，提升到与 **Step 3 答案工作区** 同一产品线水准——主要靠 **布局重构 + 面板层次**，而非再换一轮图标。

### 1.2 明确不做

| 不做 | 原因 |
|------|------|
| **改 Step 3**（`#deliverable-workspace`、三栏 grid、复制/预览逻辑） | 用户已满意 |
| 引入 React / Tailwind / 新 UI 框架 | 维持 vanilla 栈 |
| 改 agent / Python 后端 API | 纯前端改造 |
| 3D / WebGL / 重动效 | 见 DESIGN.md §2 |

### 1.3 成功标准（整体）

- 打开软件 → Step 1 首屏不再像「纵向表单堆叠」（**P2-A ✅**）
- Step 2 默认视图可扫读：课程摘要 + 分节卡片 + 底栏主操作（**P2-B ✅**）
- 设置页宽屏不空、窄项有分组导航（**P2-C ✅**）
- 侧栏 / 步骤条 / 卡片风格与 Step 3 内面板 **同一套 elevation 语言**（**P2-D ✅**）
- 所有改动可仅用 CSS + HTML 结构微调 + 少量 `app.js` DOM 渲染适配

---

## 2. 现状 vs 目标（差距摘要）

| 区域 | Phase 1 做了什么 | 用户仍不满意的原因 | Phase 2 要做什么 |
|------|------------------|-------------------|------------------|
| **Step 1** | 上传区加大、role chip、文档表格 | ~~4 块纵向堆叠~~ → **P2-A 已改** | ✅ **左右分栏** + 次要面板折叠（[清单](./UI_PHASE2_PACK_A.md)） |
| **Step 2** | 高级选项 `<details>` 折叠 | ~~plain KV / 表单感~~ → **P2-B 已改** | ✅ **摘要 hero** + **分节卡片** + **sticky 底栏** |
| **设置** | 图标 + 表单 focus 态 | `max-width: 600px` 窄栏；长 scroll；radio 朴素 | **左 nav + 右内容**；模式 **卡片选择** |
| **历史** | 空状态插画 | 几乎无设计；有数据后预期仍是列表 | **记录卡片** + 操作按钮 |
| **侧栏 / 标题栏** | SVG 图标 | 72px 图标栏过简；与 Step 3 面板不统一 | 略加强 active 态 / 可选 hover 展开 |
| **步骤条** | 4→3 步 | 视觉仍偏旧，与 Step 3 卡片未统一 | 与 `--bg-secondary` 面板风格对齐 |

---

## 3. 设计原则（继承 Phase 1）

- **Token**：仅用 [DESIGN.md §3](../../DESIGN.md) 已有 CSS 变量，不新增随机色
- **动效**：`MOTION_INTENSITY = 3`（hover、折叠、步骤切换；无 scroll 特效）
- **密度**：Step 1 **5** · Step 2 **6** · 设置 **5** · 历史 **4**
- **组件复用**：优先复用 Step 3 已有 class 模式：
  - `deliverable-nav-item` 风格 → 设置模式卡片、历史条目
  - `panel-header` + `bg-secondary` 内面板 → Step 1 右栏、Step 2 分节卡
- **Primary 按钮**：每屏可见区域最多 **1 个**视觉主 CTA

---

## 4. Pack 划分与优先级

```
Pack A  Step 1 左右分栏          ★★★  ✅ 已完成
Pack B  Step 2 产品化            ★★★  ✅ 已完成
Pack C  设置页左 nav             ★★  ✅ 已完成
Pack D  历史 + 壳层统一          ★   ✅ 已完成
```

建议实施顺序：**A → B → C → D**（可独立 PR / 独立对话）

---

## 5. Pack A — Step 1 上传（首屏）✅

> **实施清单**: [UI_PHASE2_PACK_A.md](./UI_PHASE2_PACK_A.md)（**已实施 2026-06-06**）

### 5.1 布局线框

**宽屏（≥ 960px）**

```
┌─────────────────────────────────────────────────────────────────┐
│ 步骤条：① 上传报告  ─  ② 计划确认  ─  ③ 答案与导出                  │
├──────────────────────────────┬──────────────────────────────────┤
│  UPLOAD HERO（左 ~42%）       │  DOCUMENT LIST（右 ~58%）         │
│  ┌────────────────────────┐  │  ┌────────────────────────────┐  │
│  │ [粘贴题目★][上传文件]    │  │  │ 文档清单    [粘贴] [+添加] │  │
│  │  默认：内联文本框粘贴    │  │  ├────────────────────────────┤  │
│  │  无需文件即可解析        │  │  │ 文件名 │ 角色 │ 操作      │  │
│  │  上传模式：doc/pdf+chips │  │  │ ...    │ ...  │ ...       │  │
│  └────────────────────────┘  │  ├────────────────────────────┤  │
│                              │  │         [ 解析并继续 ★ ]    │  │
│                              │  └────────────────────────────┘  │
├──────────────────────────────┴──────────────────────────────────┤
│  ▼ 可选：答题模版 / 范文（`<details>` 默认关闭）                  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ 条件显示：合体文档拆分预览（有 combined 时才展开）              │
├─────────────────────────────────────────────────────────────────┤
│  💡 没有报告？[加载演示文档]                                      │
└─────────────────────────────────────────────────────────────────┘
```

**窄屏（< 960px）**：恢复 **单列**，顺序为 上传 hero → 文档清单 → 折叠区（与现逻辑一致）

### 5.2 HTML 结构变更（`index.html`）

| 变更 | 说明 |
|------|------|
| 新增 `.step1-grid` | 包裹 upload-area + document-list-panel，`grid-template-columns: 5fr 7fr` |
| `upload-area` | 左栏固定 min-height，去掉与右栏重复的「解析并继续」 |
| `document-list-panel` | 右栏 `display: flex; flex-direction: column`，表格 `flex:1` 滚动 |
| `document-list-actions` | sticky 底栏，仅保留 **btn-primary 解析并继续** |
| `template-upload-panel` | 移出 grid，放到 `.step1-secondary` 折叠区 |
| `split-preview-panel` | 同上；`display:none` 逻辑保留，展开时占满宽 |

### 5.3 CSS 新增（`styles.css`）

```css
.step1-grid { display: grid; grid-template-columns: 5fr 7fr; gap: var(--space-4); ... }
.step1-secondary { display: flex; flex-direction: column; gap: var(--space-3); }
.document-list-panel { min-height: 320px; }
.document-table-wrap { flex: 1; overflow: auto; }
.document-list-actions { sticky bottom; border-top; padding-top; background }
@media (max-width: 959px) { .step1-grid { grid-template-columns: 1fr; } }
```

### 5.4 JS 影响（`app.js`）

- **最小**：文档行渲染、拖拽逻辑不变
- 可选：右栏有文档时 upload-area 视觉降为「继续添加」次要态（class `has-documents`）

### 5.5 验收

- [x] 宽屏下上传与清单 **同一行**可见，无需滚动即可看到表格
- [x] 全页仅 **1 个** primary「解析并继续」（拆分态由 `setStep1PrimaryMode` 切换）
- [x] 范文 / 拆分默认不占首屏高度
- [x] 窄屏单列无横向滚动
- [x] 不回归：多文档、角色选择、拆分、演示加载

---

## 6. Pack B — Step 2 计划确认 ✅

> **实施记录**: [UI_PHASE2_PACK_B.md](./UI_PHASE2_PACK_B.md)（**已实施 2026-06-06**）

### 6.1 布局线框

```
┌─────────────────────────────────────────────────────────────────┐
│ 检测到的报告内容                              [← 重新上传]        │
├─────────────────────────────────────────────────────────────────┤
│  DETECT HERO（摘要条，横向）                                      │
│  课程：Java程序设计  ·  实验：设计模式  ·  专业：软件工程  [PDF提示] │
├─────────────────────────────────────────────────────────────────┤
│  ▼ 检测到的题目列表（默认折叠，有内容时可展开）                    │
├─────────────────────────────────────────────────────────────────┤
│  分节设置                                                         │
│  ┌─ 全局 ─────────────────────────────────────────────────────┐ │
│  │ 编程语言 [Python ▼]  ☑源码  ☐UML                           │ │
│  │ 老师总体要求 [textarea…………]  [智能解析]                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌─ 第三节 · 实验步骤 ──────────────────── [模式 pill] ────────┐ │
│  │ textarea / 智能解析 / 状态标签                               │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌─ 第四节 · 实验结果 ────────────────────────────────────────┐ │
│  └────────────────────────────────────────────────────────────┘ │
│  …                                                               │
├─────────────────────────────────────────────────────────────────┤
│  ▼ 高级选项（已有 step2-advanced-panel，视觉与 Step3 折叠一致）   │
├─────────────────────────────────────────────────────────────────┤
│  STICKY ACTION BAR                                               │
│              [ 生成计划 ]    [ 执行计划 ★ ]                       │
├─────────────────────────────────────────────────────────────────┤
│  执行计划预览（agent-plan-panel，生成后出现）                     │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 检测 Hero（`detect-info-card` 升级）

**现状**：多行 `.detect-row` 键值对  
**目标**：单行 / 两行 **摘要条**，大字号实验名 + 小字课程/专业

```html
<div class="detect-hero" id="detectInfoCard">
  <div class="detect-hero-main">
    <h4 class="detect-hero-title" id="detectTitle">—</h4>
    <p class="detect-hero-meta">
      <span id="detectCourse">—</span>
      <span class="detect-hero-sep">·</span>
      <span id="detectMajor">—</span>
    </p>
  </div>
  <div class="detect-hero-badges"><!-- PDF 提示等 --></div>
</div>
```

- 保留现有 element id，`app.js` 写入逻辑 **不变**或仅改选择器容器

### 6.3 分节行卡片化（`.section-row`）

| 现状 | 目标 |
|------|------|
| 浅底 + 小 padding | `--bg-secondary` 全宽卡片，header 行：节名 + 模式 pill |
| 模式为原生 `<select>` | 可选：改为 **segmented control**（CSS only，value 仍进 select hidden） |
| 状态文字 muted | 右侧 badge：已解析 / 待填写 / preserve 黄标 |

复用 Step 3 `.deliverable-nav-item` 的 border / active / hover token。

### 6.4 Sticky 底栏（`.sections-action-bar`）

- `position: sticky; bottom: 0; z-index: 10`
- 背景 `--bg-primary` + 顶边框 + 轻微 shadow
- 「执行计划」为 primary；「生成计划」secondary
- `agent-plan-panel` 在底栏 **上方**滚动，不被遮挡

### 6.5 题目列表折叠

- `#questionsList` 外包 `<details class="step2-questions-panel">`
- summary：`检测到 N 道题目`（JS 解析后更新文案）

### 6.6 JS 影响

| 文件 | 变更 |
|------|------|
| `app.js` | `renderSectionRows()` 输出结构调整（card header）；questionsList summary 计数 |
| `app.js` | detect 填充逻辑可不变（同 id） |

### 6.7 验收

- [x] 进入 Step 2 首屏可见 **实验名摘要**，不必滚动找课程信息
- [x] 分节行间有明显卡片分隔，风格接近 Step 3 左 nav 项
- [x] 生成/执行按钮 **sticky**，长分节列表滚动时始终可点
- [x] 高级选项默认关闭；打开后功能与 Phase 1 一致
- [x] 不回归：plan 生成、execute、toolbox 切换

---

## 7. Pack C — 设置页 ✅

> **实施记录**: [UI_PHASE2_PACK_C.md](./UI_PHASE2_PACK_C.md)（**已实施 2026-06-06**）

### 7.1 布局线框

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚙ 设置                                                           │
├──────────────┬──────────────────────────────────────────────────┤
│ 解题模式      │  ┌─ 解题模式 ─────────────────────────────────┐ │
│ AI 配置       │  │  (card) 标准 / 深度 / ReAct 三选一卡片        │ │
│ 免责声明      │  └────────────────────────────────────────────┘ │
│ 隐私说明      │                                                  │
│ 关于          │  （切换 nav 时只换右侧内容，无整页 scroll）       │
└──────────────┴──────────────────────────────────────────────────┘
```

### 7.2 结构变更

| 变更 | 说明 |
|------|------|
| `.settings-layout` | `grid: 200px 1fr`，左 `.settings-nav`，右 `.settings-pane` |
| 每个 `.settings-card` | 拆成独立 `.settings-pane` section，`id="settings-pane-runmode"` 等 |
| 左 nav | 按钮列表，`.active` 同 sidebar nav 风格 |
| `run-mode-option` | 改为 `.run-mode-card`：大卡片 + 标题 + hint + radio 隐藏 |

### 7.3 JS

- 新增 `switchSettingsPane(paneId)`：切换 nav active + pane visibility
- `saveSettings()` / 各 `onXxxChange()` **不变**
- 首次进入默认 pane：解题模式

### 7.4 窄屏

- `< 768px`：settings-nav 改为顶部的 **横向 scroll chip**，pane 全宽

### 7.5 验收

- [x] 宽屏设置内容区利用宽度（`max-width` 提升至 ~720px 或全宽）
- [x] 三种 Agent 模式以 **可点击卡片** 展示，选中态与 nav-item.active 一致
- [x] API Key、保存、测试连接功能不变
- [x] 不回归：safeStorage、compliance 弹窗
- [x] 首次免责：须先勾选「我已阅读并理解上述条款」再点「我已阅读并同意」（BF54 修复勾选区 `is-hidden` 显示）

---

## 8. Pack D — 历史 + 壳层 ✅

> **实施记录**: [UI_PHASE2_PACK_D.md](./UI_PHASE2_PACK_D.md)（**已实施 2026-06-06**）

### 8.1 历史记录卡片

**单条结构**：

```
┌─────────────────────────────────────────────────────────────┐
│ Java程序设计 · 设计模式实验                    2026-06-06 14:30 │
│ 3 节已生成 · 已验证                              [打开] [删除] │
└─────────────────────────────────────────────────────────────┘
```

- class：`.history-card`（hover border accent-muted）
- 空状态：沿用 Phase 1 `empty-state-illustration`
- 数据：读现有 localStorage / history API（若有）；无数据时仅样式预备

### 8.2 侧栏（可选增强）

| 方案 | 说明 | 推荐 |
|------|------|------|
| D1 保持 72px | 仅加强 active 左侧 accent 条 | ✅ 默认 |
| D2 展开 160px | 常显图标+文字 | 可选，Phase 2 不做除非用户要求 |

- D1：`.nav-item.active::before { 3px accent 左边条 }`

### 8.3 步骤条统一

- `.step-circle` / `.step-line` 背景与 Step 3 内面板一致
- 当前步：轻微 `box-shadow: var(--shadow-accent)`

### 8.4 内容区 max-width（Step 2 专用）

- ~~`#step-2 .parse-result { max-width: 960px; margin: 0 auto; }`~~ → **已在 P2-B 落地**（`.parse-result` on `#guidedModeContent`）
- Pack D 仅剩步骤条 / 侧栏 polish 时无需重复此项

### 8.5 验收

- [x] 历史页空状态与 Step 1 空状态视觉统一
- [x] 侧栏 active 态与 Step 3 nav-item 一致
- [x] Step 2 在 1920px 宽屏可读宽度受限（P2-B ✅）

---

## 9. 文件 touch 清单

| Pack | index.html | styles.css | app.js | 后端 | 状态 |
|------|------------|------------|--------|------|------|
| A | step1 grid 结构 | `.step1-grid` 等 | `setStep1PrimaryMode` 等 | — | ✅ |
| B | detect hero、sticky bar | section-card、detect-hero | badge/summary helpers | — | ✅ |
| C | settings layout | settings-nav、run-mode-card | switchSettingsPane | — | ✅ |
| D | history 卡片模板 | history-card、nav active | history 渲染 | — | ✅ |

**禁止修改**（除非 bug）：

- `#deliverable-workspace` 及子元素结构
- `.deliverable-grid` 三栏 CSS
- `renderDeliverableWorkspace()` 核心逻辑

---

## 10. 实施计划与工时

| 阶段 | 内容 | 预估 | 依赖 | 状态 |
|------|------|------|------|------|
| **P2-A** | Step 1 左右分栏 | 1～1.5 天 | — | ✅ |
| **P2-B** | Step 2 hero + 分节卡 + sticky | 2～2.5 天 | — | ✅ |
| **P2-C** | 设置左 nav + 模式卡片 | 1 天 | — | ✅ |
| **P2-D** | 历史 + 壳层 | 0.5～1 天 | — | ✅ |
| **合计** | | **4.5～6 天** | A/B 可并行不同人 | |

### 建议 PR / 对话拆分

1. ~~`ui/p2-step1-layout`~~ ✅
2. ~~`ui/p2-step2-polish`~~ ✅
3. ~~`ui/p2-settings`~~ ✅ Pack C
4. ~~`ui/p2-history-shell`~~ ✅ Pack D

---

## 11. 测试清单（每 Pack）

### 手动冒烟

- [ ] 三步流程走通：上传 demo → 计划 → 执行 → Step 3 正常（**回归 Step 3**）
- [ ] 窗口宽度 1280 / 960 / 720 三档无破版
- [ ] 键盘：Tab 可聚焦 nav、settings nav、sticky 按钮
- [ ] `prefers-reduced-motion` 无异常动画

### 自动化

- 现有 `tests/test_*` 不涉及 renderer DOM 的可不增
- 可选：后续加 Playwright 截图对比（**不在 Phase 2 范围**）

---

## 12. 可选：补充 Mockup

Phase 1 仅有 Step 3 mockup。Phase 2 可在实施前生成：

| 文件 | 内容 |
|------|------|
| `mockup-step1-split.png` | 左上传 + 右清单 |
| `mockup-step2-config.png` | hero + 分节卡 + sticky 底栏 |
| `mockup-settings-nav.png` | 设置左 nav |

生成后放入 `docs/design/`，本文件 §5～§7 线框仍以 **HTML 可实施性** 为准。

---

## 13. 文档维护

| 事件 | 更新 |
|------|------|
| Pack 开工 | 本文件对应 § 标「🚧 进行中」 |
| Pack 完成 | 新增/更新 `UI_PHASE2_PACK_*.md`；[DESIGN.md](../../DESIGN.md) §7/§10/§11；[README.md](./README.md) 进度表 |
| Step 3 相关 bug | 在 PR 中明确「非本意改动」并回滚 |

---

## 14. 新对话起手 Prompt（复制用）

**Phase 2 已完成** — 后续仅 Step 3 bugfix 或新功能需求。
