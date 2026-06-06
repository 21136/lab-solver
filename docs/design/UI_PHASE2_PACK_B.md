# Pack B — Step 2 计划确认 · 实施记录

**版本**: 2026-06-06  
**状态**: ✅ 已实施（2026-06-06）  
**父文档**: [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) §6  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**前置**: [Pack A](./UI_PHASE2_PACK_A.md) ✅

---

## 0. 目标（一句话）

Step 2 首屏可扫读：**实验名 hero** + **分节卡片** + **sticky 生成/执行底栏**；题目列表与高级选项默认收折。

---

## 1. 变更摘要

| 区域 | Before | After |
|------|--------|-------|
| 检测信息 | `.detect-info-card` 多行 KV | `.detect-hero`：大标题 `#detectTitle` + meta（课程·专业） |
| PDF 提示 | `.detect-row#pdfExportHint` | `.detect-hero-badge.pdf` in `#detectHeroBadges` |
| 题目列表 | `#questionsList` 直接展示 | `<details id="step2QuestionsPanel">` 默认折叠 |
| 全局配置 | 与分节行平铺 | `.section-global-card` 包裹语言/勾选/总体要求 |
| 分节行 | `.section-row` 浅底 | `.section-row.section-card` + `.section-status-badge` |
| 操作按钮 | 普通底栏 | `#sectionsActionBar.sections-action-bar` **sticky** |
| 内容宽度 | 全宽拉伸 | `#guidedModeContent.parse-result` **max-width 960px** 居中（原 Pack D §8.4 提前落地） |

---

## 2. DOM 结构（After）

```html
#step-2
└── #guidedModeContent.parse-result
    ├── .section-header
    ├── #detectInfoCard.detect-hero
    │   ├── .detect-hero-main → #detectTitle, #detectCourse, #detectMajor
    │   ├── #detectHeroBadges → #pdfExportHint, .layout-badge
    │   └── #pdfPairDocxBar
    ├── #step2QuestionsPanel.step2-questions-panel (details)
    │   └── #questionsList
    ├── #sectionsWorkbench
    │   ├── .section-global-card
    │   ├── #sectionsRowsList → .section-row.section-card × N
    │   └── #step2AdvancedPanel (details)
    ├── #agentStaleBanner
    ├── #sectionsActionBar.sections-action-bar (sticky)
    └── #agentPlanPanel
```

**未改 id**：`detectCourse` / `detectTitle` / `detectMajor` / `pdfExportHint` / `questionsList` 等，`app.js` 写入逻辑保持兼容。

---

## 3. 落地文件

| 文件 | 变更 |
|------|------|
| `index.html` | detect-hero、questions details、section-global-card、sectionsActionBar |
| `styles.css` | `.detect-hero`、`.step2-questions-panel`、`.section-card`、`.section-status-badge`、sticky `.sections-action-bar`、`.parse-result` max-width |
| `app.js` | `sectionStatusBadgeHtml`、`refreshSectionStatusBadge`、`updateQuestionsPanelSummary`；`renderLayoutBadge` → `#detectHeroBadges`；分节行 HTML 卡片化 |

**未触碰**：`#deliverable-workspace`、`.deliverable-grid`、`renderDeliverableWorkspace()`。

---

## 4. JS 新增 / 调整

```javascript
sectionStatusBadgeClass(sec, chars)   // skip | preserve | user | parsed | pending
sectionStatusBadgeLabel(sec, chars)
sectionStatusBadgeHtml(sec, chars)
refreshSectionStatusBadge(row, sec, chars)
updateQuestionsPanelSummary(questions)  // summary: 「检测到 N 道题目」/「实验报告（1 份）」
```

- `renderQuestions()` 末尾调用 `updateQuestionsPanelSummary`
- 分节 `mode` 变更时 `refreshSectionStatusBadge`
- `updatePdfExportHint`：`pdfExportHint` 显示为 `inline-flex`

---

## 5. 验收清单

### 5.1 布局与视觉

- [x] 进入 Step 2 首屏可见实验名 hero，课程/专业在 meta 行
- [x] 分节行间卡片分隔，hover 与 Step 3 nav 项同级 token
- [x] 状态 badge：待填写 / 约 N 字 / 不填 / 保留原文 / 用我的内容
- [x] 1920px 宽屏 Step 2 内容区 max-width 960px

### 5.2 交互

- [x] 题目列表默认折叠，summary 随解析更新
- [x] 生成计划 / 执行计划 sticky，长列表滚动时可点
- [x] 高级选项默认关闭，打开后功能与 Phase 1 一致
- [x] Primary 仍为「执行计划」；「生成计划」为 secondary

### 5.3 回归

- [x] plan 生成、execute、toolbox 模式切换
- [x] PDF 配对 Word、layout badge、sectionsDetectCard
- [x] Step 3 三栏无改动

---

## 6. 未做（留待后续）

| 项 | 说明 |
|----|------|
| 模式 segmented control | 规划为可选；当前保留 `<select class="section-row-mode">` + pill 样式 |
| Pack D §8.4 max-width | 已在 P2-B 完成 |
| Pack D 步骤条 / 侧栏 active | 仍在 P2-D |

---

## 7. 新对话起手（Pack D）

Pack C 见 [UI_PHASE2_PACK_C.md](./UI_PHASE2_PACK_C.md)。

```
按 docs/design/UI_PHASE2_NON_STEP3.md §8 实施 Pack D（历史卡片 + 壳层统一）。
不要改 Step 3。P2-A/B/C 见 UI_PHASE2_PACK_*.md。
```
