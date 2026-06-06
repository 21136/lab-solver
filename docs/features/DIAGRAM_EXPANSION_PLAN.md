# 软件工程图表扩展 — 设计文档

**用途**：扩展解题能手的 UML / 分析图能力，覆盖软工专业常见实验（不限于设计模式类图）。  
**状态**：Phase A/B/C 已实现；Phase D 待实现  
**关联**：[LAB_SOLVER_AGENT_PLAN.md](../architecture/LAB_SOLVER_AGENT_PLAN.md) · [AGENT_ARCHITECTURE_V3.md](../architecture/AGENT_ARCHITECTURE_V3.md) · [V2_DOC_TEMPLATE_ADAPTATION.md](../v2/V2_DOC_TEMPLATE_ADAPTATION.md) · `src/python/assets/README.txt`（PlantUML 本地渲染）

---

## 一、已确认的产品决策

| # | 决策 | 说明 |
|---|------|------|
| D1 | **单张图上限 12** | `extract_diagrams` / `render_diagrams` 由 `[:4]` 改为 `[:12]` |
| D2 | **默认每张图独立** | 如设计模式「每模式一张类图」；仅当报告**明确要求**「一张大的类图」「合并类图」「总览类图」等时才合并 |
| D3 | **新增优先级** | 第一批：**状态图 → ER 图 → 部署图**；第二批补齐其余 UML；**标准 DFD** 单独立项 |
| D4 | **标准 DFD 必做** | 课程要求规范数据流图符号，不接受仅用活动图凑合 |
| D5 | **插入位置：合理即可** | 不追求像素级精准；**禁止**插入「实验目的」等元信息节；**默认倾向「实验内容 / 实验步骤」**；由 Agent 结合 `section_map` / 报告语义决定具体落点 |
| D6 | **插图编排 vs 渲染分工** | **Agent 档**负责智能插图（Planner、`fill_hints.diagrams_target`、禁止进实验目的）；**工具箱**负责手动批量渲染（≤12 张 PlantUML + DFD），不做分节编排 |
| D7 | **DFD 用便携 Graphviz** | 与 `plantuml.jar` 同级，将 Graphviz 便携版打入 `src/python/assets/graphviz/`，**不要求用户自行安装**；系统 PATH 中的 `dot` 仅作开发/兜底 |

---

## 二、现状与差距

### 2.1 已有能力

| 能力 | 位置 | 说明 |
|------|------|------|
| PlantUML 渲染 | `uml_render.py` | 本地 `plantuml.jar` 优先，在线后备 |
| 图列表协议 | `solve_lab` → `parsed.diagrams[]` | `{ kind, title, plantuml }` |
| Prompt 引导 | `prompts.py` → `LAB_REPORT_UML_APPEND` | 仅 `class \| sequence \| usecase \| activity` |
| 关键词检测 | `detect_needs_uml()` | 含状态/构件/部署等，但未写入 Prompt kind |
| 类图一致性 | `uml_consistency.py` | 代码类名 ↔ PlantUML 类名，覆盖率 ≥ 60% |
| 插图 | `fill_report.py` | 全部 UML 固定插入 `steps`（实验步骤） |
| 数量上限 | `uml.py` / `uml_render.py` | **12 张**（Phase A） |

### 2.2 主要差距

1. **种类**：软工常要的**状态图、ER 图、部署图、构件图、包图、标准 DFD** 缺少 Prompt 示例与场景套餐。  
2. **数量**：设计模式 6 模式 + 时序图等易超 4 张。  
3. **合并策略**：未区分「分模式」与「总览合并」。  
4. **插图**：不区分图类型，且未排除「实验目的」。  
5. **DFD**：PlantUML 无标准 DFD 符号体系，需**第二渲染通道**。

---

## 三、图类型 taxonomy（软工课映射）

### 3.1 统一数据模型（扩展 `diagrams[]`）

```json
{
  "kind": "class",
  "title": "简单工厂模式类图",
  "plantuml": "@startuml\n...\n@enduml",
  "merge_group": null,
  "placement_hint": "content",
  "source_engine": "plantuml"
}
```

| 字段 | 说明 |
|------|------|
| `kind` | 见下表 `kind` 枚举 |
| `title` | 插入 Word 时的图题 / 上下文依据 |
| `plantuml` / `source` | 主图源文本（DFD 可为 `dot` 或 `dfd_json`） |
| `merge_group` | 可选；相同非空值表示应画在同一张图内（仅当 D2 合并策略触发时由 LLM 设置） |
| `placement_hint` | Agent 建议落点：`content` \| `steps` \| `result` \| `design` \| `environment`；填表作软约束 |
| `source_engine` | `plantuml`（默认）\| `graphviz`（DFD / 部分架构图） |

### 3.2 `kind` 枚举（分期）

#### Phase 1 — PlantUML 原生（优先实现）

| kind | 中文 | 典型课程/实验 | Prompt 套餐关键词 |
|------|------|---------------|-------------------|
| `class` | 类图 | 面向对象、设计模式 | 类图、设计模式、UML类 |
| `sequence` | 时序图 | 交互、设计模式 | 时序、顺序、交互 |
| `usecase` | 用例图 | 需求分析、软工概论 | 用例、参与者、需求 |
| `activity` | 活动图 | 业务流程、算法流程 | 活动图、流程（非 DFD） |
| **`state`** | **状态图** | 状态机、工作流 | **状态图、状态转换、状态模式** |
| **`er`** | **ER / E-R 图** | 数据库、信息系统 | **ER、E-R、实体、联系、数据库设计** |
| **`deployment`** | **部署图** | 系统部署、B/S | **部署、服务器、节点、B/S** |
| `component` | 构件图 | 软件体系结构 | 构件、组件、模块 |
| `package` | 包图 | 多包 Java 项目 | 包图、package |
| `flowchart` | 流程图 | 程设基础 | 流程图、程序流程（与 activity 二选一，由报告措辞决定） |

#### Phase 2 — 校验与插图增强

- 时序图：`participant` 名与代码类型弱校验  
- 用例图：至少 1 actor + 1 use case  
- ER 图：实体数与代码/SQL 表名弱校验  

#### Phase 3 — 标准 DFD（独立引擎）

| kind | 中文 | 说明 |
|------|------|------|
| `dfd` | 数据流图（标准） | 顶层 / 0 层 / 1 层；**外部实体 □、处理 ○、数据存储 ═、数据流 →** |

**渲染方案（已定）**：

采用 **结构化 JSON → DOT → 便携 Graphviz**（原方案 B），不采用纯 SVG 或 LLM 直写 DOT。

| 环节 | 做法 |
|------|------|
| LLM 输出 | `dfd_json`：`externals[]` `processes[]` `stores[]` `flows[]` + `level`（顶层/0层/1层） |
| Python | `dfd_layout.py` 校验 + 生成带 DFD 标准形状的 `.dot`（外部实体方框、处理圆、存储开口矩形） |
| 渲染 | 调用 **便携** `dot -Tpng`（见 §3.3） |
| 分发 | 与 PlantUML 并列，由 `diagram_render.py`（新薄封装）按 `source_engine` 路由 |

### 3.3 便携 Graphviz 布局（D7）

与 `plantuml.jar` 相同策略：**随应用分发，开箱即用**。

```
src/python/assets/
  plantuml.jar          # 已有
  graphviz/             # 便携 Graphviz（Windows x64 为首发目标）
    bin/
      dot.exe
    lib/                # dot 依赖的 DLL（便携 zip 自带，须整包保留）
  dfd_layout.py         # Phase C：JSON → DOT
  dfd_render.py         # Phase C：便携 Graphviz 渲染
  README.txt            # 含 PlantUML + Graphviz 自测说明
```

**`dot` 查找顺序**（`dfd_render.py` 内 `_find_dot()`，对齐 `uml_render._find_java()`）：

1. `{ASSETS_DIR}/graphviz/bin/dot.exe`（Windows）或 `.../bin/dot`（macOS/Linux）
2. 系统 `PATH` 中的 `dot` / `dot.exe`（开发机已装 Graphviz 时可用，**非用户必需**）
3. 均未找到 → 明确报错：`未找到便携 Graphviz，请检查 assets/graphviz 是否完整`

**获取与打包**：

| 场景 | 做法 |
|------|------|
| 开发 / 仓库 | 提供 `scripts/fetch-graphviz-portable.ps1`（或 `.bat`）从官方 Windows zip 解压到 `assets/graphviz/`；大文件可 `.gitignore`，CI/打包脚本拉取 |
| Electron 安装包 | `electron-builder` `extraResources` 将 `assets/graphviz/` 与 `plantuml.jar` 一并打入 `resources/python/assets/` |
| 体积 | 便携包约 5–15 MB，可接受；仅 DFD 场景加载，不影响纯 UML 实验 |

**不要求用户操作**：设置页无需「安装 Graphviz」引导；`/api/runtime-status` 仅报告 `graphviz_ok: true/false` 便于排障。

---

## 四、场景套餐（Agent / Prompt）

报告解析后，按关键词选择**默认图组合**（用户可在计划步骤里取消 `render_uml` 或改 `include_uml`）：

| 场景 ID | 触发关键词（示例） | 默认图（独立张数，≤12） | 合并例外 |
|---------|-------------------|------------------------|----------|
| `design_patterns` | 设计模式、创建型、结构型 | 每模式 1 类图（或 + 关键模式时序图） | 报告写「总览类图」「合并」→ 1 张 `merge_group=overview` |
| `oo_design` | 面向对象、类设计 | 类图 + 时序图 | — |
| `requirements` | 需求分析、用例 | 用例图 + 活动图（主流程） | — |
| `database` | 数据库、E-R、表设计 | ER 图（+ 可选类图） | — |
| `architecture` | 架构、体系结构 | 构件图 + 部署图 + 包图 | — |
| `bs_web` | B/S、Web、HttpServer | 部署图 + 时序图（请求链） | — |
| `state_machine` | 状态机、状态模式 | 状态图 + 类图 | — |
| `structured_analysis` | 数据流图、DFD、结构化分析 | DFD 顶层 + 0 层展开（分层多张） | 层级图各自独立，不合并 |
| `algorithm` | 算法、程序流程 | 流程图/活动图 | 通常无类图 |

**合并规则（D2）**：仅当 `assignment_raw` 或表格题目出现下列之一时，LLM 才设置 `merge_group` 或单张多类 PlantUML：

- 「一张（总的/完整的）类图」
- 「合并类图 / 总览类图」
- 「画在同一张图上」

否则：**一个模式 / 一个子系统 / 一层 DFD = 一张图**。

---

## 五、插图策略（D5 / D6）

### 5.1 禁止落点（硬规则）

以下语义节**不得**插入任何 UML/DFD/截图类图片：

- `objective` / 实验目的、实验目标、实训目的  
- 封面信息：学号、姓名、班级、专业、实验日期、指导老师（表格标签格）

实现：`fill_report` 维护 `_IMAGE_FORBIDDEN_SEMANTICS`；Agent 传的 `placement_hint` 若命中禁止集则降级到 `content` 或 `steps`。

### 5.2 推荐落点（软规则，Agent 决策）

| placement_hint | 常见报告对应 | 适合图类型 |
|----------------|--------------|------------|
| `content` | 实验内容、实验步骤及内容 | 类图、用例图、ER、DFD、状态图（**默认**） |
| `steps` | 实验过程、操作步骤 | 时序图、活动图、流程图 |
| `result` | 实验结果 | 运行截图（已有）；UML 一般不放 |
| `environment` | 实验环境 | 部署图 |
| `design` | 设计说明（若有独立节） | 构件图、包图、架构图 |

**原则**：宁可放在「实验内容」大节末尾，也不要塞进「实验目的」。Agent 在 `fill_report` 前可根据 `section_map` + `placement_hint` 写入 `fill_hints.diagrams_target`（可选列表：`[{image_index, target_semantic}]`）；若 Agent 未指定，**回退**：`uml_default_target` 优先 `content`（实验内容类标题），其次 `steps`。

### 5.3 与三档模式关系

| 模式 | 插图职责 |
|------|----------|
| 标准 / 深度 / ReAct | Planner 决定是否 `render_uml`；ReAct 在 `fill_report` 前可读 `section_map`；`finalize_report` 沿用同一 `fill_hints` |
| 工具箱 | 批量渲染 ≤12 张（PlantUML + DFD），**不**做 `diagrams_target` 分节编排；#5 图表渲染 + 引擎状态栏 |

---

## 六、实现分期

### Phase A — 协议与上限（小改，优先）

| 任务 | 文件 | 内容 |
|------|------|------|
| A1 | `uml.py`, `uml_render.py` | `[:4]` → `[:12]` |
| A2 | `prompts.py` | 扩展 `LAB_REPORT_UML_APPEND`：kind 枚举、合并规则、场景套餐摘要、每类 1 个中文示例 |
| A3 | `uml_render.py` → `detect_needs_uml` | 增加 ER、DFD、部署、状态等关键词；DFD 命中时 `needs_dfd=true` 标志（供 Planner） |
| A4 | `planner.py` | `render_uml` 的 reason/evidence 可提及图类型组合 |
| A5 | `preflight.py` | schema 校验：`kind` 合法值、`plantuml` 含 `@startuml` |

**验收**：设计模式 6 类图 + 1 时序图共 7 张可一次渲染；Prompt 明确「默认不合并」。  
**Phase A 完成**（2026-06-05）：`[:12]`、`LAB_REPORT_UML_APPEND` 扩展、`detect_diagram_needs`（含 `needs_dfd`）、`preflight` kind 校验、`planner` render_uml reason/evidence。

### Phase B — 优先三图（状态 / ER / 部署）

| 任务 | 内容 |
|------|------|
| B1 | Prompt 内嵌 state / er / deployment 完整示例（中文类名） |
| B2 | `uml_consistency.py` | ER：实体名提取（PlantUML `entity` 语法）；state：状态名粗提取（可选） |
| B3 | `fill_report.py` | 禁止插入实验目的；支持 `fill_hints.diagrams_target`；默认回退 `content` > `steps` |
| B4 | `agent/executor.py` / `react_tools.py` | `render_uml` 结果 summary 带图类型统计 |

**验收**：需求分析实验自动生成用例图；数据库实验生成 ER；B/S 实验生成部署图；图不进实验目的。  
**Phase B 完成**（2026-06-05）：`LAB_REPORT_UML_APPEND` 补全 state/er/deployment 完整中文示例；`uml_consistency` ER 实体名与状态名粗提取；`fill_report` 禁止插图进实验目的、`fill_hints.diagrams_target`、默认 `content` > `steps`；`render_uml` 结果 `kind_stats` + `summary` 图类型统计。

### Phase C — 标准 DFD（便携 Graphviz）

| 任务 | 内容 |
|------|------|
| C1 | 新增 `dfd_render.py` + `dfd_layout.py`；`_find_dot()` 优先 `assets/graphviz/bin/dot.exe` |
| C2 | 新增 `scripts/fetch-graphviz-portable.ps1`（解压官方 Windows 便携 zip 到 `assets/graphviz/`）；打包脚本确保安装版含该目录 |
| C3 | `solve_lab` JSON：`kind=dfd` + `dfd_json`（或 `source` 字段存 JSON 字符串） |
| C4 | Prompt：`structured_analysis` 套餐 + DFD 层级与 `dfd_json` schema 示例 |
| C5 | `preflight`：DFD 平衡性粗检（外部实体、处理命名、流端点合法） |
| C6 | `assets/README.txt` | 便携 Graphviz 目录说明 + `dot -V` / DFD 样例自测命令（**非**「请用户安装 Graphviz」） |
| C7 | `config.py` / `/api/runtime-status` | `graphviz_ok`（检测便携 `dot` 是否可执行） |

**验收**：未装系统 Graphviz 的机器上，仅凭 `assets/graphviz/` 即可生成标准 DFD PNG；目录缺失时错误信息指向 `assets/graphviz` 而非官网下载页。  
**Phase C 完成**（2026-06-05）：`dfd_layout.py` + `dfd_render.py`（`_find_dot()` 优先便携 `assets/graphviz/bin`）、`scripts/fetch-graphviz-portable.ps1`、`kind=dfd` + `dfd_json` 渲染路由、`structured_analysis` Prompt + schema 示例、preflight DFD 平衡性粗检、`assets/README.txt` Graphviz 自测、`/api/runtime-status` 的 `graphviz_ok`；**工具箱 #5 升级为图表渲染**（见 [V2_TOOLBOX_MODE.md](../v2/V2_TOOLBOX_MODE.md) Phase 5）。

### Phase D — 图表验错与修复闭环

| 任务 | 文件 | 内容 |
|------|------|------|
| D1 | `diagram_verify.py` | 统一验错：schema / 渲染 / 一致性 → `issues` + `suggested_actions` |
| D2 | `fix_diagrams.py` + `executor._run_fix_diagrams` | LLM 仅修订 `diagrams`；ReAct 工具 `fix_diagrams` |
| D3 | `uml.py` / `executor._run_render_uml` | 渲染结果附带 `validation`；部分失败时 `ok=false` |
| D4 | `quality.py` + `executor_dirty.py` | verify 建议 `fix_diagrams`；auto_remediate 映射 `render_uml` |
| D5 | 工具箱 #5 + `/api/tool/verify-diagrams` `/api/tool/fix-diagrams` | 验错 + AI 修复 + 重渲染 |

**Phase D 完成**（2026-06-05）：验错→修复→重渲染闭环；Agent（verify/auto_remediate/ReAct）与工具箱均已覆盖。

### Phase E — 其余 UML + 质量（可选，原 Phase D）

- 构件图、包图、流程图 Prompt 补全  
- 时序图 participant 校验  
- 设置页：「图类型偏好」多选（高级，可后置）

---

## 七、配置与依赖

| 依赖 | 用途 | 分发方式 | 用户侧 |
|------|------|----------|--------|
| `plantuml.jar` + Java | UML / ER / 大部分图 | `assets/plantuml.jar` + 系统或自带 JRE | 已配置，见 `assets/README.txt` |
| **便携 Graphviz `dot`** | **标准 DFD** | **`assets/graphviz/`**（随安装包 / 开发目录） | **零配置**；缺失时看 README 与 `runtime-status` |

`dot` 解析顺序：**便携 `assets/graphviz/bin` → 系统 PATH（兜底）**。

环境探测：`/api/runtime-status` 报告 `plantuml_jar_ok`、`java_ok`、`graphviz_ok`（均检测便携资源是否可用）。

---

## 八、测试计划

| 用例 | 类型 |
|------|------|
| 12 张类图批量渲染 | 单元 / 集成 |
| 明确「合并类图」→ 仅 1 张含多类 | Prompt 黄金样例（`tests/fixtures/`） |
| 状态图 / ER / 部署 PlantUML 样例渲染 | 集成 |
| DFD JSON → PNG 符号正确（仅便携 `dot`，无系统 Graphviz） | 单元 + 人工目检 |
| 便携 `graphviz/` 缺失 → 明确报错 | 单元 |
| `fill_report` 插图不进 `objective` | 单元（mock section_map） |
| `uml_consistency` 对 ER 实体名 | 单元 |

---

## 九、风险与约束

1. **LLM 胡写 PlantUML**：靠 preflight + 示例 + 一致性检查缓解；DFD 用结构化 JSON 降低风险。  
2. **12 张图填 Word 体积**：可接受；必要时压缩 PNG（后置）。  
3. **便携 Graphviz 体积与 DLL**：须整包保留 `bin` + `lib`，不能只拷 `dot.exe`；安装包增大约 5–15 MB。  
4. **跨平台**：首发 Windows x64 便携包；macOS/Linux 后续可增 `assets/graphviz-{platform}/` 或构建时按平台拉取。  
5. **工具箱范围**：符合 D6 — 已支持 #5 批量渲染（含 DFD），**不**做 Agent 级分节插图编排。  

---

## 十、文档与 Backlog 挂钩

实现启动时建议：

1. 在 [NEXT_VERSION_BACKLOG.md](../product/NEXT_VERSION_BACKLOG.md) 增加条目 **「图表扩展 DG1–DG3」** 指向本文。  
2. [IMPLEMENTATION_PHASES.md](../architecture/IMPLEMENTATION_PHASES.md) 新增一节「Phase DG」。  
3. ~~完成后更新 `CLAUDE.md` 目录说明中的 `uml_render.py` 描述为「图表渲染（PlantUML + DFD）」。~~ ✅

---

## 十一、决策记录

| 日期 | 决策 |
|------|------|
| 2026-06-05 | 上限 12；默认分图；合并听报告；优先状态/ER/部署；标准 DFD 独立做；插图 Agent 决策、禁止实验目的 |
| 2026-06-05 | DFD 采用 **便携 Graphviz**（`assets/graphviz/`），不要求用户安装；系统 PATH 仅作开发兜底 |
| 2026-06-05 | 工具箱 #5 升级为图表渲染（diagrams 数组 + DFD + 引擎状态栏）；D6 细化为「Agent 编排 / 工具箱渲染」分工 |

---

*本文档为产品与技术对齐用；具体 PR 可按 Phase A → B → C 拆分。*
