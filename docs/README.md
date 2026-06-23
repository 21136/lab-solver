# Lab-Solver 文档索引

项目设计文档按主题分子目录存放。**运行时代码不读取这些路径**（仅注释与 AI 协作文档引用）；移动后已在 `CLAUDE.md`、`DESIGN.md`、`.cursor/skills/` 等处同步更新。

## 推荐阅读顺序

1. [product/V5_PRODUCT_PIVOT.md](product/V5_PRODUCT_PIVOT.md) — 当前产品定位（生成优先、用户落笔）
2. [architecture/LAB_SOLVER_AGENT_PLAN.md](architecture/LAB_SOLVER_AGENT_PLAN.md) — 完整 Agent 架构（主文档）
3. [architecture/IMPLEMENTATION_PHASES.md](architecture/IMPLEMENTATION_PHASES.md) — V1/V3 分阶段实施与进度
4. [../DESIGN.md](../DESIGN.md) — UI 设计规范（根目录）
5. [product/NEXT_VERSION_BACKLOG.md](product/NEXT_VERSION_BACKLOG.md) — 待办与盲区

---

## 目录结构

### [architecture/](architecture/) — Agent 架构与实施

| 文档 | 说明 |
|------|------|
| [LAB_SOLVER_AGENT_PLAN.md](architecture/LAB_SOLVER_AGENT_PLAN.md) | **主架构**：模块、Planner、Executor、ReAct、API |
| [AGENT_ARCHITECTURE_V3.md](architecture/AGENT_ARCHITECTURE_V3.md) | V3 编排收敛、registry、反馈闭环 |
| [IMPLEMENTATION_PHASES.md](architecture/IMPLEMENTATION_PHASES.md) | Phase 1～3 + V3 冲刺拆分 |
| [AGENT_ERROR_HANDLING.md](architecture/AGENT_ERROR_HANDLING.md) | 预检 → 分类 → 策略修复 → 降级 |
| [RUNTIME_LOGIC_ISSUES.md](architecture/RUNTIME_LOGIC_ISSUES.md) | **运行逻辑问题清单** RL1–RL12（✅）+ `code_cloze` 补充 BF45–BF49 |
| [AGENT_OPTIMIZATION_PLAN.md](architecture/AGENT_OPTIMIZATION_PLAN.md) | **Agent 优化路线图** AO-P0 ✅ · AO-P1～P3 待做 |
| [AGENT_IMPROVEMENT_RECOMMENDATIONS.md](architecture/AGENT_IMPROVEMENT_RECOMMENDATIONS.md) | **Agent 建设性改进建议** IR-1～IR-17 · 两周排期 |
| [AGENT_CAPABILITY_GAPS.md](architecture/AGENT_CAPABILITY_GAPS.md) | **Agent 能力短板评估** · 强/弱环节对照与补强顺序 |
| [AGENT_ROADMAP_PHASES.md](architecture/AGENT_ROADMAP_PHASES.md) | **Agent 后续路线图** · 四阶段：质量体感 → 可靠 → 进化闭环 → 工程债 |

### [product/](product/) — 产品方向与路线图

| 文档 | 说明 |
|------|------|
| [V5_PRODUCT_PIVOT.md](product/V5_PRODUCT_PIVOT.md) | **V5 战略**：Deliverable 主输出、内化验证 |
| [V4_MULTI_PHASE_SOLVE.md](product/V4_MULTI_PHASE_SOLVE.md) | 分阶段 LLM 流水线（V4-0/1 核心已落地） |
| [NEXT_VERSION_BACKLOG.md](product/NEXT_VERSION_BACKLOG.md) | v2 backlog、O7–O32、发布基建 |
| [PLAN_EXPORT_README.md](product/PLAN_EXPORT_README.md) | 计划速览 + 给 AI 的提问模板 |

### [v2/](v2/) — v2 功能规格

| 文档 | 说明 |
|------|------|
| [V2_TOOLBOX_MODE.md](v2/V2_TOOLBOX_MODE.md) | 工具箱模式 API + 前端面板 |
| [V2_DOC_TEMPLATE_ADAPTATION.md](v2/V2_DOC_TEMPLATE_ADAPTATION.md) | DA1–DA4：表格实训、节号映射、填表 |
| [V2_IMAGE_INPUT.md](v2/V2_IMAGE_INPUT.md) | IM1–IM5：多图 OCR / Vision（✅ 已落地） |
| [IM_OCR_FIRST.md](v2/IM_OCR_FIRST.md) | 识图实施记录：OCR 优先 + IM2–IM5 落地说明 |
| [V2_DYNAMIC_SECTIONS.md](v2/V2_DYNAMIC_SECTIONS.md) | 动态分节工作台（设计中） |
| [V2_CODE_EXECUTION_FIX.md](v2/V2_CODE_EXECUTION_FIX.md) | 代码执行修复方案（已落地） |

### [features/](features/) — 独立特性设计

| 文档 | 说明 |
|------|------|
| [DIAGRAM_EXPANSION_PLAN.md](features/DIAGRAM_EXPANSION_PLAN.md) | UML、DFD、便携 Graphviz |
| [ENVIRONMENT_PROBE.md](features/ENVIRONMENT_PROBE.md) | L4 运行时环境探测 |
| [KEY_STORAGE.md](features/KEY_STORAGE.md) | Electron safeStorage 方案 |
| [HOSTED_LLM_PROVIDERS.md](features/HOSTED_LLM_PROVIDERS.md) | **Agnes 托管 Key**（零配置 · 2026-06-06 ✅） |
| [MODEL_REGISTRY.md](features/MODEL_REGISTRY.md) | LLM 模型 catalog、弃用别名、DeepSeek V4 迁移 |
| [CODE_CLOZE_QUESTIONS.md](features/CODE_CLOZE_QUESTIONS.md) | **代码完形填空** 题型规格 · A/B/C ✅ |
| [CODE_CLOZE_ROUTING.md](features/CODE_CLOZE_ROUTING.md) | **代码完形填空** 模式矩阵 / 改动边界 / PR 自检（改代码前必读） |

### [reference/](reference/) — 评审与过程文档

| 文档 | 说明 |
|------|------|
| [deepseek的建议.md](reference/deepseek的建议.md) | DeepSeek 评审（已合并主计划） |
| [AI_INSIGHTS.md](reference/AI_INSIGHTS.md) | LLM 洞察与技能学习 |
| [PROMPT_CRITIQUE_CHECKLIST.md](reference/PROMPT_CRITIQUE_CHECKLIST.md) | 7 维度评审清单 |

### [logs/](logs/) — 运行时记录

| 文档 | 说明 |
|------|------|
| [V1_BUGFIX_LOG.md](logs/V1_BUGFIX_LOG.md) | BF1–BF55 修复记录（含 RL1–RL12 → BF28–BF41；`code_cloze` → BF45–BF49；标准模式质量 → **BF50**；合规弹窗 → BF54；cloze 校验/UI → **BF55**） |

### [design/](design/) — UI 设计与 mockup

| 文档 | 说明 |
|------|------|
| [README.md](design/README.md) | Step 3 mockup 选型 + Phase 1/2/3 + **逐屏优化**进度 |
| [UI_PHASE2_NON_STEP3.md](design/UI_PHASE2_NON_STEP3.md) | Step 1/2/设置/历史改造总 spec |
| [UI_PHASE2_PACK_A.md](design/UI_PHASE2_PACK_A.md) ~ [D](design/UI_PHASE2_PACK_D.md) | Pack A～D 实施记录 |
| [UI_PHASE3_POLISH.md](design/UI_PHASE3_POLISH.md) | **Phase 3** 精致化抛光（审计 + Pack A～F） |
| [UI_SCREEN_HOME.md](design/UI_SCREEN_HOME.md) | **逐屏优化** — 首页 Step 1 |
| [STANDARD_MODE_QUALITY.md](design/STANDARD_MODE_QUALITY.md) | 标准模式质量感知强化（auto_remediate + Step2 说明条） |

---

## 路径迁移对照（2026-06-06）

| 旧路径 | 新路径 |
|--------|--------|
| `docs/LAB_SOLVER_AGENT_PLAN.md` | `docs/architecture/LAB_SOLVER_AGENT_PLAN.md` |
| `docs/AGENT_ARCHITECTURE_V3.md` | `docs/architecture/AGENT_ARCHITECTURE_V3.md` |
| `docs/IMPLEMENTATION_PHASES.md` | `docs/architecture/IMPLEMENTATION_PHASES.md` |
| `docs/AGENT_ERROR_HANDLING.md` | `docs/architecture/AGENT_ERROR_HANDLING.md` |
| `docs/V5_PRODUCT_PIVOT.md` | `docs/product/V5_PRODUCT_PIVOT.md` |
| `docs/V4_MULTI_PHASE_SOLVE.md` | `docs/product/V4_MULTI_PHASE_SOLVE.md` |
| `docs/NEXT_VERSION_BACKLOG.md` | `docs/product/NEXT_VERSION_BACKLOG.md` |
| `docs/PLAN_EXPORT_README.md` | `docs/product/PLAN_EXPORT_README.md` |
| `docs/V2_*.md` | `docs/v2/V2_*.md` |
| `docs/DIAGRAM_EXPANSION_PLAN.md` | `docs/features/DIAGRAM_EXPANSION_PLAN.md` |
| `docs/ENVIRONMENT_PROBE.md` | `docs/features/ENVIRONMENT_PROBE.md` |
| `docs/KEY_STORAGE.md` | `docs/features/KEY_STORAGE.md` |
| `docs/HOSTED_LLM_PROVIDERS.md` | `docs/features/HOSTED_LLM_PROVIDERS.md` |
| `docs/AI_INSIGHTS.md` | `docs/reference/AI_INSIGHTS.md` |
| `docs/PROMPT_CRITIQUE_CHECKLIST.md` | `docs/reference/PROMPT_CRITIQUE_CHECKLIST.md` |
| `docs/deepseek的建议.md` | `docs/reference/deepseek的建议.md` |
| `docs/V1_BUGFIX_LOG.md` | `docs/logs/V1_BUGFIX_LOG.md` |

`docs/design/` 未变动。
