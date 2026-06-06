# lab-solver — 项目文档

## 项目概览

桌面 Electron + Python Flask 后端实验报告解题助手。默认 **BYOK**：用户自填 LLM API Key（DeepSeek/OpenAI/Claude/智谱/自定义）；可选 **Agnes AI 托管档**（内置 Key、零配置，见 `docs/features/HOSTED_LLM_PROVIDERS.md`）。上传实验报告 doc/docx/pdf（旧版 .doc 自动转换），AI 生成结构化答案（文字、代码、UML），用户在答案工作区审阅复制；高级区可选填回 Word。

## 技术栈

| 层 | 技术 |
|---|------|
| 桌面壳 | Electron 31，主进程 `main.js` + `preload.js`（含 `openExternalUrl` 浏览器打开） |
| 前端 | 原生 HTML/CSS/JS，`src/renderer/index.html` + `app.js`，Monaco 编辑器 |
| 后端 | Python Flask，`src/python/server.py` 启动，端口 5199 |
| LLM 调用 | `llm_client.py` 统一 OpenAI 兼容 + Claude Messages API；`hosted_providers.py` 托管 Key（Agnes） |
| 文档 | python-docx (docx 读写)、PyMuPDF (PDF 读)、Word COM / LibreOffice (.doc 转换) |
| Key 存储 | BYOK：`safeStorage` → localStorage；托管：`APP_DATA/hosted_agnes.key`（见 `docs/features/HOSTED_LLM_PROVIDERS.md`） |
| 打包 | electron-builder + NSIS，`build-installer.bat` |
| 测试 | pytest，`pytest.ini`，`tests/conftest.py` 自动加 `src/python` 到 sys.path |

## 启动方式

```bash
start.bat              # 启动 Electron 桌面应用
python src/python/server.py  # 仅启动后端 API
```

## 目录结构

```
lab-solver/
├── main.js                  # Electron 主进程
├── preload.js               # 预加载脚本（IPC 桥接）
├── start.bat                # 启动脚本
├── package.json             # Electron + electron-builder 配置
├── requirements.txt         # Python 依赖
├── requirements-dev.txt     # 开发/测试依赖
├── pytest.ini
├── build-installer.bat      # 打包脚本
│
├── src/
│   ├── main/
│   │   ├── settings-store.js    # safeStorage 加密/解密 IPC
│   │   └── terminal-detect.js   # 终端检测
│   ├── renderer/
│   │   ├── index.html           # 主界面
│   │   ├── app.js               # 前端主逻辑（Step1-3、SSE、设置）
│   │   ├── icons.js             # Lucide 风格 SVG 图标（UI-1）
│   │   ├── compliance-ux.js     # 合规引导/免责声明
│   │   └── styles.css           # 全局样式（DESIGN.md token）
│   └── python/
│       ├── server.py            # Flask API 路由（薄层，编排调用；含 /api/runtime-status）
│       ├── config.py            # 路径常量 + 可选依赖标志 + 运行时环境探测（L4）
│       ├── llm_client.py        # LLM 统一客户端
│       ├── log_util.py          # 日志脱敏（Key/长正文）
│       ├── uml_render.py        # 图表渲染：PlantUML（本地 JAR + 在线）
│       ├── dfd_layout.py        # 标准 DFD：JSON 校验 + DOT 生成
│       ├── dfd_render.py          # 便携 Graphviz 渲染（assets/graphviz/bin/dot）
│       ├── settings_schema.py   # 设置迁移/版本管理
│       ├── agent/               # Agent 核心
│       │   ├── types.py             # AgentContext、ChatResult、ModuleResult 等类型
│       │   ├── planner.py           # Planner：生成步骤计划、增量重规划
│       │   ├── executor.py          # Executor：顺序执行模块、dirty_modules 复用
│       │   ├── deep_pipeline.py     # DeepPipeline：draft→(v1 preflight/fix | V4 跳过)→reflect→revise→tail
│       │   ├── understand_plan.py   # 深度模式：单次 LLM 输出 {understand, plan}
│       │   ├── reflect.py           # 深度模式：审稿（锚定 assignment_raw）
│       │   ├── quality.py           # verify_answer + revise_answer 质量保障
│       │   ├── executor_dirty.py    # dirty_modules + sub_fingerprints 字段级复用
│       │   ├── react_loop.py         # ReAct 循环：思考→行动→观察；结束后 react_finalize 补跑
│       │   ├── react_finalize.py     # ReAct 收尾：自动 UML/交付 + finalize_report 工具
│       │   ├── react_tools.py        # ReAct 工具：solve/fix/run/uml/deliverable/fill/finalize_report
│       │   ├── react_prompts.py      # ReAct System Prompt 模板
│       │   ├── prompts.py           # 集中 Prompt 模板 + 版本号
│       │   ├── prompt_budget.py     # 按节优先级裁剪输入（替代硬截断）
│       │   ├── sections_config.py   # 分节工作台 normalize → fill_scope/user_content/teacher_constraints
│       │   ├── template_analyzer.py # 答题模版分析 → format_spec
│       │   ├── user_profile.py      # 用户画像 v1（default_language/prefer_uml）
│       │   ├── parse_documents.py   # 多文档解析、角色猜测、合体拆分、粘贴文字 parse_inline_text
│       │   ├── plan_feedback.py     # 计划反馈与行为学习接口
│       │   ├── document_store.py    # 文档缓存（内存 TTL）
│       │   ├── run_control.py       # 单任务锁、取消、按步重试
│       │   ├── fallback.py          # Agent 失败降级 /api/solve
│       │   ├── decision_log.py      # 决策审计日志
│       │   └── skill_store.py       # 技能注册表（trigger→inject），3 技能：java-no-servlet/no-python/multi-file
│       ├── modules/             # 子模块（统一 ModuleResult 接口）
│       │   ├── parse_report.py      # docx/pdf 解析（DA1：表格正文抽取；DA4：detect_docx_sections）
│       │   ├── solve_lab.py         # v1 单轮 / v4 分发至 solve_pipeline
│       │   ├── solve_pipeline.py    # V4 分阶段：代码沙箱验证 → 写报告（默认主路径）
│       │   ├── run_code.py          # 编译运行代码（工具箱高级 / 内化验证）
│       │   ├── uml.py               # 图表提取与渲染（PlantUML + DFD，最多 12 张）
│       │   ├── fill_report.py       # 写回 docx；training_table 分格填表 + 单元格内嵌 UML/用户上传图
│       │   ├── lab_parse.py         # 从答案 JSON 解析各字段
│       │   ├── fix_code.py          # 编译错误修代码 + FIX_STRATEGIES 分类修复
│       │   ├── preflight.py         # 零 LLM 语法/UML/schema/执行模式/emoji 预检
│       │   ├── revise_answer.py     # 局部/整题重生成
│       │   └── parse_answer_template.py # 答题模版解析包装器
│       └── document/            # 文档格式处理
│           ├── extract_pdf.py       # PDF 文本提取 (PyMuPDF)
│           ├── convert_doc.py       # .doc → .docx 转换（Word COM → LibreOffice，SHA-256 缓存）
│           ├── extract_images.py    # docx 内嵌图枚举、SHA-256 去重、角色猜测 (IM1)
│           ├── image_read.py        # OCR + Vision hybrid、合并 assignment_text (IM2/IM5)
│           ├── user_upload_images.py # Step1 题目图组 (IM4)
│           └── pdf_export.py        # PDF/.doc 源 → 生成 docx 外壳并填充（prepare_fill_docx_for_fill 内调用 convert_doc）
│
├── tests/
│   ├── conftest.py                 # 共享 setup：sys.path 注入
│   ├── generate_fixtures.py        # 生成 Phase 1.2 金样本 docx（3+4 份）
│   ├── run_golden_regression.py    # 解析金样本回归（无 LLM）
│   ├── fixtures/                   # programming_lab 等 + solve_v4/（10 题 V4 金样本）
│   ├── test_solve_pipeline_golden.py  # V4 金样本 mock LLM + 可选真 sandbox
│   ├── test_deep_pipeline_v4.py    # deep 模式 V4 去重（AO-1）
│   ├── test_da1_tables.py          # DA1 表格提取测试
│   ├── test_planner.py
│   ├── test_phase2a.py / test_phase2a2.py
│   ├── test_phase2b.py / test_phase2b_b4.py / test_phase2b5_pdf.py
│   ├── test_phase3_compliance.py / test_phase3b_pdf_export.py
│   ├── test_plan_feedback.py
│   ├── test_log_util.py
│   ├── test_image_input.py          # IM1–IM5 + UI：OCR/PDF/上传/Vision 集成测试
│   ├── fixtures/image_input/        # scanned_5page.pdf、assignment_page*.png、vision_* 等
│   ├── test_react_loop.py / test_react_finalize.py  # ReAct 循环与收尾流水线
│   ├── test_settings_store.js      # Node 测试
│   └── verify_imports.py
│
├── DESIGN.md                   # UI 设计规范（token、动效、UI-1～4 + Phase 2 进度）
├── docs/                       # 完整设计文档（见 docs/README.md）
│   ├── architecture/           # Agent 架构、实施阶段、错误处理
│   ├── product/                # 产品战略、V4/V5、backlog
│   ├── v2/                     # v2 功能规格（工具箱、填表、图片等）
│   ├── features/               # 独立特性（图表、环境探测、Key 存储）
│   ├── reference/              # 评审建议、洞察、清单
│   ├── logs/                   # 运行时 bug 修复记录
│   └── design/                 # UI mockup、Phase 2 实施记录
├── scripts/                    # build-win.ps1, run-tests.bat, unlock-dist.ps1
├── assets/                     # 图标等
├── release/                    # 已构建的安装包
└── students.json               # 学生数据（演示用）
```

## docs 文档索引

> 完整目录与阅读顺序见 **[docs/README.md](docs/README.md)**。

| 文档 | 用途 |
|------|------|
| `../DESIGN.md` | **UI 设计规范**：OKLCH token、图标、Step3 三栏 mockup 选型、UI-1～4 + Phase 2（P2-A～D ✅） |
| `design/README.md` | Step3 mockup + Phase 1/2 实施进度表 |
| `design/UI_PHASE2_NON_STEP3.md` | Phase 2 总规划（P2-A～D ✅） |
| `design/UI_PHASE2_PACK_A.md` | Pack A Step1 双栏实施清单 |
| `design/UI_PHASE2_PACK_B.md` | Pack B Step2 hero/卡片/sticky 实施记录 |
| `docs/architecture/LAB_SOLVER_AGENT_PLAN.md` | **完整架构设计**（主文档）：Agent、DeepPipeline、**ReAct+收尾**、分节工作台、API |
| `docs/architecture/AGENT_ARCHITECTURE_V3.md` | **Agent 架构加强（V3）**：V3-1 ✅ registry + ReAct LLM/读题；待做 Orchestrator、auto_remediate、C2 |
| `docs/architecture/IMPLEMENTATION_PHASES.md` | V1 分阶段实施拆分 + Phase V3 进度（§五，V3-1 ✅） |
| `docs/product/PLAN_EXPORT_README.md` | 计划要点速览 + 给 AI 的提问模板 |
| `docs/product/NEXT_VERSION_BACKLOG.md` | v2 backlog：DA/IM 立项 + O7-O32 盲区 + 发布基建 |
| `docs/v2/V2_DOC_TEMPLATE_ADAPTATION.md` | v2 DA1-DA4：表格实训、节号语义映射、填表适配 |
| `docs/v2/V2_IMAGE_INPUT.md` | IM1–IM5 识图总规格（✅ 已落地） |
| `docs/v2/IM_OCR_FIRST.md` | OCR 优先实施记录与维护说明 |
| `docs/features/ENVIRONMENT_PROBE.md` | L4 运行时环境探测设计：Python/Java/C/Node 探测 → prompt 注入 |
| `docs/architecture/AGENT_ERROR_HANDLING.md` | Agent 错误处理增强：预检→分类→策略修复→智能降级 |
| `docs/reference/deepseek的建议.md` | DeepSeek 13 条评审建议（已合并主计划） |
| `docs/reference/PROMPT_CRITIQUE_CHECKLIST.md` | 7 维度评审清单 |
| `docs/reference/AI_INSIGHTS.md` | LLM 解题自述洞察收集 + 技能学习路径（skill_store.py 注册 3 技能，executor 自动追加 Agent 模式 notes） |
| `docs/features/KEY_STORAGE.md` | safeStorage 加密方案 + 风险说明 |
| `docs/features/HOSTED_LLM_PROVIDERS.md` | Agnes 等托管 LLM Key（零配置） |
| `docs/features/MODEL_REGISTRY.md` | 模型 catalog、弃用别名、DeepSeek V4 |
| `docs/v2/V2_TOOLBOX_MODE.md` | 工具箱模式设计文档：独立工具 API + 前端面板（含 #5 图表渲染 / DFD） |
| `docs/product/V5_PRODUCT_PIVOT.md` | **V5 战略大改**：生成优先、验证内化、用户落笔；Deliverable 主输出 |
| `docs/product/V4_MULTI_PHASE_SOLVE.md` | V4 分阶段 LLM 流水线（技术子方案，并入 V5-1） |
| `docs/features/DIAGRAM_EXPANSION_PLAN.md` | 图表扩展：UML 种类、DFD、便携 Graphviz、Agent vs 工具箱分工 |
| `docs/logs/V1_BUGFIX_LOG.md` | 运行时 bug 修复记录（BF1–BF31，含 SSE/done.ok/文档缓存重试 RL1–RL4） |
| `docs/architecture/RUNTIME_LOGIC_ISSUES.md` | 运行逻辑审查清单（RL1–RL4 ✅，RL5–RL12 待修/设计债） |

## 核心 Agent 流程

```
上传文档 → parse_documents (角色猜测 + 合体拆分)
  → Planner 生成 PlanStep[] + plan_fingerprint
  → 用户确认/勾选 + clarifications
  → Executor 顺序执行模块
  → verify_answer 规则校验
  → revise_answer (不满意时) + fill_report 写回 docx
```

**运行模式**：`run_mode=standard` (~2 次 LLM)；`run_mode=deep` (DeepPipeline ~3-4 次)；`run_mode=react` (ReAct Loop ~5-12 次；循环内可调用 `present_deliverable`；收尾仍**自动补跑**缺失的 UML/交付；`finalize_report` 一键收尾)。

**工具箱模式**：Step 2 顶部模式切换 Tab（引导模式 / 工具箱模式）。工具箱提供 8 个独立工具卡片：解析文档 → AI 解题 → 运行代码（高级）/ **图表渲染** → 填写报告（实验性），以及 3 个辅助工具（修复代码、校验答案、修订答案）。**图表渲染**支持 `diagrams` JSON 数组（PlantUML + 标准 DFD，最多 12 张）。**修复代码**成功后会写回 `#2` 并同步到 `#3 运行代码` 输入框。详见 `docs/v2/V2_TOOLBOX_MODE.md`。

**V5 产品大改（V5-0 已落地）**：定位从「代跑+代填 Word」转为 **生成答案内容（Deliverable）由用户自行落笔**；默认 `output_mode=deliverable` + Step3 答案工作区；`fill_report` 降为实验性高级功能。详见 `docs/product/V5_PRODUCT_PIVOT.md`。

**V4 分阶段解题（技术子方案）**：读题 → 只写代码 → 内化验证 → 写报告 → 图表；并入 V5-1。详见 `docs/product/V4_MULTI_PHASE_SOLVE.md`。

**工具箱 API** (10 条路由，统一 `{ok, data, error}` 响应)：

| 路由 | 功能 | 模块 |
|------|------|------|
| `POST /api/tool/parse` | 解析 doc/docx/pdf（.doc 自动转换） | `parse_report` |
| `POST /api/tool/solve` | AI 解题 | `solve_lab` |
| `POST /api/tool/run` | 运行代码（高级） | `run_code` |
| `POST /api/tool/uml` | 图表渲染（PlantUML + DFD） | `uml` + `dfd_render` |
| `POST /api/tool/verify-diagrams` | 图表验错（schema / 渲染 / 一致性） | `diagram_verify` |
| `POST /api/tool/fix-diagrams` | LLM 修复 diagrams | `fix_diagrams` |
| `POST /api/tool/fill` | 填写报告 | `fill_report` |
| `POST /api/tool/fix` | 修复代码 | `fix_code` |
| `POST /api/tool/verify` | 校验答案 | `quality.verify` |
| `POST /api/tool/revise` | 修订答案 | `quality.revise` |

**输出方式** (`output_mode`)：`deliverable`（默认，答案工作区 + `present_deliverable`）；`answer_only`（与 deliverable 同主路径）；`fill_original` / `new_document`（高级实验性填表）。无 fill_target 时 `fill_original` 禁用。`modules/deliverable.py` 组装 `LabDeliverable`；`POST /api/deliverable/export` 导出 Markdown。

## 关键设计原则

- **evidence 门禁**：步骤存在性由报告原文 `evidence` 支撑，画像/模版只能影响 params
- **指纹校验**：plan_fingerprint = sha256(sections_config + document_ids + split_idx + layout)，sections 变更 → 409 stale_plan
- **多文档角色**：assignment（题目）、fill_target（待填报告）、answer_template（范文/模版）、reference（参考资料）；assignment 也可经 Step 1 **粘贴**（`text_content`，无需文件）
- **合体拆分**：单 docx 前半题目+后半待填 → 在 `三、实验步骤` 处 split
- **分节工作台**：sections_config.normalize() → fill_scope + user_content + teacher_constraints
- **fill_mode**：auto/skip/preserve/generate_only/user_provided（每节独立）
- **日志脱敏**：log_util 过滤 api_key、Bearer token、sk- 前缀

## 当前实现状态 (2026-06-06)

**V1 已完成**：Phase 1/2a/2b/3/3b 全部 27/27 todo completed。
- 标准/深度 Agent、分节工作台、多文档（前后端）、verify/revise、PDF 读/导出、compliance、safeStorage、template 整合
- 打包验证：`build-installer.bat` 通过，生成 `installer/解题能手 Setup 1.0.0.exe`（76MB）

**v2 进行中**：
- **DA1** ✅ — 表格正文抽取
- **DA2** ✅ — section_map 语义映射（含「实验任务」→ steps、「实验小结」→ summary；过滤 `1.xxx` 列表伪节标题）
- **DA3** ✅ — 填表适配（段落 + training_table 双路径；`/api/fill-report` 与 Agent 共用 metadata）
- **DA4** ✅ — UI 映射确认（`semantic_overrides` 随 `/api/agent/run` 下发）
- **L4** ✅ — 运行时环境探测 + 安装引导
- **L4.1** ✅ — Agent 错误处理增强
- **IM1–IM5** ✅ — 识图全链路（2026-06-06）：枚举 · OCR · 扫描 PDF · 题图上传 · Vision hybrid opt-in · O30 预览
- **phase2-multi-doc** ✅ — 多文档 UI + Step1 粘贴题目/要求
- **skill-system** ✅ — 技能注册表 + Agent 洞察学习
- **toolbox-mode** ✅ — 工具箱模式：9 条独立 API + Step 2 模式切换 + 前端工具面板（#5 图表渲染含 DFD）
- **doc-conversion** ✅ — .doc（旧版 Word）格式支持：Word COM / LibreOffice headless 自动转换 .docx，SHA-256 缓存，解析+填表全链路覆盖
- **thought-export** ✅ — 思考过程导出：运行结束自动保存 + 侧栏/Step4 手动导出 `.txt`（见下方）
- **react-finalize** ✅ — ReAct 自动收尾（UML/交付）+ `finalize_report` 一键工具
- **v5-screenshot-removal** ✅ — **移除运行截图**（2026-06-06）：删除 `ide_render.py`、`modules/screenshot.py`、`screenshot_ide/terminal` Agent 模块、`/api/tool/screenshot` 等路由及全部 UI；运行结果由文字 + 内化验证 `sample_stdout` 覆盖；详见 `docs/product/V5_PRODUCT_PIVOT.md` §V5-5
- **ui-1-tokens-icons** ✅ — **UI 美化 Phase 1**（2026-06-06）：`DESIGN.md` token 写入 `styles.css`；新增 `icons.js`；全局 emoji → Lucide SVG；按钮/表单 focus 与 `prefers-reduced-motion`；详见 `DESIGN.md` §10、`docs/design/README.md`
- **UI-C** 📝 — 一图多题自动拆分（当前 `multi_question_in_image` warn + O30 手改）
- **UI-2～4** ✅ — Step3 三栏、Step1/2 减负、三步条（见 `DESIGN.md` §10）
- **step3-home-nav** ✅ — Step3 deliverable 完成后「回到主页」（页头 + 底栏，`startNew()`；见 BF42）
- **UI Phase 2 P2-A/B** ✅ — Step1 双栏 + Step2 hero/卡片/sticky（见 `docs/design/UI_PHASE2_PACK_*.md`）；**P2-C/D** 📋 设置/历史/壳层

### 思考过程导出（2026-06-05）

| 能力 | 说明 |
|------|------|
| 自动保存 | Agent/ReAct 执行结束后写入 `%APPDATA%\lab-solver\thought_logs\思考过程_{文档}_{模式}_{时间}.txt` |
| 手动导出 | 思考过程侧栏「导出」、Step 4「导出思考过程」 |
| 内容 | ReAct 每轮思考/参数/结果（完整版 `thought_trace`）、决策日志、`solve_lab` 的 `notes` |
| IPC | `write-thought-log`（自动）、`save-text-dialog`（另存为）；`preload.js` 暴露 `writeThoughtLog` / `saveTextDialog` |

### 填表 metadata 链路（2026-06-05）

解析时 `parse_documents` 将 `sections_detected` / `section_map` / `report_layout` / `table_map` 写入 bundle metadata；`agent/run` 接收前端 `semantic_overrides`；`buildFillReportPayload()` 对 `/api/fill-report`（「生成完整报告」）同样附带完整 metadata（含 `assignment_text`）。`fill_lab` 在 metadata 缺失时自动检测 `training_table`；**2026-06-05** 起支持超星式 **实验名 / 实验目的 / 实验内容** 分格写入，UML 与用户上传图插入 **实验内容** 单元格。**实验目的**从题目 `assignment_text` 的「实验目的与原理」段解析（`extract_objective_from_assignment`），非 `steps_analysis` 首段。

## 已知硬编码问题（DA2/DA3 已解决）

`modules/fill_report.py` 的 `SECTION_HEADER_PATTERNS` 死绑 `三/四/五` 已被 `detect_sections()`（语义关键词匹配）和 `section_map` 驱动填表替代。`_replace_section()` 边界检测优先使用 section_map，fallback 到序号正则。`_fill_training_table()` 支持表格型实训报告写入单元格。段落填表若核心三栏均未匹配会 `ValueError`（避免静默空填）；表格填表走独立校验。详见 `docs/v2/V2_DOC_TEMPLATE_ADAPTATION.md` §2、`docs/logs/V1_BUGFIX_LOG.md` BF17–BF20。

## 测试

```bash
python -m pytest tests/ -v                              # 全部测试
python tests/generate_fixtures.py                       # Phase 1.2 docx 金样本
python tests/fixtures/solve_v4/gen_fixtures.py          # V4 十题金样本 + manifest.json
python tests/run_golden_regression.py                   # 解析回归（无 LLM）
python -m pytest tests/test_solve_pipeline_golden.py -m golden_sandbox -s  # V4 sandbox 基线
```
