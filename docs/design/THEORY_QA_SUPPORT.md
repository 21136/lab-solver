# 简答题支持（Theory Q&A）设计文档

> 状态：已实现（2026-06-11）  
> 创建：2026-06-11  
> 关联：`docs/features/CODE_CLOZE_QUESTIONS.md`（同级题型）

---

## 背景

项目已支持：
- `lab_report` — 实验报告（主路径）
- `code_cloze` — 代码完形填空
- `mixed_assignment` — 混排卷（简答 + 填空）

**缺口**：纯简答题卷（软工期末复习题、理论问答等）没有独立路径：  
- 解析器默认判成 `lab_report`，不会识别多道简答
- `THEORY_USER` prompt 要求输出代码，不适合纯文字问答
- `build_deliverable` 把 `solve_theory` 结果放进实验报告四段结构，答案字段为空
- Step3 展示四个空 Tab，用户看到空白

本文档描述最小改动方案（Option B），让纯简答题走通 Step1→Step2→Step3 全流程。

---

## 改动范围（4 处）

### 1. Prompt — `src/python/agent/prompts.py`

**问题**：当前 `THEORY_USER` 只有一行，要求「给出完整代码+思路」，对纯文字简答完全不适用。

**方案**：新增 `SHORT_ANSWER_USER` 模板，要求 LLM 逐题作答，输出 Markdown 格式：

```
请你作为软件工程助教，逐题解答下面的简答题。

【题目全文】
{full_text}

要求：
- 每题单独一段，格式：**第N题** 或 **题目标题**，然后换行写答案
- 答案用中文，简洁但完整，每题 3-8 句
- 纯文字输出，不需要代码，不需要 JSON
- 不要重复题目原文
```

同时注册到 `PROMPTS` 字典，版本 `v1`。

旧 `THEORY_USER` 保留（混排卷的 `theory` 段仍在用），不删除。

---

### 2. 题型识别 — `src/python/agent/parse_documents.py` + `src/python/agent/planner.py`

**问题**：解析器遇到纯文字题目默认返回 `lab_report`。

**方案**：在 `_classify_question_type`（或对应识别函数）中，增加「纯简答」检测：

**检测规则**（按优先级，若已命中 `code_cloze` / `mixed_assignment` 则跳过）：

| 条件 | 权重 |
|------|------|
| 存在 `一、二、三` 或 `1. 2. 3.` 编号，且每段均无代码块 | +3 |
| 全文无 `代码`/`程序`/`实验步骤`/`运行结果` 等实验报告关键词 | +2 |
| 文档来源为粘贴文字（非 docx 上传）| +1 |
| 总字数 < 800 字 且段数 ≥ 3 | +1 |

得分 ≥ 4 → `question_type = "short_answer"`

**Planner** 中 `apply_question_type_overrides` 增加 `short_answer` 分支：
```python
if question_type == "short_answer":
    steps = [PlanStep(module="solve_short_answer", ...)]
```

`registry.py` 注册 `solve_short_answer`（alias → `solve_theory`，但 prompt_key = `"short_answer"`）。

---

### 3. Deliverable — `src/python/modules/deliverable.py`

**问题**：`build_deliverable` 对 `solve_theory` 的结果尝试读 `steps_analysis/result_description/summary`，而 `theory` prompt 返回的是 `answer` 字段，导致三节均为空。

**方案**：在 `build_deliverable` 函数内，`is_code_cloze` 判断后，增加 `is_short_answer` 分支：

```python
is_short_answer = solve_type in ("theory", "short_answer")

if is_short_answer:
    sections = {
        "answer": solve.get("answer") or parsed.get("answer") or "",
        "notes": parsed.get("notes") or solve.get("notes") or "",
    }
    dlv["type"] = "theory"
    dlv["sections"] = sections
    # 隐藏代码/图表/验证 Tab（简答题不需要）
    dlv["code"] = {"files": [], "language": "", "main_file": ""}
    dlv["diagrams"] = []
    dlv["execution"] = {"validation_status": "not_requested", "validation_note": "简答题无需代码验证"}
    return dlv
```

同时 `_get_solve_data` 优先级不变（`solve_short_answer` 结果存在 `module_results["solve_theory"]`）。

---

### 4. 前端布局与 GSAP 动效 — `app.js` + `styles.css` + `theory-motion.js`

**问题**：`renderDeliverableWorkspace` 没有 `type === "theory"` 分支；且实验报告三栏（nav | 正文 | 代码预览）对简答题是错位的——右侧预览栏永远空，左侧「步骤/结果/总结」也不适用。

**设计原则**（对齐 `DESIGN.md` + `UI_PHASE3_POLISH.md` Pack D）：

| 原则 | 简答题落地 |
|------|-----------|
| 中间亮、两侧暗 | 正文 hero 占满可用宽度，预览栏收起 |
| 复制优先 | 整卷复制 + 单题复制 |
| `MOTION_INTENSITY = 3` | 仅 3 处 GSAP：工作区入场、题卡 stagger、Tab 切换 |
| `prefers-reduced-motion` | `gsap.matchMedia()` 降级为即时切换 |
| 禁止 scroll 特效 | 不用 ScrollTrigger / 视差 |

---

#### 4.1 布局：阅读型双栏（非实验报告三栏）

简答题进入 Step3 时，给 `#deliverableGrid` 加修饰类 `deliverable-grid--theory`，从三栏变为 **题目导航 + 阅读主栏**：

```
┌─────────────────────────────────────────────────────────────┐
│  [未请求验证]  简答题 · 共 N 题          [复制全部] [导出 ▾] │
├──────────────┬──────────────────────────────────────────────┤
│ 题目导航     │  第 2 题 · 瀑布模型的优缺点                  │
│ ───────────  │  ──────────────────────────────────────────  │
│ ✓ 第1题      │                                              │
│ ● 第2题 ←    │  瀑布模型是一种线性、阶段性的软件开发模型…    │
│   第3题      │                                              │
│   第4题      │                          [复制本题]          │
│              │                                              │
│ ───────────  │  （备注 Tab 有内容时显示第二 nav 项）        │
│   备注       │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

**DOM**：复用现有 `#deliverableGrid` 子节点，不新增顶层 HTML 壳。

| 区域 | 实验报告 | 简答题 (`--theory`) |
|------|---------|---------------------|
| 左栏 `#deliverableTabs` | 步骤/结果/总结 | **题目列表**（从答案文本解析） |
| 中栏 `#deliverableSectionBody` | 单节正文 | **当前题卡片** 或备注全文 |
| 右栏 `#deliverablePreviewCol` | 代码/图表 | **隐藏**（`display: none` 或 `grid-column` 不占位） |
| 工具栏 badge | 验证状态 | 文案改为「简答题 · 共 N 题」 |

**CSS**（`styles.css`）：

```css
.deliverable-grid--theory {
  grid-template-columns: 200px minmax(0, 1fr);
}
.deliverable-grid--theory .deliverable-preview-col {
  display: none;
}
.deliverable-grid--theory .deliverable-content-col {
  /* 阅读区更宽，沿用 P3-B hero elevation */
  max-width: 72ch;          /* 正文行宽，居中于列内 */
  margin-inline: auto;
}
.theory-qa-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}
.theory-qa-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: var(--space-2);
}
.theory-qa-body {
  white-space: pre-wrap;
  line-height: 1.7;
  color: var(--text-secondary);
  user-select: text;
}
.theory-qa-actions {
  display: flex;
  justify-content: flex-end;
}
```

窄屏（`≤767px`）沿用现有 deliverable 响应式：左栏变横向滚动 chip，不额外引入 GSAP 布局逻辑。

---

#### 4.2 答案解析 → 题目卡片

LLM 输出约定为 `**第N题**` 或 `**题目标题**` 分段。前端 `parseTheoryAnswerBlocks(text)` 切分为：

```js
// [{ id: '1', title: '什么是软件工程？', body: '软件工程是…' }, …]
```

规则（按优先级）：

1. 按行匹配 `/^\*\*(第?\d+题[^*]*|[^*]+)\*\*/` 开新块
2. fallback：按 `^\d+[.、]\s` 编号切分
3. 切不出块时 → 单块 `{ id: 'all', title: '简答答案', body: fullText }`

左栏 nav 每题一项；点击调用 `switchTheoryQuestion(id)`。

---

#### 4.3 GSAP 动效编排

项目当前 **未安装 GSAP**（`package.json` 无依赖）。简答题工作区作为 **首个 GSAP 接入点**，遵循 Pack D「可选 GSAP、须 matchMedia」约定。

**依赖**：`npm install gsap`（Electron 打包约 +45KB gzip，可接受）。

**新文件** `src/renderer/theory-motion.js`（vanilla，无 React）：

```js
import gsap from 'gsap';

let theoryCtx = null;

export function initTheoryMotion() {
  theoryCtx?.revert();
  theoryCtx = gsap.context(() => {
    gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', () => {
      // 注册 reduced-motion 外的 tween 默认
      gsap.defaults({ duration: 0.2, ease: 'power1.out' });
    });
  });
}

export function animateTheoryWorkspaceEnter(gridEl, cards) {
  theoryCtx?.revert();
  theoryCtx = gsap.context(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return;

    const tl = gsap.timeline({ defaults: { ease: 'power1.out' } });
    // 1) 预览栏淡出（若从实验报告切过来）
    tl.fromTo(gridEl, { gridTemplateColumns: '220px 1fr 320px' },
                  { gridTemplateColumns: '200px 1fr', duration: 0.25 }, 0);
    // 2) 正文区入场
    tl.fromTo('.deliverable-content-col',
      { autoAlpha: 0, y: 6 },
      { autoAlpha: 1, y: 0, duration: 0.2 }, 0.05);
    // 3) 题卡 stagger（仅首次渲染）
    if (cards?.length) {
      tl.from(cards, { autoAlpha: 0, y: 8, stagger: 0.04, duration: 0.18 }, 0.1);
    }
  }, gridEl);
}

export function animateTheoryTabSwitch(bodyEl) {
  if (!bodyEl || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  gsap.fromTo(bodyEl,
    { autoAlpha: 0, y: 4 },
    { autoAlpha: 1, y: 0, duration: 0.18, overwrite: 'auto' });
}

export function killTheoryMotion() {
  theoryCtx?.revert();
  theoryCtx = null;
}
```

**动效触发点**（仅 3 处，不扩散）：

| 时机 | 动画 | 时长 |
|------|------|------|
| 首次 `renderTheoryWorkspace` | 网格收栏 + 正文 fade-in + 题卡 stagger | 200–250ms |
| 切换题目 / 答案↔备注 Tab | 正文区 `autoAlpha` + `y: 4→0` | 180ms |
| 离开 theory 工作区（`startNew` 等） | `killTheoryMotion()` 清理 context | — |

**不用 GSAP 的场景**（保持 CSS `transition`）：nav item hover/active、按钮 hover、复制 Toast。

**降级路径**：若暂不引入 GSAP，用 CSS `.deliverable-section-body.is-entering`（Pack D §8.1 方案 1）实现 Tab 切换淡入；工作区入场和 stagger 省略。文档实现时 **优先 GSAP**，CSS 为 fallback。

---

#### 4.4 `renderTheoryWorkspace` 逻辑

在 `renderDeliverableWorkspace` 的 `isCodeClozeDeliverable` 之后插入：

```js
if (isTheoryDeliverable(dlv)) {
  renderTheoryWorkspace(dlv);
  return;
}
```

核心流程：

1. `grid.classList.add('deliverable-grid--theory')`；隐藏预览栏与验证 badge 无关文案
2. `blocks = parseTheoryAnswerBlocks(dlv.sections.answer)`
3. 渲染左栏题目 nav（+ 可选「备注」项）
4. 渲染中栏当前题 `.theory-qa-card`（标题 + 正文 + 「复制本题」）
5. 工具栏「复制本节」→ 当前题 body；新增「复制全部」→ 完整 `sections.answer`
6. 首次渲染调用 `animateTheoryWorkspaceEnter(grid, cards)`
7. Tab 切换调用 `animateTheoryTabSwitch(body)`

```js
function isTheoryDeliverable(dlv) {
  return dlv?.type === 'theory';
}
```

**与混排卷简答段的关系**：混排卷内 `theory` 段仍走 `renderMixedAssignmentWorkspace` 的纯文本展示（轻量、无题卡拆分）；**仅 `dlv.type === 'theory'` 整卷** 走本布局 + GSAP。

---

#### 4.5 涉及文件（前端）

| 文件 | 改动 |
|------|------|
| `package.json` | 新增 `gsap` 依赖 |
| `src/renderer/theory-motion.js` | GSAP context + 3 个 export |
| `src/renderer/app.js` | `parseTheoryAnswerBlocks`、`renderTheoryWorkspace`、`switchTheoryQuestion` |
| `src/renderer/styles.css` | `--theory` 网格、`.theory-qa-*` 卡片 |
| `src/renderer/index.html` | 可选：工具栏加「复制全部」按钮（或 JS 动态插入） |

---

## 数据流变化

```
Step1 粘贴纯简答题文字
  → parse_documents: question_type = "short_answer"（新检测规则）
  → Planner: [solve_short_answer]（alias → solve_theory + short_answer prompt）
  → executor_solve._run_solve_theory: call_ai(question.type="short_answer") → answer 字段
  → build_deliverable: type="theory", sections={answer, notes}
  → renderTheoryWorkspace: 单栏答案 + 复制按钮
```

上传 docx 的简答题（如期末卷 Word 文档）同样走此路径（识别规则也适用）。

---

## 不改动的部分

| 模块 | 原因 |
|------|------|
| `mixed_assignment` 路径 | 混排卷的简答段走 `solve_theory`，已可用，不动 |
| `fill_report.py` | 简答题暂不支持填回 Word（实验报告专用），不扩展 |
| ReAct 工具 | `solve_short_answer` 暂不注册 ReAct alias（简答题不需要多轮） |
| `verify_answer` / `auto_remediate` | 简答题跳过质量校验（无结构化 schema 可验证） |

---

## 文件改动清单

| 文件 | 类型 | 改动量 |
|------|------|-------|
| `src/python/agent/prompts.py` | 新增 prompt | ~20 行 |
| `src/python/agent/parse_documents.py` | 新增题型检测 | ~25 行 |
| `src/python/agent/planner.py` | 新增 `short_answer` 分支 | ~10 行 |
| `src/python/agent/registry.py` | 注册 `solve_short_answer` | ~5 行 |
| `src/python/agent/executor_solve.py` | `short_answer` prompt 路由 | ~8 行 |
| `src/python/modules/deliverable.py` | `theory` 类型分支 | ~20 行 |
| `package.json` | 新增 `gsap` | 1 依赖 |
| `src/renderer/theory-motion.js` | GSAP 动效模块 | ~60 行 |
| `src/renderer/app.js` | 解析题块 + 工作区渲染 | ~120 行 |
| `src/renderer/styles.css` | `--theory` 布局 + 题卡样式 | ~50 行 |

**总计：约 280 行**（后端 ~90 行不变；前端因阅读型布局 + GSAP 增至 ~230 行）。均为新增分支，不破坏现有路径。

---

## 验收标准

### 功能

1. Step1 粘贴「1. 什么是软件工程？2. 瀑布模型的优缺点？…」→ Step2 计划显示「解答简答题」
2. Step3 进入 **双栏阅读布局**（无右侧代码预览栏），左栏按题号导航
3. 点击左栏题号，中栏显示对应题卡；「复制本题」复制单题，「复制全部」复制整卷
4. 上传含简答题的 docx 同样生效
5. 现有实验报告 / code_cloze / 混排卷测试全部通过（回归）

### 布局与动效

6. `deliverable-grid--theory` 下正文区 `max-width: 72ch`，长文可读性优于实验报告三栏
7. 首次进入工作区：预览栏收起 + 正文 fade-in（`prefers-reduced-motion` 下无动画）
8. 多题时题卡 stagger 入场（≤5 题可见 stagger，>5 题仅首屏 3 张 stagger 避免拖沓）
9. 切换题目 / 备注 Tab：正文 180ms 淡入，无布局跳动（不 animating `width`/`height`）
10. `startNew()` / 切回实验报告 deliverable 时 `killTheoryMotion()` 无残留 tween
