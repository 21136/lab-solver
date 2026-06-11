# Pack A — Step 1 左右分栏 · 实施清单

**版本**: 2026-06-06（Step1 粘贴优先补丁 2026-06-08）  
**状态**: ✅ 已实施（2026-06-06；粘贴默认标签 2026-06-08）  
**父文档**: [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) §5  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**预估**: 0.5～1 天（纯前端）

---

## 0. 目标（一句话）

宽屏（≥960px）下 **上传 hero 与文档清单同一行可见**；范文 / 拆分移出首屏；全页常态仅 **1 个** primary「解析并继续」。

**2026-06-08 增补**：左栏 `#uploadArea` 增加 `upload-mode-tab`，默认 **「粘贴题目」** 内联文本框（无需文件）；「上传文件」保留原拖拽/role chips 流程。见 `DESIGN.md` §7 P1、`V1_BUGFIX_LOG.md` BF43。后端配套：**BF44** 修复仅粘贴题目时 `/api/parse-report` 在 `fill_target=null` 下崩溃。

---

## 1. 现状 DOM（Before）

```html
#step-1.step-content
├── .step1-layout                    ← flex column，四块纵向堆叠
│   ├── #uploadArea.upload-area
│   ├── #documentListPanel.document-list-panel
│   │   ├── .panel-header
│   │   ├── .document-table-wrap
│   │   └── .document-list-actions → #parseDocumentsBtn.btn-primary
│   ├── #splitPreviewPanel.split-preview-panel   [display:none]
│   └── #templateUploadPanel.template-upload-panel
└── .demo-hint
```

**现有问题**

| 问题 | 位置 |
|------|------|
| 四块纵向堆叠，首屏需滚动 | `.step1-layout { flex-direction: column }` |
| 表格固定 `max-height: 280px`，右栏无法撑满 | `.document-table-wrap` |
| 空状态文案写「上方区域」 | `#documentListEmpty` hint |
| 拆分态可能出现 **2 个** primary（解析 + 确认拆分） | `#parseDocumentsBtn` + `#splitConfirmBtn` |

---

## 2. 目标 DOM（After）

```html
#step-1.step-content
├── .step1-layout                    ← 外层：flex column，占满 #step-1 高度
│   ├── .step1-grid                  ← NEW：宽屏双栏 grid
│   │   ├── #uploadArea.upload-area
│   │   └── #documentListPanel.document-list-panel
│   │       ├── .panel-header
│   │       ├── #docSummaryBar       ← JS 动态插入，位置不变
│   │       ├── .document-table-wrap
│   │       └── .document-list-actions  ← sticky 底栏
│   │           └── #parseDocumentsBtn.btn-primary
│   ├── .step1-secondary             ← NEW：全宽次要区
│   │   ├── <details.step1-fold-panel id="step1TemplateFold">  ← 范文默认折叠
│   │   │   └── #templateUploadPanel（内层，去掉重复 border 时可加 .step1-fold-body）
│   │   └── #splitPreviewPanel       ← 仍由 JS display 控制；有 combined 时显示
│   └── .demo-hint                   ← 移入 .step1-layout 末尾（仍在 grid 下方）
```

**不改 id / 不改事件**：所有 `getElementById` 选择器保持可用。

---

## 3. 实施顺序（推荐）

```
① index.html   结构调整（§4）
② styles.css   布局 + 响应式（§5）
③ app.js       文案 + primary 互斥（§6，约 15 行）
④ 手动冒烟      §8
```

---

## 4. `index.html` 变更（逐步）

### 4.1 包裹 `.step1-grid`

在 `.step1-layout` 内，用 `.step1-grid` **仅包裹** `#uploadArea` 与 `#documentListPanel`：

```html
<div class="step1-layout">
  <div class="step1-grid">
    <!-- upload-area：原样保留，id/事件/onclick 不动 -->
    <!-- document-list-panel：原样保留 -->
  </div>
  <!-- step1-secondary：见 4.2 -->
  <!-- demo-hint：见 4.3 -->
</div>
```

### 4.2 新建 `.step1-secondary`

将 `#splitPreviewPanel` 与 `#templateUploadPanel` **移出** grid，放入：

```html
<div class="step1-secondary">
  <details class="step1-fold-panel" id="step1TemplateFold">
    <summary class="step1-fold-summary">
      <span class="icon icon-sm" data-icon="file-pen"></span>
      <span class="step1-fold-title">答题模版 / 范文（可选）</span>
      <span class="form-hint step1-fold-hint">仅供参考，以当前报告为准</span>
    </summary>
    <div class="step1-fold-body">
      <!-- 原 #templateUploadPanel 整块移入此处 -->
      <!-- 删除 template 内重复的 <div class="panel-header"> 或仅保留 body 内容 -->
    </div>
  </details>

  <div class="split-preview-panel" id="splitPreviewPanel" style="display:none">
    <!-- 原 split 内容不变 -->
  </div>
</div>
```

**范文 panel 去重 header（二选一）**

| 方案 | 做法 |
|------|------|
| **A（推荐）** | `<details>` 的 `summary` 作标题；`#templateUploadPanel` 内 **删除** `.panel-header`，保留 `template-upload-actions` 及以下 |
| B | 保留 panel-header，summary 只写「展开/收起」 |

### 4.3 `.demo-hint` 位置

从 `#step-1` 直接子级 **移入** `.step1-layout` 末尾（在 `.step1-secondary` 之后）：

```html
<div class="demo-hint">…</div>
```

### 4.4 空状态文案

`#documentListEmpty` 内 hint 改为宽屏友好（可用同一文案兼顾窄屏）：

```diff
- 拖拽文件到上方区域，或点击添加
+ 拖拽文件到左侧上传区，或点击添加
```

窄屏单列时「左侧」略怪 → **改由 JS 按视口切换**（§6.1），HTML 默认写中性文案：

```
拖拽文件到上传区，或点击「+ 添加」
```

---

## 5. `styles.css` 变更

### 5.1 修改 `.step1-layout`（替换原规则）

```css
.step1-layout {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
```

保持不变；确保 `#step-1.active` 为 flex 子项时能撑开（已有 `.step-content.active { display: flex }`）。

### 5.2 新增 `.step1-grid`

```css
.step1-grid {
  display: grid;
  grid-template-columns: 5fr 7fr;
  gap: var(--space-4);
  align-items: stretch;
  min-height: 320px;
}

@media (max-width: 959px) {
  .step1-grid {
    grid-template-columns: 1fr;
    min-height: 0;
  }
}
```

> 断点 **959px** 与父文档一致；项目内 `split-preview-columns` 用 720px，不冲突。

### 5.3 左栏 `#uploadArea`

```css
.step1-grid .upload-area {
  min-height: 320px;
  height: 100%;
  align-self: stretch;
}

/* 可选 Phase 2.1：有文档时次要态 */
.step1-grid .upload-area.has-documents {
  min-height: 240px;
  padding: var(--space-4);
}

.step1-grid .upload-area.has-documents .upload-drop-inner h2 {
  font-size: 15px;
}
```

### 5.4 右栏 `#documentListPanel`

```css
.step1-grid .document-list-panel {
  display: flex;
  flex-direction: column;
  min-height: 320px;
  min-width: 0; /* grid 子项防溢出 */
  padding: 0;   /* header/table/actions 分区 padding */
}

.step1-grid .document-list-panel .panel-header {
  flex-shrink: 0;
  margin-bottom: 0;
  padding: var(--space-4) var(--space-4) var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
}

.step1-grid .document-table-wrap {
  flex: 1;
  min-height: 120px;
  max-height: none;      /* 覆盖原 280px */
  overflow: auto;
  border: none;
  border-radius: 0;
  margin: 0 var(--space-4);
}

.step1-grid .doc-summary-bar {
  flex-shrink: 0;
  margin: var(--space-3) var(--space-4) 0;
}

.step1-grid .document-list-actions {
  flex-shrink: 0;
  position: sticky;
  bottom: 0;
  margin-top: auto;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-card);
  z-index: 2;
}
```

### 5.5 新增 `.step1-secondary` + 折叠面板

**复用** `.step2-advanced-panel` 视觉语言，抽共享 class 或复制规则：

```css
.step1-secondary {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  flex-shrink: 0;
}

/* 与 .step2-advanced-panel 同构 */
.step1-fold-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-secondary);
  overflow: hidden;
}

.step1-fold-summary {
  /* 复制 .step2-advanced-summary 规则，或合并为 .fold-panel-summary */
}

.step1-fold-body {
  padding: var(--space-4);
  border-top: 1px solid var(--border-subtle);
}

/* 范文内层 panel 在 fold 内时去掉双重边框 */
.step1-fold-body .template-upload-panel {
  background: transparent;
  border: none;
  padding: 0;
}

/* 拆分预览：全宽，有数据时自然撑开 */
.step1-secondary .split-preview-panel {
  /* 保持现有 card 样式 */
}
```

**实现提示**：若不想复制 CSS，可把 `.step2-advanced-summary` 等改为共享 class `.fold-panel` / `.fold-summary`，Step 1 与 Step 2 共用。

### 5.6 `.demo-hint`

```css
.step1-layout > .demo-hint {
  margin-top: 0;
  flex-shrink: 0;
}
```

### 5.7 不动

- `#deliverable-workspace`、`.deliverable-grid` 及 Step 3 相关规则
- `.upload-area` 的 hover / dragover 动效
- `.document-table` 行样式、role chip

---

## 6. `app.js` 变更（最小）

### 6.1 空状态文案（`renderDocumentList`）

```javascript
const emptyHint = document.querySelector('#documentListEmpty .empty-state-hint');
if (emptyHint) {
  const narrow = window.matchMedia('(max-width: 959px)').matches;
  emptyHint.textContent = narrow
    ? '拖拽文件到上传区，或点击「+ 添加」'
    : '拖拽文件到左侧上传区，或点击「+ 添加」';
}
```

可选：`matchMedia('change')` 监听 resize 时刷新（非必须，下次 `renderDocumentList` 会更新）。

### 6.2 Primary 互斥（拆分态）

在 `renderSplitPreview` 末尾、`hideSplitPreview` 内：

```javascript
function setStep1PrimaryMode(mode) {
  // mode: 'parse' | 'split' | 'idle'
  const parseBtn = document.getElementById('parseDocumentsBtn');
  const parseActions = document.querySelector('.document-list-actions');
  const splitBtn = document.getElementById('splitConfirmBtn');
  if (parseActions) {
    parseActions.style.display = mode === 'split' ? 'none' : '';
  }
  if (splitBtn && mode !== 'split') {
    splitBtn.style.display = 'none';
  }
}

// renderSplitPreview 显示 panel 后：
setStep1PrimaryMode('split');

// hideSplitPreview：
setStep1PrimaryMode('idle');

// confirmSplitAndContinue 跳转前：
setStep1PrimaryMode('idle');
```

保证：**同一时刻仅 1 个可见 primary**（解析 或 确认拆分）。

### 6.3 可选：`has-documents` 次要态（**本 Pack 可跳过**）

在 `renderDocumentList` 末尾：

```javascript
const uploadArea = document.getElementById('uploadArea');
if (uploadArea) {
  uploadArea.classList.toggle('has-documents', uploadedDocuments.length > 0);
}
```

### 6.4 不必改

| 函数 | 原因 |
|------|------|
| `renderDocumentList` 行渲染 | DOM 结构不变 |
| `renderDocumentSummaryBar` | 仍插入 `tableWrap.before(bar)` |
| `parseAllDocuments` | 逻辑不变 |
| 拖拽 `handleDragOver/Drop` | 仍绑在 `#uploadArea` |

### 6.5 可选：拆分面板自动滚入视口

`renderSplitPreview` 显示后：

```javascript
document.getElementById('splitPreviewPanel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
```

尊重 `prefers-reduced-motion` 时用 `behavior: 'auto'`。

---

## 7. Primary CTA 规则（硬性）

| 状态 | 可见 Primary | 位置 |
|------|-------------|------|
| 无文档 | 无（disabled） | 右栏底栏 |
| 有文档，未解析 | **解析并继续** | 右栏 sticky 底栏 |
| 已解析，非 combined | **解析并继续**（可重新解析） | 同上 |
| combined 待确认 | **确认拆分并进入计划** | `#splitPreviewPanel` 内；**隐藏** `.document-list-actions` |
| 范文 fold 内 | 仅 `btn-secondary`（确认采用格式） | 非 primary |

左栏 `#uploadArea` 内按钮保持 **secondary / ghost**。

---

## 8. 验收清单

### 8.1 布局

- [x] 宽屏 ≥960px：上传区与文档清单 **同一行**，无需滚动即可看到表头
- [x] 右栏表格区域随窗口增高 **flex 伸展**，底栏 sticky 贴 panel 底
- [x] 窄屏 &lt;960px：**单列**，顺序 上传 → 清单 → 折叠区 → demo-hint
- [x] 无横向滚动条（1280 / 960 / 720 三档）

### 8.2 交互

- [x] 拖拽、多文件添加、角色 select、移除文档正常
- [x] 「解析并继续」仅一处；disabled 态与文档数联动
- [x] combined 文档：拆分面板全宽出现；仅「确认拆分」为 primary
- [x] 粘贴题目、加载演示、范文上传/确认流程不回归
- [x] `docSummaryBar` 解析后仍出现在表格上方

### 8.3 视觉

- [x] 右栏 `document-list-panel` 与 Step 3 面板同级：`--bg-card` + border + radius
- [x] 范文默认 **折叠**，不占用首屏高度
- [x] `prefers-reduced-motion` 下步骤进入动画仍正常

### 8.4 回归 Step 3

- [x] 完整流程：demo → 解析 → Step 2 → 执行 → Step 3 三栏正常
- [x] 未改动 `#deliverable-workspace` / `renderDeliverableWorkspace`

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| grid 子项高度不一致 | `align-items: stretch` + 右栏 `display:flex; flex-direction:column` |
| sticky 底栏被父级 `overflow` 裁切 | `.step1-layout` 滚动，sticky 相对 `.document-list-panel`（panel 不设 overflow:hidden） |
| 范文 fold 内 `renderTemplateSummary` 显示 card | 可选：有 pending 时 `step1TemplateFold.open = true`（后续小改） |
| 双 primary | §6.2 `setStep1PrimaryMode` |

---

## 10. 完成后文档更新

| 文件 | 更新 |
|------|------|
| [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) | Pack A 行 → ✅ |
| [docs/design/README.md](./README.md) | P2-A → ✅ |
| [DESIGN.md](../../DESIGN.md) §7 / §11 | 增补「Step 1 双栏布局」条目 |

以上已于 2026-06-06 同步。Pack B 见 [UI_PHASE2_PACK_B.md](./UI_PHASE2_PACK_B.md)。

---

## 11. 新对话起手（Pack A 专用）

```
按 docs/design/UI_PHASE2_PACK_A.md 实施 Step 1 左右分栏。
不要改 Step 3。先改 index.html 结构，再 styles.css，最后 app.js §6。
做完跑 §8 验收清单。
```
