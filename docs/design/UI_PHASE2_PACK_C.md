# Pack C — 设置页左 nav + 模式卡片 · 实施记录

**版本**: 2026-06-06  
**状态**: ✅ 已实施（2026-06-06）  
**父文档**: [UI_PHASE2_NON_STEP3.md](./UI_PHASE2_NON_STEP3.md) §7  
**设计规范**: [DESIGN.md](../../DESIGN.md)  
**前置**: [Pack A](./UI_PHASE2_PACK_A.md) ✅ · [Pack B](./UI_PHASE2_PACK_B.md) ✅

---

## 0. 目标（一句话）

设置页宽屏 **左 nav + 右 pane** 分栏；三种 Agent 模式以 **可点击卡片** 展示；切换 nav 时仅换右侧内容，避免整页长 scroll。

---

## 1. 变更摘要

| 区域 | Before | After |
|------|--------|-------|
| 布局 | `.settings-container` 单列 `max-width: 600px` | `.settings-layout` grid `200px 1fr` |
| 导航 | 无 | `.settings-nav` + `.settings-nav-item`（5 项） |
| 内容 | 5 张 `.settings-card` 纵向堆叠 | 5 个 `.settings-pane` section，仅 active 可见 |
| 解题模式 | `.run-mode-option` 小行 + 可见 radio | `.run-mode-card` 大卡片 + 隐藏 radio + `.active` 选中态 |
| 窄屏 | 同单列 | nav 改为顶部 **横向 scroll chip**（&lt;768px） |

---

## 2. DOM 结构（After）

```html
#tab-settings
├── .page-header
└── .settings-layout
    ├── nav.settings-nav[role=tablist]
    │   └── button.settings-nav-item × 5  → data-settings-pane
    └── .settings-content
        ├── #settings-pane-runmode.settings-pane.active
        │   └── .settings-card → .run-mode-cards → .run-mode-card × 3
        ├── #settings-pane-ai.settings-pane[hidden]
        ├── #settings-pane-disclaimer.settings-pane[hidden]
        ├── #settings-pane-privacy.settings-pane[hidden]
        └── #settings-pane-about.settings-pane[hidden]
```

**未改 id**：`runModeOptions`、`aiProvider`、`apiKey`、`complianceSettingsCard`、`complianceDisclaimerText` 等；`saveSettings()` / `onRunModeChange()` / compliance 逻辑不变。

---

## 3. 落地文件

| 文件 | 变更 |
|------|------|
| `index.html` | `.settings-layout`、nav、pane sections；`.run-mode-card` 结构 |
| `styles.css` | `.settings-nav*`、`.settings-pane`、`.run-mode-card*`；767px 响应式 |
| `app.js` | `switchSettingsPane()`；`syncRunModeUI()` 同步卡片 `.active`；`init()` 默认 pane |

**未触碰**：`#deliverable-workspace`、`.deliverable-grid`、`renderDeliverableWorkspace()`。

---

## 4. JS 新增

```javascript
let _activeSettingsPane = 'settings-pane-runmode';

function switchSettingsPane(paneId) {
  // nav .active + aria-selected；pane .active + hidden
}

// syncRunModeUI：radio checked + .run-mode-card.active
// onRunModeChange：先 syncRunModeUI 再 persist
// init()：switchSettingsPane(_activeSettingsPane)
```

---

## 5. 验收清单

### 5.1 布局与视觉

- [x] 宽屏内容区 `max-width: 720px`，不再限制 600px 整页宽
- [x] 左 nav sticky；选中态与 `.deliverable-nav-item.active` 同级 token
- [x] 三种模式为网格卡片，选中 accent 边框 + 背景
- [x] 窄屏 nav 横向 chip 可滚动

### 5.2 交互

- [x] 切换 nav 仅显示对应 pane，无整页 scroll 跳变
- [x] 模式卡片点击切换 radio，`onRunModeChange` / localStorage 正常
- [x] API Key、保存、测试连接、合规弹窗不回归
- [x] Tab 可聚焦 nav 项与模式卡片（`focus-within`）

### 5.3 回归

- [x] `loadSettings()` / `syncRunModeUI()` 恢复已存 runMode
- [x] Step 3 三栏无改动

---

## 6. Phase 2 收尾

Pack D 见 [UI_PHASE2_PACK_D.md](./UI_PHASE2_PACK_D.md)。Phase 2 非 Step 3 改造已全部完成。
