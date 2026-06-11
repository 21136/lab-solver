# V5 产品大改 —「生成优先、验证内化、用户落笔」

**版本**: 2026-06-06  
**状态**: ✅ V5-5 已落地（2026-06-06：移除运行截图；V5-0～V5-4 已完成）  
**决策者意图**: 自动填表、对外提供「运行代码」服务从根上偏离了产品价值；应**生成完整可用的实验内容交给用户**，由用户自行决定填到哪里；本机环境仅用于**内部验证代码质量**；扩展 jar 仅在用户同意时用于验证。  
**关联**: [V4_MULTI_PHASE_SOLVE.md](V4_MULTI_PHASE_SOLVE.md)（技术流水线，职责重定义）· [V2_TOOLBOX_MODE.md](../v2/V2_TOOLBOX_MODE.md) · [NEXT_VERSION_BACKLOG.md](NEXT_VERSION_BACKLOG.md) · [ENVIRONMENT_PROBE.md](../features/ENVIRONMENT_PROBE.md)

---

## 1. 为什么要改

### 1.1 旧路径错在哪里

```
上传模板 docx → 解题 → 运行代码 → 截图 → 自动填回 Word
```

这条路径隐含了三个错误假设：

| 假设 | 问题 |
|------|------|
| 用户的 Word 版式我们能稳定填对 | 表格实训、节号不统一、学校模版各异 → 填错位置比不填更糟 |
| 用户需要我们代跑代码 | 多数人在自己 IDE / 实验环境跑；我们 bundled JRE 与用户课程环境不一致 |
| 「跑通」等于「作业完成」 | 用户要的是**可抄进报告的文字、代码、图**，不是一次 subprocess 的 exit code |

因此大量工程花在：

- `fill_report` 节映射、填表验错、重试  
- 工具箱 `#3 运行代码`、JRE 下载引导、fix 循环  
- 让用户关心「你有没有 Java」——而这不是解题助手的核心身份  

### 1.2 新定位（一句话）

> **解题能手 = 实验报告内容生成器 + 可选质量验证；不是在线 IDE，也不是 Word 自动填表机。**

用户拿走的是**结构化答案包**（文字、代码、图、运行结果说明），**自行**粘贴到学校模版、学习通、石墨文档等任意位置。

---

## 2. 职责边界

### 2.1 我们做什么

| 职责 | 说明 |
|------|------|
| **读题** | 解析上传文档 / 粘贴 / 多图，理解实验要求 |
| **生成** | 步骤分析、结果说明、总结、代码、图表源码 |
| **内化验证**（可选） | 在沙箱里试编译/试跑，**仅用于提高生成质量**，结果写入「验证状态」 |
| **导出** | 分节复制；预览区一键复制代码/图表；Markdown/JSON/独立 docx；zip 为可选下载 |
| **用户约束** | 「不要用任何 jar」「只要单文件 Java」「加诚信标注」等写入生成策略 |

### 2.2 我们不做什么（默认）

| 不做 | 说明 |
|------|------|
| **不替用户运行作业环境** | 不承诺与用户实验室环境一致 |
| **不默认自动填回上传模版** | `fill_original` 降为**高级/旧版**能力 |
| **不强迫用户安装 JRE** | 无运行时 → 跳过验证，仍交付内容 + 标注「未验证」 |
| **不静默下载 jar** | 验证需要第三方库 → **弹窗同意** 后下载到本地验证沙箱 |

### 2.3 用户做什么

- 选择生成约束（语言、是否允许 jar、是否要诚信标注）  
- 审阅生成内容，复制或下载  
- 自行粘贴到任意报告载体、自行在真实环境运行代码  

---

## 3. 核心概念

### 3.1 `LabDeliverable`（交付物）

替代「填表成功与否」作为**主输出**：

```typescript
interface LabDeliverable {
  id: string;
  created_at: string;

  // 分节内容（用户逐节复制）
  sections: {
    steps_analysis?: string;
    result_description?: string;
    summary?: string;
    notes?: string;
  };

  // 代码包
  code: {
    language: string;
    files: { name: string; code: string }[];
    main_file: string;
  };

  // 图表（PlantUML 源码 + 渲染 PNG，用户自选粘贴）
  diagrams?: { kind: string; title: string; plantuml?: string; image_b64?: string }[];

  // 运行相关（来自验证沙箱，非用户现场跑）
  execution: {
    validation_status: "verified" | "failed" | "skipped" | "not_requested";
    validation_note?: string;      // 人话说明
    sample_stdout?: string;        // 沙箱 stdout，供结果节引用
    sample_stderr?: string;
  };

  // 用户约束的回显
  constraints_applied: string[];   // e.g. "no_external_jar", "single_file_java"

  // 诚信 / 防伪（用户可选）
  provenance?: {
    ai_assisted: true;
    generated_at: string;
    model?: string;
    integrity_hash?: string;       // 内容摘要 hash，供用户自述「非代写」场景
    custom_label?: string;         // 用户自定义，如「AI 辅助整理」
  };

  // 质量摘要（规则 + 可选验证）
  quality: {
    verify_passed?: boolean;
    checks?: { id: string; label: string; passed: boolean }[];
  };
}
```

**UI 主界面**从「执行进度条」转为 **「答案工作区」**：左侧分节 tabs，中间「复制本节」，右侧代码/图预览 + **「复制代码 / 复制图表」**，顶部验证徽章；zip 下载收纳在「导出 ▾」。

### 3.2 `Validation Sandbox`（验证沙箱）

与「用户运行服务」彻底分离：

```
生成代码
    ↓
[用户设置：启用内化验证？]
    ↓ 是
preflight → 缺 jar？→ 用户同意下载（仅沙箱）→ 试编译/试跑
    ↓
validation_status + sample_stdout 写回 Deliverable
    ↓
LLM 写 result_description 时引用 sample_stdout（V4 Phase 2）
    ↓
交付给用户（用户自己不一定要在我们这里再点「运行」）
```

| 属性 | 用户运行服务（废弃） | 验证沙箱（保留） |
|------|---------------------|------------------|
| 入口 | 工具箱 #3、Step3「运行」 | 无独立按钮；设置在「生成时验证代码」 |
| 失败含义 | 用户作业失败 | **生成质量**未达标，触发重生/修订 |
| 依赖 JRE | 强引导下载 | 可选；无则 `skipped` |
| jar | 无 | 白名单 + 用户同意，见 §6；缺 jar 时弹窗确认后下载并重试验证 |

### 3.3 `UserConstraints`（用户约束）

在 Step 1/2 或设置中声明，写入所有生成 prompt：

| 约束 id | 用户表述示例 | 生成侧效果 |
|---------|--------------|------------|
| `no_external_jar` | 「不要任何第三方 jar」 | 禁止 import 非 JDK 包；验证沙箱不下载 jar |
| `single_file` | 「只要一个 Java 文件」 | `code_files` 长度必须为 1 |
| `no_gui` | 「不要图形界面」 | preflight 拦截 GUI 模式 |
| `provenance_label` | 「加诚信标注：AI 辅助生成」 | `deliverable.provenance` + 导出页脚 |
| `skip_validation` | 「不用帮我跑，只要代码」 | `validation_status=not_requested` |
| `allow_curated_jars` | 「可以用 H2 内存库」 | 白名单 jar 可用；缺则提示下载 |

约束优先于 skill_store 默认策略。

---

## 4. 与 V4 的关系

[V4](V4_MULTI_PHASE_SOLVE.md) 的**分阶段 LLM 流水线保留**，职责重映射：

| V4 阶段 | V5 下的含义 |
|---------|-------------|
| Phase 0 读题 | 不变 |
| Phase 1 代码 + 试跑 | **验证沙箱**（内化，非用户步骤） |
| Phase 2 写报告 | 引用 `sample_stdout`；交付分节文本 |
| Phase 3 图表 | 渲染 PNG 进 Deliverable 附件 |
| Phase 4 汇编 | 输出 `LabDeliverable`，**不是** `fill_report` 输入 |

V4 §12 已拍板决策 **继续有效**，但 Q2 试跑改为「**默认开启内化验证**」，用户可用 `skip_validation` 关闭。

---

## 5. `fill_report` 处置

### 5.1 定位调整

| 之前 | V5 |
|------|-----|
| 默认终点 `output_mode=fill_original` | 默认 `output_mode=deliverable` |
| Agent 计划末步必含 `fill_report` | 计划末步为 **present_deliverable**（零 LLM） |
| 工具箱 #6「填写报告」在主推水线 | 降为 **「高级：尝试填入模版（实验性）」** |

### 5.2 保留理由（可选能力）

部分用户仍想要「尽量填一下」：

- 保留 `fill_report` 模块与 `/api/tool/fill`  
- UI 明确标注：**「不保证版式；建议以复制粘贴为主」**  
- 不再为填表失败阻塞主流程、不再 SSE 红色阻断  

### 5.3 默认导出替代填表

| 导出格式 | 内容 |
|----------|------|
| **复制代码**（预览栏 / 导出菜单） | 全部 `code_files` 拼接；多文件带 `// 文件名` 分隔；单文件可点卡片「复制」 |
| **复制图表**（预览栏 / 导出菜单） | 单张 PNG 进剪贴板；多张优先 PlantUML 源码；每张图可单独「复制图片 / 复制图源」 |
| **复制本节** | 当前分节正文（主 CTA） |
| **复制 JSON** | 完整 Deliverable |
| **下载 Markdown** | 分节标题 + 代码块 + 图链接 |
| **下载独立 docx** | 按**固定简洁模版**生成（非用户上传模版） |
| **下载代码 zip** | `code_files` 打包（可选，非主路径） |
| **下载图表 zip** | PNG 集合（可选，非主路径） |

用户把 Markdown / 独立 docx 内容拷进学校模版，比程序猜单元格可靠。

---

## 6. Java JAR（仅验证沙箱）

沿用 [V4 §13](V4_MULTI_PHASE_SOLVE.md#13-java-外部-jar--现状动机与可选方案) 技术方案，叠加 V5 规则：

1. jar **只服务验证沙箱**，不对外宣称「本应用能跑 MyBatis 作业」。  
2. 下载前必须：**名称、大小、用途、仅用于生成质量检查**。  
3. 用户设 `no_external_jar` → **不检测、不下载、不提示**，生成侧硬约束纯 SE。  
4. 用户设 `allow_curated_jars` → 缺 jar 时暂停验证 → 同意 → 下载 → 重试（J2）。  

首版白名单仍为：H2、sqlite-jdbc（可选），不做 Maven 通用解析。

**前端流程（V5-3）**：解题返回 `solve_session.run_result.reason=missing_jar` 时弹出确认框（库名、大小、用途、仅沙箱）→ `POST /api/java-jars/download` → `POST /api/tool/retry-validation`（复用已生成代码，不重新调 LLM 写码）。工具箱 #2 与 Agent 主链均接入。

---

## 7. 诚信标注 / 「防伪」

用户可要求的输出元数据，**不是** DRM 防伪贴纸，而是**学术诚信与可追溯**：

| 能力 | 说明 |
|------|------|
| `provenance.ai_assisted` | 固定 true |
| `provenance.custom_label` | 用户自定义一句，如「内容由 AI 辅助生成，本人已核对」 |
| `integrity_hash` | SHA256(sections+code)，用户可在报告里附「校验码」自证未篡改 |
| 导出页脚 | 独立 docx / PDF 导出可选插入标注段落 |
| UI 徽章 | 答案工作区显示「已验证 / 未验证 / 未请求验证」 |

**不做**：代写承诺、绕过查重、伪造实验数据。

---

## 8. 用户体验（To-Be）

### 8.1 主流程

```
Step 1  粘贴题目文字（默认，无需文件）或上传报告
        → `assignment_only` 时 `parse-report` 返回 `fill_target: null`（BF44）
Step 2  生成约束（语言、验证、jar 策略、诚信标注）→ 生成
Step 3  答案工作区（审阅、复制、下载）— 不再是「执行计划看填表」
        完成后「回到主页」→ 重置并回到 Step 1（填表成功面板内「处理新报告」同等行为）
```

### 8.2 Agent 模式

| 模式 | V5 行为 |
|------|---------|
| **标准** | parse → solve_pipeline（含可选验证）→ present |
| **深度** | + reflect 修订文字；验证失败可重生代码 |
| **ReAct** | 收敛：首跑 solve_pipeline，**不再**把 `run_code` 暴露为高频工具 |

默认计划步骤（用户可见）：

```
1. 解析题目
2. 生成答案（含代码质量验证）
3. 渲染图表（若有）
4. 完成 — 打开答案工作区
```

隐藏/折叠：`run_code`、`fill_report`。**运行截图已移除**（V5-5，2026-06-06）。

### 8.3 工具箱

| 原 # | V5（2026-06-06） |
|------|------------------|
| 1 解析 | 保留 |
| 2 解题 | 保留 → 输出 Deliverable |
| 3 运行 | **高级**；内化验证合并进 #2 |
| ~~4 截图~~ | **已删除** — 用户自行在实验环境截图 |
| 4 图表 | 保留（原 #5，重新编号） |
| 填表 | **移入「高级 / 实验性」** |
| 修复/校验/修订 | 保留为编辑 Deliverable 的辅助 |

一键链：`#1 → #2 → 完成`，不再 `#1→#2→#6`。

---

## 9. 技术改造清单

### 9.1 后端

| 项 | 说明 |
|----|------|
| `modules/deliverable.py` | **NEW** — 组装、导出、provenance |
| `modules/solve_pipeline.py` | V4 流水线；`validation_*` 字段 |
| `output_mode` | 新增 `deliverable`（默认）；`fill_*` 保留 |
| `agent/executor.py` | `_run_fill_report` 非默认 tail；新增 `_present_deliverable` |
| `agent/registry.py` | `present_deliverable` 注册 `react_alias`（BF27：ReAct 循环内可调用，非仅收尾补跑） |
| `agent/planner.py` | 默认 plan 去掉 fill/run |
| `server.py` | `GET /api/deliverable/:id`；`POST /api/deliverable/export` |
| `run_code` | 改名为内部 `validation_sandbox.run()`；HTTP 路由标记 deprecated |

### 9.2 前端

| 项 | 说明 |
|----|------|
| Step 3 重做 | 「答案工作区」组件：分节、代码 Monaco、验证徽章、复制、下载 |
| 约束面板 | Step 2：checkbox + 自定义诚信文案 |
| 弱化环境引导 | 无 JRE 不再阻断生成；仅提示「代码未验证」 |
| 移除默认 | `output_mode` 默认 `deliverable` |
| **UI 美化 UI-1** ✅ | 2026-06-06：`DESIGN.md` token、`icons.js`、全局 SVG 图标；详见根目录 `DESIGN.md` §10、`docs/design/README.md` |
| **UI 美化 UI-2** ⏳ | Step3 三栏（左节导航 + 中正文 + 右预览），mockup 方案 4 |

### 9.3 测试

- Deliverable schema 契约测试  
- `no_external_jar` 约束下生成代码无第三方 import（金样本）  
- `skip_validation` 不产生 subprocess  
- 导出 Markdown/docx 可读性  

---

## 10. 实施分期

### V5-0 — 产品与默认切换（3～4 天）✅

- [x] `output_mode=deliverable` 默认；`answer_only` 行为对齐  
- [x] 答案工作区 MVP：分节展示 + 复制 JSON/Markdown + 验证状态占位  
- [x] Agent 计划默认 `present_deliverable`，去掉 `fill_report` 主路径  
- [x] 文案：产品定位改为「生成答案，自行填写」  

**交付**：用户主路径不再依赖填表。

### V5-1 — 验证内化（5～7 天，可与 V4-0 合并）✅

- [x] 实现 V4 `SolvePipeline` 骨架；试跑作为 Phase 1 子步骤（`modules/solve_pipeline.py`）  
- [x] `validation_status` / `sample_stdout` 进 Deliverable（来自 `solve_session`）  
- [x] 用户约束 `skip_validation` / `no_external_jar` + Step 2 约束面板 MVP  
- [x] 工具箱 #3 移入「高级 / 实验性」；主链仍为 #1→#2  

### V5-2 — 导出与诚信（3 天）✅

- [x] Markdown / zip / 独立 docx 导出（`POST /api/deliverable/export`，格式：`markdown` | `docx` | `code_zip` | `diagrams_zip` | `json`）  
- [x] `provenance` + 可选页脚（约束 `provenance_label` + 自定义诚信文案；`include_footer` 控制导出页脚）  
- [x] `integrity_hash` 答案工作区显示与复制  
- [x] 预览区 **复制代码 / 复制图表**（剪贴板；zip 降为次要）— 2026-06-08  

### V5-3 — JAR 验证沙箱（3～4 天，可选）✅

- [x] J1 白名单下载 + `-cp`（仅 sandbox；`modules/java_jars.py`，`GET/POST /api/java-jars`）  
- [x] 约束 `allow_curated_jars` 联动；缺 jar 暂停验证 → 用户同意 → 下载 → 重试（`approved_jar_ids` / `on_jar_consent`）  
- [x] `no_external_jar` 仍硬禁止：不检测、不下载、不提示 jar  
- [x] 前端缺 jar 弹窗 → `POST /api/java-jars/download` → `POST /api/tool/retry-validation`（不重新生成代码）  

### V5-4 — 填表降级（2 天）✅

- [x] `fill_report` 移入高级区；失败不阻断（SSE `degraded`，不计入 consecutive_failures）  
- [x] 工具箱一键链 `#1→#2`；填表在「高级 / 实验性」  
- [x] onboarding / 文案更新（`compliance-ux.js` ONBOARDING v2）  

### V5-5 — 移除运行截图（1 天）✅

- [x] 删除 `ide_render.py`、`modules/screenshot.py`、`screenshot_ide` / `screenshot_terminal` Agent 模块  
- [x] 移除 API：`/api/tool/screenshot`、`/api/run-and-screenshot`、`/api/screenshot-terminal`、`/api/screenshot-screen`  
- [x] 前端：工具箱截图卡片、代码面板「运行+截图」、截图/终端样式设置  
- [x] ReAct / planner / finalize 不再补跑或推荐截图；`user_profile.screenshot_style` 移除  
- [x] 运行结果改由 `result_description` + 内化验证 `sample_stdout` 覆盖；填表仅插 UML + 用户手动上传图  

**总估**：核心 V5-0～V5-2 约 **11～14 人天**；含 JAR 约 **15～18 人天**。

---

## 11. 迁移与兼容

| 群体 | 策略 |
|------|------|
| 习惯自动填表用户 | 设置保留「旧版：尝试填入上传模版」；一个版本后改默认 |
| 工具箱 localStorage | 旧 `toolState` 仍可读；`#6` 移到高级 |
| API | `/api/tool/fill`、`/api/run-code` 保留 deprecated 6 个月；截图相关路由已删除（V5-5） |
| 打包 | JRE 改为「验证可选组件」，安装包说明调整 |

---

## 12. 风险

| 风险 | 对策 |
|------|------|
| 老用户抱怨「不能一键交作业」 | 导出独立 docx + 明确沟通定位变化 |
| 未验证代码质量下降 | 默认开启内化验证；徽章可见 |
| V4/V5 文档并行混乱 | V4=流水线实现；V5=产品边界（本文）；V4 不再单独推进填表导向 |
| ReAct 工具集过大 | V5-1 收缩可见工具 |

---

## 13. 文档索引更新

| 文档 | V5 后状态 |
|------|-----------|
| **V5_PRODUCT_PIVOT.md** | **主战略**（本文） |
| V4_MULTI_PHASE_SOLVE.md | 技术子方案：分阶段 LLM + 内化验证 |
| V2_TOOLBOX_MODE.md | 需修订：工具顺序与 #3/#6 定位 |
| V2_DOC_TEMPLATE_ADAPTATION.md | 降为「高级填表」参考 |
| ENVIRONMENT_PROBE.md | 改为「验证沙箱探测」 |

---

## 14. 总结

| 维度 | 旧 | V5 |
|------|-----|-----|
| 产品身份 | 解题 + 代跑 + 代填 | **生成实验答案内容** |
| 代码运行 | 用户可见服务 | **可选内化验证** |
| jar | 回避 | **用户同意 → 仅沙箱** |
| Word | 填回上传模版 | **用户复制；填表实验性** |
| 成功标准 | fill 验字通过 | **Deliverable 完整、可审阅、约束满足** |

> 从「替用户做完实验」改为「帮用户生成高质量草稿，落笔权在用户」。

---

*文档版本：2026-06-06 · 战略大改立项 · 待评审后取代 V4 为产品主文档*
