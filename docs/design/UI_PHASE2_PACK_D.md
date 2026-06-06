# Pack D — 历史卡片 + 壳层统一 · 实施记录

**版本**: 2026-06-06  
**状态**: ✅ 已实施（2026-06-06）  
**父文档**: [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) §8  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**前置**: Pack A/B/C ✅

---

## 0. 目标（一句话）

历史页记录改为 **产品级卡片**（标题/时间/摘要 + 打开·删除）；侧栏 active **左侧 accent 条**；步骤条圆圈/连线与 Step 3 面板 **同一套 elevation**。

---

## 1. 变更摘要

| 区域 | Before | After |
|------|--------|-------|
| 历史条目 | `.question-card.history-card` 整卡点击 | `.history-card` 两行布局 + `[打开]` `[删除]` |
| 历史空状态 | HTML 静态占位 | `renderHistory()` + `emptyStateHtml()`（与 Step 1 同组件） |
| 侧栏 active | `accent-dim` 背景 only | `accent-muted` + **3px 左条** `::before` |
| 步骤圈（待办） | `bg-primary` + 2px currentColor | `bg-secondary` + `1px border` |
| 步骤连线 | `var(--border)` | `var(--border-subtle)` |
| 当前步 | 已有 `shadow-accent` | 保留 |

---

## 2. 历史卡片 DOM

```html
<article class="history-card" data-history-index="0">
  <div class="history-card-header">
    <h3 class="history-card-title">课程 · 实验名</h3>
    <time class="history-card-date">2026/6/6 14:30</time>
  </div>
  <div class="history-card-footer">
    <p class="history-card-meta">
      <span>3 节已生成 · 已导出</span>
      <span class="history-tag mode-standard">标准模式</span>
    </p>
    <div class="history-card-actions">
      <button class="btn-secondary btn-sm">打开</button>
      <button class="btn-ghost btn-sm">删除</button>
    </div>
  </div>
</article>
```

标题来自 `historyCardTitle()`（`document_roles[].course` + 文件名）；时间优先 `exported_at`。

---

## 3. 落地文件

| 文件 | 变更 |
|------|------|
| `index.html` | `#historyList` 空容器（由 JS 渲染） |
| `styles.css` | `.history-card*`、`.nav-item.active::before`、`.step-circle`/`.step-line` |
| `app.js` | `formatHistoryDate`、`historyCardTitle`、`openHistoryItem`、`deleteHistoryItem`；`renderHistory` 重写 |

**未触碰**：`#deliverable-workspace`、`.deliverable-grid`、`renderDeliverableWorkspace()`。

---

## 4. 验收清单

- [x] 历史空状态与 Step 1 共用 `empty-state-illustration`
- [x] 历史卡片 hover `border-color: accent-muted`
- [x] 打开调用 `electronAPI.openFileExternal`；删除更新 localStorage
- [x] 侧栏 active 左侧 accent 条 + `accent-muted` 背景
- [x] 步骤条待办态 `bg-secondary`；当前步 `shadow-accent`
- [x] Step 3 无改动

---

## 5. Phase 2 收尾

Pack A～D 全部完成；后续仅为 Step 3 bugfix 或新功能，不再改非 Step 3 壳层除非用户要求。
