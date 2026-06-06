# V2 工具箱模式 — 设计文档

**用途**：让用户手动选用后端工具模块执行，不依赖 Agent 流水线自动编排。
**状态**：Phase 1-4 全部完成 ✅（2026-06-05）
**依赖**：无（独立功能，不影响现有三档 Agent 模式）

---

## 一、为什么要做

现有三档 Agent（标准/深度/ReAct）都是"自动驾驶"——用户上传文档、点执行、等结果。大多数时候没问题，但：

1. **出问题时无法精准定位** — 某一步失败了只能整体重跑
2. **想调某一步的输出** — 比如 AI 解题结果不满意，只改代码部分，不想重跑整个流程
3. **用户有自己的流程** — 比如先手动写完答案，只想用工具填回 Word
4. **教学/调试场景** — 老师想给学生展示每一步的效果

工具箱是"手动挡"，和 Agent 是互补关系，不是替代。

---

## 二、现有工具清单

后端已实现 9 个独立模块，每个都有明确的输入/输出签名：

| # | 工具 | 模块 | 功能 | 输入 | 输出 |
|---|------|------|------|------|------|
| 1 | 📄 解析文档 | `parse_report` | 提取 docx/pdf 文本、表格、图片结构 | 文档文件 | 全文 + 段落 + tables + 图片列表 |
| 2 | 🧠 AI 解题 | `solve_lab` | LLM 生成结构化实验答案 | 题目文本 + API Key + 设置 | `steps_analysis` / `result_description` / `summary` + code + UML |
| 3 | ▶ 运行代码 | `run_code` | 编译执行代码（Python/Java/C/Node） | 代码 + 语言 | stdout / stderr / exit_code |
| 4 | 📸 截图 | `screenshot` | IDE 风格代码截图 | 代码 + 语言 + 主题 | PNG base64 |
| 5 | 📊 图表渲染 | `uml` + `dfd_render` | PlantUML / 标准 DFD → PNG（最多 12 张） | `diagrams` JSON 数组 / `plantuml_src` / `dfd_json` | PNG base64 + 类型统计 + 预览 |
| 6 | 📝 填写报告 | `fill_report` | 答案 JSON 写入 docx | 答案 JSON + docx + fill_scope | 填写后的 docx |
| 7 | 🔧 修复代码 | `fix_code` | 编译错误自动修代码 | 代码 + 错误文本 + API Key | 修复后代码 + 解释 |
| 8 | ✅ 校验答案 | `quality.verify` | 规则校验 | 答案 JSON | 通过 / 问题列表 |
| 9 | ✏️ 修订答案 | `quality.revise` | LLM 局部/整题重写 | 答案 JSON + 反馈 + API Key | 修订后答案 |

---

## 三、UI 设计

### 3.1 入口

在 **Step 2 顶部** 新增模式切换 Tab：

```
┌─────────────────────────────────────┐
│  [◉ 引导模式]   [○ 工具箱模式]      │
├─────────────────────────────────────┤
│  (引导模式 = 现有分节工作台 UI)      │
│  (工具箱模式 = 新 UI，见下方)        │
└─────────────────────────────────────┘
```

引导模式 = 现有的三个按钮（生成计划 / 执行计划），走 Agent 流水线。
工具箱模式 = 替换操作区为工具面板，用户自由选用。

### 3.2 工具面板布局

```
┌───────────────────────────────────────────────────────────┐
│  工具箱 — 按推荐顺序自上而下操作                             │
│  图表引擎: ✅ PlantUML JAR  ✅ Java  ✅ Graphviz (DFD)      │
├───────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─ 1. 📄 解析文档 ─────────────────────────────────────┐ │
│  │  [已加载: 实验报告.docx]   [重新解析]                 │ │
│  │  状态: ✅ 解析完成 · 3,520 字 · 5 节 · 2 张图        │ │
│  └──────────────────────────────────────────────────────┘ │
│                          ↓ (自动传递: full_text)          │
│  ┌─ 2. 🧠 AI 解题 ─────────────────────────────────────┐ │
│  │  输入: 使用 #1 解析结果 (3,520 字)                    │ │
│  │  [▶ 执行]    状态: ⏸ 未执行                          │ │
│  └──────────────────────────────────────────────────────┘ │
│              ↓ (自动传递: answer_json)                    │
│  ┌─ 3. ▶ 运行代码 ────────────────────────────────────┐ │
│  │  输入: 使用 #2 中的 code                             │ │
│  │  语言: [python ▾]   [▶ 执行]  状态: ⏸ 未执行        │ │
│  └──────────────────────────────────────────────────────┘ │
│                          ↓                                │
│  ┌─ 4. 📸 截图 ───────────────────────────────────────┐ │
│  │  输入: 使用 #2 中的 code                             │ │
│  │  主题: [monokai ▾]  [▶ 截图]  状态: ⏸ 未执行        │ │
│  └──────────────────────────────────────────────────────┘ │
│                          ↓                                │
│  ┌─ 5. 📊 图表渲染 ─────────────────────────────────────┐ │
│  │  输入: 使用 #2 的 diagrams JSON（PlantUML / dfd_json）│ │
│  │  [▶ 渲染]    状态: ⏸ 未执行 · 支持最多 12 张          │ │
│  └──────────────────────────────────────────────────────┘ │
│                          ↓                                │
│  ┌─ 6. 📝 填写报告 ───────────────────────────────────┐ │
│  │  输入: 使用 #2 答案 + #3 截图 + #5 图表               │ │
│  │  目标: 实验报告.docx                                 │ │
│  │  节: [steps: auto] [result: auto] [summary: auto]    │ │
│  │  [▶ 填写]    状态: ⏸ 未执行                          │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ 辅助工具 ───────────────────────────────────────────┐ │
│  │  [🔧 修复代码]  [✏️ 修订答案]  [✅ 校验答案]         │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ 输出 —──────────────────────────────────────────────┐ │
│  │  [📥 下载填写后的报告]  [📋 复制最后输出的 JSON]     │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 3.3 交互规则

1. **数据自动传递** — 上游工具执行成功后，其输出自动成为下游工具的默认输入
2. **任意起点** — 用户可以从任意工具开始。比如直接粘贴代码到 #3 运行，不从 #1 开始
3. **手动覆盖** — 每个工具的输入框可展开编辑。用户可粘贴自己的代码 / PlantUML / `dfd_json` / 完整 `diagrams` 数组
4. **工具间独立** — 上游重新执行不会触发下游自动重跑。下游保留旧结果但标记"⚠️ 输入已更新"
5. **辅助工具回写** — 「修复代码」成功后，修复结果自动写回 `#2` 解题 JSON 的 `code` / `code_files`，并同步到 `#3 运行代码`、`#4 截图` 的输入框；`#3` / `#4` / `#6` 若已有结果则标记 stale，用户需重新执行 `#3` 验证修复是否有效（与 #5「AI 修复」图表后需重渲染同理）
6. **状态持久化** — 切换 Tab 不丢状态；切换文档后全部重置
7. **无依赖序列** — #3 #4 #5 无先后依赖，可并行或单独执行

### 3.4 单工具展开视图（以 AI 解题为例）

```
┌─ 2. 🧠 AI 解题 ─────────────────────────── [展开] [▶ 执行] ┐
│                                                              │
│  输入文本 (来自 #1 解析结果, 3,520 字):                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 实验一 Java多线程程序设计                                 │ │
│  │ 一、实验目的                                             │ │
│  │ 1. 掌握Java中创建线程的两种方式...                        │ │
│  │ ...                                                      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  配置:                                                       │
│  语言:[java ▾]  UML:[开启]  代码:[开启]                     │
│                                                              │
│  输出 (JSON):                                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ { "steps_analysis": "...", "code": "...", ... }          │ │
│  │                               [📋 复制] [✏️ 编辑]       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  状态: ✅ 成功 · 耗时 3.2s · tokens 1,842                    │
└──────────────────────────────────────────────────────────────┘
```

### 3.5 数据流

```
用户文档 (docx/pdf)
    │
    ├──[1. 解析文档]──→ full_text + sections + tables + images
    │                         │
    │                    ┌────┴──────────────────────┐
    │                    ▼                           ▼
    │              [2. AI 解题]              (用户手动编辑)
    │                    │                           │
    │        ┌───────────┼───────────┐               │
    │        ▼           ▼           ▼               │
    │   [3. 运行]  [4. 截图]  [5. 图表渲染]              │
    │        │           │           │               │
    │        └───────────┴───────────┘               │
    │                    │                           │
    │                    ▼                           ▼
    │              [6. 填写报告] ←──────  (用户手动编辑)
    │                    │
    │                    ▼
    │              输出 docx
    │
    └──[可选: 辅助工具 7/8/9 随时调用]──→ 修正中间结果
              │
              │  🔧 修复代码 成功
              ▼
         写回 #2.code ──→ 同步 #3 / #4 输入 ──→ #3/#4/#6 标记 stale
```

---

## 四、实现分步

### Phase 1 — 接口标准化（后端，~30 行）

给 `server.py` 新增 9 条独立 API 路由（或 1 条通用 `/api/tool/<name>` 路由），每个模块暴露为独立端点。

```
POST /api/tool/parse     → parse_report.tool_parse(files)
POST /api/tool/solve     → solve_lab.tool_solve(text, settings)
POST /api/tool/run       → run_code.tool_run(code, lang)
POST /api/tool/screenshot→ screenshot.tool_screenshot(code, lang, theme)
POST /api/tool/uml       → uml.render_uml_diagrams(diagrams | plantuml_src | dfd_json)
POST /api/tool/fill      → fill_report.tool_fill(answer_json, docx_path, fill_scope)
POST /api/tool/fix       → fix_code.tool_fix(code, error, settings)
POST /api/tool/verify    → quality.tool_verify(answer_json)
POST /api/tool/revise    → quality.tool_revise(answer_json, feedback, settings)
```

大部分模块已有对应的函数入口，这里主要是包装成薄路由 + 统一 `{ok, data, error}` 响应格式。

**代码量**：`server.py` +50 行

### Phase 2 — 前端工具面板（~200 行）

1. 新增 `renderToolboxPanel()` — 渲染 9 个工具卡片
2. 新增 `switchToToolboxMode()` / `switchToGuidedMode()` — 模式切换
3. 新增 `toolState` 全局对象 — 存储每个工具的输入/输出/状态
4. 工具状态机：`idle → running → success/failed`
5. 自动数据传递逻辑（上游输出 → 下游默认输入）
6. 工具卡片折叠/展开动画
7. 单工具输出编辑器（Monaco Editor 复用）

**代码量**：`app.js` +200 行，`index.html` +60 行，`styles.css` +80 行

### Phase 3 — 数据传递可视化（~60 行）

1. 上下游连线或箭头渲染
2. "⚠️ 输入已更新"标记
3. 一键执行全部链（#1→#2→#6 自动串联）

**代码量**：`app.js` +60 行

---

## 五、Agent 模式 vs 工具箱模式 对比

| | 引导模式（Agent） | 工具箱模式 |
|---|--|--|
| 适合谁 | 新用户 / 懒得管 | 老用户 / 想掌控 |
| 操作次数 | 2 次（生成计划→执行） | N 次（每个工具点一次） |
| 自由度 | 低：Agent 决定顺序 | 高：用户决定做什么、用什么顺序 |
| 出错处理 | 整体重试或失败 | 精准重做某一步 |
| 中间结果可见 | 否（黑盒） | 是（每步输出可查看/编辑） |
| 代码路径 | agent/ 下 15+ 文件 | 仅 server.py 薄路由 |
| 分节工作台 | 有 | 无（用户在 fill 工具里手动选节） |
| 数据持久化 | 会话内 agentModuleResults | toolState 持久化到 localStorage |

---

## 六、兼容性

- **不影响现有功能** — Agent 模式是默认，工具箱是可选切换
- **不修改 Agent 模块代码** — 工具箱用独立路由包装，不碰 agent/ 内部
- **`/api/solve` 保留不变** — 旧接口继续可用（向后兼容）

---

## 七、不做

- 不在工具箱里重做 Planner/分节工作台（太复杂，这些是 Agent 的核心价值）
- 不支持"拖拽连线"式可视化编排（过度设计，9 个工具的依赖链是线性的）
- **不做智能分节插图** — 图表落点由 Agent 的 `fill_hints.diagrams_target` 负责；工具箱 #5 仅批量渲染 PNG，#6 仍按默认策略写入 docx
- 不替换现有 Step 3（Agent 模式下 Step 3 进度列表保留）

---

## 八、实现记录 (2026-06-05)

### Phase 1 ✅ — 后端 API

`server.py` 新增 9 条独立路由 + `_tool_ok()`/`_tool_err()` 辅助函数。每个路由是薄包装层，调用已有模块函数，统一返回 `{ok, data, error}` 格式。无需修改任何 `agent/` 或 `modules/` 内部代码。

关键细节：
- `/api/tool/parse` — 复用 `build_question_from_document()` + `detect_docx_sections()`
- `/api/tool/fill` — 返回结果的 `file_data`（base64）方便前端直接下载
- `/api/tool/fix` — 复用 `fix_code_from_error()`，支持 category/pattern 参数
- `/api/tool/verify` — 包装 `verify_answer()`，构造最小 `ctx`
- `/api/tool/revise` — 复用 `revise_answer()`，通过 `window.prompt()` 收集用户反馈

### Phase 2 ✅ — 前端

- **`index.html`** — Step 2 顶部模式切换 Tab 栏 + 工具箱面板容器 `#toolboxPanel` + 工具列表 `#toolboxTools` + 输出栏 `#toolboxOutputBar`
- **`app.js`** — `toolState` 全局对象（9 工具 × idle/running/success/failed/stale 状态机）、`renderToolboxPanel()` 动态渲染、`executeTool()` 分支执行、自动数据传递（上游输出 → 下游默认输入）、下游标记 stale、expand/collapse、复制输出、下载填写后报告
- **`styles.css`** — 工具卡片样式（含 5 种状态配色）、模式切换 Tab、展开动画

### Phase 3 ✅ — 数据传递可视化

- **箭头渲染** — `renderToolboxPanel()` 将顺序工具（#1→#2→#3→#4→#5→#6）卡片之间插入 `.tool-arrow` 箭头元素，包含竖线和数据传递标签（如 "自动传递: full_text"）。下游工具为 stale 时箭头同步变黄。
- **stale 标记增强** — `.tool-card.stale` 新增 `stalePulse` 动画（黄色边框脉冲发光），状态文字加粗，箭头连线同步变黄。
- **一键执行链** — 工具箱头部新增「⚡ 一键执行链 (#1→#2→#6)」按钮，依次执行 `parse → solve → fill`，每个等前一个完成再执行下一个，中途失败自动中断。按钮在无文档或链式执行中时禁用。

关键函数：
- `buildToolCardHtml(def, state)` — 单工具卡片 HTML 构建器，顺序工具和辅助工具共用
- `renderToolboxPanel()` — 分离顺序工具组（`.toolbox-seq-group`）和辅助工具行，自动插入箭头
- `updateChainButtonState()` — 控制一键执行按钮的启用/禁用状态
- `runToolChain()` — 异步链式执行器，调用方 `await executeTool()` 等待每个工具完成

### Phase 4 ✅ — 测试覆盖、状态持久化与交互打磨

#### 4.1 后端测试覆盖（`tests/test_toolbox.py`，38 个测试）

11 个测试类覆盖全部 9 条路由 + 3 个辅助函数：

- `TestToolHelpers`（6 tests）— `_tool_ok` / `_tool_err` / `_tool_settings` 参数提取、默认值、camelCase fallback
- `TestToolParse`（4 tests）— 缺参数、非法 base64、旧版 .doc 拒绝、正常解析含 section 检测
- `TestToolSolve`（4 tests）— 缺 text、缺 api_key、成功、异常处理
- `TestToolRun`（4 tests）— 缺 code、preflight 拦截、成功执行、错误执行
- `TestToolScreenshot`（3 tests）— 缺 code、成功截图、output_text 透传
- `TestToolUml`（5 tests）— 模块不可用、缺输入、PlantUML 成功、含错误渲染、**diagrams 数组 + DFD**
- `TestToolFill`（3 tests）— 缺答案、dict→list 归一化验证、无 file_data 填写
- `TestToolFix`（3 tests）— 缺 code、缺 api_key、成功修复
- `TestToolVerify`（3 tests）— 缺答案、通过、不通过含建议
- `TestToolRevise`（4 tests）— 缺答案、缺反馈、缺 api_key、成功修订

Mock 策略：`unittest.mock.patch` 针对 `server.模块名` 路径。docx 测试用 `_make_minimal_docx()` 辅助函数。

#### 4.2 状态持久化到 localStorage

- `saveToolboxState()` — 每次 `executeTool()` 成功后自动序列化 toolState 到 localStorage（key: `toolboxState`）
- `loadToolboxState()` — `switchToToolboxMode()` 时恢复上次会话状态
- `clearToolboxStorage()` — `resetToolboxState()` 和 `startNew()` 时清除
- 文档切换时自动清除旧状态，避免残留

#### 4.3 修订反馈模态框

- 替换 `window.prompt()`（Electron 原生对话框与 UI 不一致）
- 新增 `#reviseFeedbackModal` 模态框（textarea + 取消/提交按钮）
- `showReviseFeedbackModal()` 返回 Promise，resolve 反馈字符串或 null
- 用户取消时工具状态恢复为 idle，不调用 API

#### 4.4 交互打磨

- **重试按钮** — `buildToolCardHtml()` 在 `state.status === 'failed'` 时追加「🔄 重试」按钮
- **重置按钮** — 工具箱头部 `#toolboxResetBtn`，调用 `confirmResetToolbox()`（有结果时 confirm 确认）
- **JSON 校验提示** — verify/revise 工具 textarea 输入非 JSON 时显示黄色 `⚠️ 输入不是有效的 JSON 格式`
- **进度条动画** — 工具 `running` 时渲染 `.tool-card-progress`（CSS 伪元素蓝色光条循环滑动）

#### 4.5 Agent ↔ 工具箱状态同步

- `syncToolboxParseFromAgent()` — 引导模式已解析文档时，自动填充 toolbox parse 工具状态为 success（含 full_text、sections、section_map 等），避免重复解析
- 反向同步：工具箱 parse 执行成功后自动更新 `agentPrimaryFullText`，使 `resolveToolInput('solve')` 无需切换模式也能取到正确值

#### 4.6 辅助工具结果回写（2026-06-06）

| 辅助工具 | 回写行为 |
|----------|----------|
| 🔧 修复代码 | `propagateFixedCodeToToolbox()` — 合并 `code` / `code_files` / `main_file` / `language` 到 `toolState.solve.output`；更新 `toolState.run.input` 与 `toolState.screenshot.input`；`#3` / `#4` / `#6` 在 success 或 failed 时改为 stale |
| 🛠 AI 修复（#5） | `fixDiagramsTool()` — 合并 `answer_json` 到 solve；更新 uml 输入；`markDownstreamStale('solve')` |

修复代码成功后的 Toast：**「修复完成，已同步到「运行代码」— 请重新执行 #3 验证」**。

#### 关键函数（Phase 4 新增）

| 函数 | 用途 |
|------|------|
| `saveToolboxState()` | 序列化 toolState → localStorage |
| `loadToolboxState()` | 从 localStorage 恢复 toolState |
| `clearToolboxStorage()` | 清除 localStorage 中的 toolboxState |
| `syncToolboxParseFromAgent()` | 引导模式解析结果同步到工具箱 |
| `propagateFixedCodeToToolbox()` | 修复代码成功后写回 solve + run + screenshot |
| `showReviseFeedbackModal()` | Promise-based 修订反馈模态框 |
| `confirmResetToolbox()` | 带确认的重置入口 |

### Phase 5 ✅ — 图表扩展（Phase C 对齐，2026-06-05）

与 [DIAGRAM_EXPANSION_PLAN.md](./DIAGRAM_EXPANSION_PLAN.md) Phase C 同步，工具箱 #5 从「单张 PlantUML」升级为 **图表渲染**：

#### 5.1 后端 `/api/tool/uml`

- 接受 **`diagrams` 数组**（与 Agent `solve_lab` 输出同构，最多 12 张）
- 兼容 **`plantuml_src`**（旧用法）与 **`dfd_json`** / `source` JSON 字符串
- 内部调用 `render_uml_diagrams()` → PlantUML（`uml_render`）+ 标准 DFD（`dfd_render` + 便携 Graphviz）
- 响应新增：`kind_stats`、`summary`、`titles`、`diagram_count`

#### 5.2 前端工具箱

- 工具 #5 重命名为 **「图表渲染」**；`resolveToolInput('uml')` 自动传递 #2 的完整 **`diagrams` JSON**
- 头部 **`#toolboxDiagramStatus`**：展示 PlantUML JAR / Java / Graphviz (DFD) 可用性（来自 `/api/runtime-status` → `diagram_tools`）
- 卡片内：PlantUML 在线渲染开关；输出 **类型统计** + **PNG 预览**（非 base64 裸 JSON）
- 支持 kind：`class` / `sequence` / `state` / `er` / `deployment` / **`dfd`** 等

#### 5.3 与 Agent 的分工（D6）

| 能力 | Agent 模式 | 工具箱模式 |
|------|-----------|-----------|
| 决定画哪些图 / 分节落点 | ✅ Planner + `fill_hints` | ❌ |
| 批量渲染 ≤12 张（含 DFD） | ✅ `render_uml` | ✅ #5 图表渲染 |
| 调试单张 PlantUML / DFD JSON | 可 | ✅ 手动粘贴即可 |

#### 5.4 图表验错与修复（2026-06-05）

| 环节 | 实现 |
|------|------|
| 验错 | `modules/diagram_verify.py` — schema（preflight）、渲染结果、代码一致性 |
| 渲染后报告 | `render_uml_diagrams()` 返回 `validation` + `suggested_actions` |
| Agent 修复 | 新模块 `fix_diagrams`（LLM 仅改 `diagrams`）；ReAct 工具 `fix_diagrams` |
| 自动补救 | `verify_answer` → `fix_diagrams` → `render_uml`（`auto_remediate` 已映射） |
| 工具箱 | #5 卡片「🔍 验错」「🛠 AI 修复」；API `/api/tool/verify-diagrams`、`/api/tool/fix-diagrams` |

---

*文档版本：2026-06-06（Phase 1-5 全部完成；§4.6 修复代码回写 #3）*
