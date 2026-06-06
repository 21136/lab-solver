# V2 动态分节工作台

**用途**：把分节工作台从固定 4 节（封面/步骤/结果/总结）改为根据文档实际结构动态生成。  
**状态**：L0 ✅ 完成、L1 ✅ 完成、L2 ✅ 完成、L3 ✅ 完成（2026-06-05）  
**最后更新**：2026-06-05

---

## 一、问题

当前分节工作台硬编码 4 行：

```js
SECTION_ROW_DEFS = [
  { id: 'cover',   label: '封面 / 表头' },
  { id: 'steps',   label: '三、实验内容及步骤' },
  { id: 'result',  label: '四、实验结果' },
  { id: 'summary', label: '五、实验总结' },
];
```

无论上传的文档实际包含什么节，用户永远看到这 4 行。问题：

1. **多出的节不可见** — 文档有"实验目的""实验原理""讨论"等节时，UI 中不存在，用户无法控制填不填
2. **少了的节是噪音** — 文档只有 2 节时，多出 2 行无意义
3. **训练表格报告** — `training_table` 根本没有"节"的概念，仍然显示 4 行固定行，文不对题
4. **封面概念模糊** — "封面/表头"是一个特殊节（默认 skip），但有些文档没有封面表头，有些文档的表头信息在表格里

## 二、设计决策

| 决策 | 结论 |
|------|------|
| 语义角色 | **保留并扩展**。检测到的每个节自动映射语义角色（见 §2.2），用户可手动修正 |
| 训练表格 | **完全独立 UI**。`report_layout === 'training_table'` 时渲染填表预览面板，不显示分节行 |
| 封面概念 | **取消**。不再有特殊 `cover` 节。文档开头无标题的内容自动归入第一个检测到的节或"前言" |
| LLM prompt | **不改**。solve_lab 仍然输出 `steps_analysis`/`result_description`/`summary`。扩展的节（目的/原理/讨论）通过 fill_report 的"other"路径单独处理 |

### 2.1 为什么要保留语义角色而不是完全自由？

如果完全不给 LLM 语义提示，AI 拿到"二、实验原理"和"四、实验心得"这两个节时，无法区分哪个该填分析哪个该填反思。语义角色是 LLM 生成正确内容的关键约束。

扩展后的语义角色表：

| 语义角色 | 中文标签 | LLM 输出字段 | 说明 |
|----------|----------|-------------|------|
| `objective` | 实验目的 | —（从 `assignment_text` 解析；无题目时 other/回退） | 新增 |
| `principles` | 实验原理 | —（other 路径生成） | 新增 |
| `steps` | 实验步骤 | `steps_analysis` | 已有 |
| `result` | 实验结果 | `result_description` | 已有 |
| `summary` | 实验总结 | `summary` | 已有 |
| `discussion` | 讨论/思考题 | —（other 路径生成） | 新增 |
| `appendix` | 附录 | —（不填或 other） | 新增 |
| `other` | 未知类型 | —（other 路径生成） | 新增 |

## 三、层次化改动方案

### L0 — 检测层（`fill_report.py` → `parse_report.py`）

**目标**：`detect_sections()` 不丢弃非标准节。

**现状**：`_build_section_map()` 只保留 `semantic in {steps, result, summary}` 的条目。

**改动**：

```python
# 新返回结构
sections_detected = [
    {"index": 0, "heading": "一、实验目的",   "semantic": "objective"},
    {"index": 3, "heading": "二、实验原理",   "semantic": "principles"},
    {"index": 8, "heading": "三、实验步骤",   "semantic": "steps"},
    {"index": 15, "heading": "四、实验结果",  "semantic": "result"},
    {"index": 22, "heading": "五、实验心得",  "semantic": "summary"},
]
```

- 有语义的就标上，没有的标 `null`
- `section_map` 查找表仍然返回（下游兼容），但增加 `sections_detected` 完整列表
- `_SEMANTIC_KEYWORDS` 扩展关键词覆盖新角色

**文件**：`fill_report.py`、`parse_report.py`  
**代码量**：±20 行  
**风险**：低。下游用 `section_map.get("steps")` 的代码不受影响。

### L1 — 数据结构层（`sections_config.py` + `server.py`）

**目标**：`fill_scope["sections"]` 不再固定 5 个 key。

**现状**：`_default_fill_scope()` 返回 `{"cover": "skip", "steps": "auto", ...}`。

**改动**：

- `SECTION_IDS` 元组删除
- `_default_fill_scope()` 改为接受 `sections_detected` 参数，动态生成默认 fill_scope
- `normalize()` 的 whitelist `if sid in ("cover", "steps", ...)` 改为接受任意 sid
- `sections_summary_for_prompt()` 去掉"默认：三四五由 AI 填写"的 hardcode 文案
- 默认 fill_mode 逻辑：`steps/result/summary` → auto，其余 → skip

**文件**：`sections_config.py`、`server.py`（返回 sections_detected 给前端）  
**代码量**：±40 行  
**风险**：低。下游调用 `normalize()` 后仍然通过 `.get("sections")` 使用。

### L2 — 前端 UI（`app.js`）

**目标**：分节工作台动态行 + 训练表格独立 UI。

**2a. 动态行生成**

- `SECTION_ROW_DEFS` 删除
- `buildDefaultSectionsConfig()` 改为从 `agentSectionsDetected` 生成
- `estimateSectionCharCounts()` 改为用后端返回的节边界（`sections_detected[].index`），不再硬编码 `三/四/五` 正则
- `renderSectionsWorkbench()` — 已经能处理任意 `sections` 数组，核心逻辑不需大改
- 语义 override 下拉框增加新角色选项（目的/原理/讨论/附录/未知）

**2b. 训练表格独立 UI**

```js
if (agentReportLayout === 'training_table') {
  renderTrainingTablePanel(agentTableMap);  // 新函数
  return;  // 不渲染分节行
}
```

训练表格面板展示：
- 检测到的表格结构预览（哪个表格、哪些行是 fill target）
- 每个 fill target 一个开关：填 / 不填 / 用我的内容
- 简化操作：不需要"智能解析本段""附件"等段落式分节的功能

**2c. 取消封面概念**

- `cover` 不再出现在节列表中
- 原"封面表头"区域的内容（课程名称、姓名等）已在 metadata 中，不影响 Planner

**文件**：`app.js`  
**代码量**：±120 行（重写 `buildDefaultSectionsConfig` + `getDynamicSectionRowDefs` + 新增 `renderTrainingTablePanel` + 简化 `estimateSectionCharCounts`）  
**风险**：中。前端是改动最大的地方，但 4 个核心渲染函数已经设计得比较通用。

### L3 — 语义角色扩展（后端 5 个模块）

**目标**：填充循环支持 steps/result/summary 之外的节。

**3a. `fill_report.py`**

- `fill_lab()` — 主填充循环从 `for key in ("steps", "result", "summary")` 改为 `for sec in sections_detected`
- 对于 `semantic in {steps, result, summary}` 的节：走现有 fill_content 路径
- 对于 `semantic in {objective, principles, discussion, other}` 的节：调用一次 LLM 生成该节内容 → `_replace_section` 写入
- `_build_fill_hints()` — 改为用列表而非固定 3-key dict

**3b. `template_analyzer.py`**

- `_SECTION_KEYS` → 改为接受列表参数，或去掉硬编码，从 `sections_detected` 推导
- 节特殊逻辑（"result"需要图、"steps"可能有代码）→ 改为按 semantic 查表，而非硬编码

**3c. `sections_config.py`**

- `SECTION_IDS` 删除
- `_default_fill_scope()` 动态生成

**3d. `executor_dirty.py`**

- `GROUP_TO_MODULES` — 保留 `steps/result/summary` 三个主组不变（对应 solve_lab 的三个输出字段）。新增的 other 节不参与 dirty_modules 追踪（它们的内容由独立的 fill 调用生成，不在 solve_lab 输出中）
- `SCOPE_TO_GROUPS` — 同理不变

**3e. `quality.py`**

- `section_fields` → 改为从实际 sections_detected 构建

**文件**：5-6 个  
**代码量**：±80 行  
**风险**：中。fill_report 填充循环是核心路径。

### L4 — 深层耦合（LLM prompt 层，不改）

**目标**：不改 solve_lab prompt，只在填表路径扩展。

**策略**：

LLM prompt 中的 `steps_analysis` / `result_description` / `summary` 字段**保持不变**。这些是 AI 解题的核心输出结构，改动风险太高。

对于 semantic 不在 {steps, result, summary} 的节（如"实验原理""讨论"），填表时单独调用 LLM：

```
你是一名大学课程助教。请为以下实验报告的「{heading}」节撰写内容。

【作业要求】
{planner_input_text}

【该节原文（如有）】
{section_original_text}

【AI 已生成的解题内容（供参考）】
{steps_analysis + result_description + summary}

请输出该节的完整内容（直接可填入 Word 的中文段落）。
```

这样不需要改 solve_lab prompt JSON schema，不需要改 planner，不需要改 preflight/reflect/revise 的任何逻辑。

**文件**：无改动（仅 `fill_report.py` 中新增一个辅助函数调用 LLM）  
**代码量**：+30 行  
**风险**：低。这是新增路径，不影响现有流程。

## 四、数据流

```
用户上传 docx
  │
  ▼
parse_report_route()
  ├── detect_sections(paragraphs)     # L0: 现在返回完整 sections_detected[]
  ├── detect_docx_sections(path)      # L1: section_map + sections_detected + fill_hints
  └── 返回前端 { sections_detected, section_map, report_layout, table_map }
        │
        ▼
前端 app.js
  ├── report_layout === 'training_table'
  │     └── renderTrainingTablePanel()    # L2: 独立 UI
  │
  └── report_layout !== 'training_table'
        └── buildDefaultSectionsConfig()   # L2: 从 sections_detected 动态生成
              └── renderSectionsWorkbench() # L2: 动态行
                    │
                    ▼ 用户确认 → 生成计划
              POST /api/agent/plan
                    │
                    ▼
              Planner → Executor
                │
                ├── solve_lab 不变        # L4: prompt 不动
                ├── fill_report
                │     ├── semantic ∈ {steps,result,summary} → 现有路径  # L3
                │     └── semantic ∈ other → 单独 LLM 生成              # L4
                └── verify 不变
```

## 五、验收标准

### 功能验收

1. 上传标准三四五文档 → 分节工作台显示 3 行（steps/result/summary），标签为文档中实际标题
2. 上传"目的+原理+步骤+结果+总结"5 节文档 → 显示 5 行，目的/原理默认 skip
3. 上传仅 2 节文档 → 显示 2 行
4. 上传训练表格报告 → 显示填表预览面板（独立 UI），不显示分节行
5. 用户可手动将"实验目的"的语义角色改为"实验步骤"（override）
6. 非标准节选择"AI 填写"后，fill_report 正确生成并写入内容
7. 非标准节选择"不填"后，fill_report 跳过该节
8. 现有标准三四五文档的解题质量不受影响（回归）

### 技术验收

1. 所有现有测试通过（176 个）
2. `section_map` 仍在返回结构中，下游 `.get("steps")` 调用不报错
3. `_default_fill_scope()` 接受的参数签名向后兼容（无 sections_detected 时回退到旧默认值）
4. `normalize()` 对旧格式的 `sections_config` 输入仍然正确处理

## 六、不做

- **不改 solve_lab prompt**（风险太高）
- **不改 planner/understand_plan 的 plan 生成逻辑**（新增的 other 节不产生独立 plan step，在 fill_report 阶段统一处理）
- **不改 react_tools 的工具签名**（ReAct 模式的工具调用保持现有 section 语义）
- **不要求所有未知版式 100% 自动**（语义无法映射的节标为 `other`，用户可手动设置）

## 七、实现记录

### L0 实施 (2026-06-05)

**改动文件**：
- `src/python/modules/fill_report.py`

**实际改动**：
1. `_SEMANTIC_KEYWORDS` — 新增 4 个角色：`objective`（目的/目标/要求）、`principles`（原理/背景/知识/基础）、`discussion`（讨论/思考/问答/问题）、`appendix`（附录/附件/参考/源码）。注意 `discussion` 的关键词与 `summary` 有重叠（"讨论""思考"），由于 dict 保持插入顺序且 `summary` 在前，现有行为不变。
2. `_METADATA_LABELS` — 新增 13 个元数据标签黑名单，`detect_sections()` 中过滤节号前缀匹配到的元数据行（如"一、课程名称"）。
3. `_build_section_map()` — 返回值从 `section_map` 改为 `(section_map, sections_detected)`，保持下游兼容。
4. `detect_sections()` — 解包 `_build_section_map` 的两个返回值；新增元数据标签过滤逻辑。

**未改动**：
- `parse_report.py` `detect_docx_sections()` — 返回结构已包含 `sections_detected`，调用已使用两值解包，无需修改。
- `pdf_export.py` — 调用 `detect_sections()` 已使用两值解包，无需修改。

### L1 实施 (2026-06-05)

**改动文件**：
- `src/python/agent/sections_config.py`

**实际改动**：
1. `SECTION_IDS` → `_LEGACY_SECTION_IDS`（保留兼容引用，不再用于业务逻辑）。
2. `_default_fill_scope()` — 新增可选参数 `sections_detected=None`。传入时动态生成 fill_scope sections（steps/result/summary → auto，其余 → skip）。不传时回退到旧的 5-key 硬编码默认值。
3. `normalize()` — 新增可选参数 `sections_detected=None`，传递给 `_default_fill_scope()`；也从 `cfg.get("sections_detected")` 作为 fallback 来源。whitelist 检查 `if sid in (...)` 已移除，任意 sid 均可写入 `fill_scope["sections"]`。
4. `sections_summary_for_prompt()` — 去掉硬编码 fallback 文案"（默认：三四五由 AI 填写，封面跳过）"，改为返回空字符串。

**未改动**：
- `server.py` — `sections_detected` 在 parse_report 路由中已返回给前端（line 268/346），无需修改。
- 所有 `normalize_sections_config()` 调用方兼容：新参数为可选，不传时行为不变。

### 与设计文档的偏差

1. **`_METADATA_LABELS`** — 设计文档未提到，但用户要求过滤非实验文本行。新增了 13 个常见元数据标签的黑名单。
2. **`discussion` 与 `summary` 关键词重叠** — `discussion` 的 ["讨论", "思考"] 与 `summary` 重叠。由于 `summary` 在 dict 中排在前面，`_guess_semantic()` 对现有文档的映射保持不变。新增的 "问答""问题" 仅在 `summary` 不匹配时生效。

### L2 实施 (2026-06-05)

**改动文件**：
- `src/renderer/app.js`

**实际改动**：

1. **`SEMANTIC_LABEL_MAP`** — 扩展为 8 个语义角色：新增 `objective`（实验目的）、`principles`（实验原理）、`discussion`（讨论/思考题）、`appendix`（附录）、`other`（未知类型）。

2. **`getDynamicSectionRowDefs()`** — 重写：动态模式直接从 `agentSectionsDetected` 构建 row defs（id=`sec_{i}`），fallback 路径保留旧的 `SECTION_ROW_DEFS` + `section_map` 映射。

3. **`estimateSectionCharCountsFromDetected()`** — 新增函数：在 `fullText` 中搜索每个 section heading 的位置，按位置分区计算字数。第一节之前的内容归入第一节（替代原 cover 概念）。

4. **`buildDefaultSectionsConfig()`** — 重写：数据源改为 `agentSectionsDetected`。核心 semantic（steps/result/summary）默认 `auto`，其余默认 `skip`。存储 `_semantic` 和 `_label` 元数据。`agentSectionsDetected` 为空时 fallback 到旧 4 行模板。

5. **`renderSectionsWorkbench()`** — 新增 `training_table` 守卫：`agentReportLayout === 'training_table'` 时调用 `renderTrainingTablePanel()` 并 return。`estimateSectionCharCounts` 调用改为仅 fallback 路径使用。

6. **`renderTrainingTablePanel()`** — 新增函数：从 `agentTableMap` 读取 fill target，每行显示 label + 文本摘录 + mode 下拉框。配置保存在 `agentSectionsConfig._tableFillConfig`。

7. **`renderSectionsDetectCard()`** — 语义 override 下拉框新增 5 个选项（objective/principles/discussion/appendix/other）。fill_hints 合并建议仅在检测到 ≤3 节时显示。

8. **`onSemanticOverride()`** — 新增模式同步：用户改变语义角色时自动更新 `agentSectionsConfig.sections[idx].mode`（核心语义 → auto，非核心 → skip）。

9. **`collectSectionsConfigForApi()`** — section 映射增加 `_semantic` 字段；全局规则写入目标从硬编码 `id === 'summary'` 改为 `_semantic === 'summary'` 查找，fallback 到最后一个 section。新增 `_table_fill` 配置透传。

**架构决策**：

- **节 ID 格式**：动态节使用 `sec_{index}`（如 `sec_0`、`sec_1`），与旧代码中 `cover/steps/result/summary` 字符串 ID 不冲突。可通过 `startsWith('sec_')` 区分动态节。
- **封面取消**：动态路径不再生成 `cover` 节。文档开头无标题的内容通过 `estimateSectionCharCountsFromDetected` 自动归入第一个检测到的节。
- **`SECTION_ROW_DEFS` 保留**：未删除，作为 `agentSectionsDetected` 为空时的 fallback 数据源。
- **训练表格配置**：使用独立的 `_tableFillConfig`（keyed by `t{table}_r{row}_c{col}`），不混入 sections 数组。

**未改动**：
- `app.js` 之外的任何文件
- `agentSectionsDetected`、`agentSectionMap` 等全局变量的赋值逻辑（已在 `applyParseResponse` 中正确赋值）
- Step3 执行流程

### 与设计文档的偏差

1. **`onSemanticOverride` 自动同步模式** — 设计文档未明确要求，但新增了语义角色变更时自动调整 fill mode 的逻辑（core semantic → auto，non-core → skip），避免用户需手动改两处。
2. **`buildSectionsSummaryHtml` 中的 SECTION_ROW_DEFS fallback** — 保留未改，仅在 `getDynamicSectionRowDefs()` 找不到动态 ID 时才回退查询。
3. **`_label` 和 `_semantic` 元数据** — `buildDefaultSectionsConfig` 存储了 `_label` 和 `_semantic` 在 section 条目中，供 `collectSectionsConfigForApi` 和 `buildSectionsSummaryHtml` 使用。设计文档未明确列出，但为实现必需。

### L3 实施 (2026-06-05)

**改动文件**：
- `src/python/modules/fill_report.py`
- `src/python/agent/template_analyzer.py`
- `src/python/agent/sections_config.py`
- `src/python/agent/executor_dirty.py`
- `src/python/agent/quality.py`
- `src/python/agent/executor.py`

**实际改动**：

1. **`fill_report.py`** — 核心改动：
   - 新增 `_CORE_SEMANTICS = frozenset({"steps", "result", "summary"})` 常量。
   - 新增 `_fill_other_section(sec, doc, paras, all_section_indices, ans, *, settings=None)` — 对 non-core 节调用一次 LLM 生成内容，使用 `_replace_section()` 写入。若无 settings/api_key 则跳过并记录日志。Prompt 按设计文档 §4 模版（助教角色 + 作业要求 + 原文 + AI 生成内容参考）。
   - `fill_lab()` — 新增 `sections_detected=None, settings=None` 参数。主填充循环改为迭代 `working_sections`（按文档顺序），core 组走现有 `fill_content` 路径，other 组调用 `_fill_other_section()`。`all_section_indices` 传递给 `_replace_section()` 以正确检测跨语义角色的节边界。
   - `_build_fill_hints()` — 新增 `sections_detected` 参数。仅当 3 个 core 节全部存在且 non-core 节 >= 2 个时跳过 merge 提示；若 core 节缺失则仍生成 merge 提示（与旧行为兼容）。
   - `_replace_section()` — 新增 `all_section_indices` 参数，优先使用全部已知节索引检测边界，fallback 到 section_map 和正则。
   - `do_fill()` — 新增 `settings=None` 参数；从 metadata 提取 `sections_detected` 并传递给 `fill_lab()`。
2. **`template_analyzer.py`** — `build_section_map_from_text()` 和 `analyze_template_text()` 新增可选 `section_keys` 参数，默认值 `_SECTION_KEYS`。`_SECTION_KEYS` 元组保留不动。
3. **`sections_config.py`** — `sections_summary_for_prompt()` 新增可选 `sections_detected` 参数。传入时生成含标题名的丰富摘要（如"一、实验目的 (objective): skip"），否则保持旧格式。
4. **`executor_dirty.py`** — `fill_sections_for_groups()` 新增可选 `ctx` 参数。当 ctx 含 `sections_detected` 且 fill_scope 中 non-core 节 mode=auto 时，将其加入返回的 sections 列表。调用方 `mark_dirty_from_revise()` 已更新传 ctx。
5. **`quality.py`** — `verify_teacher_rules()` 新增可选 `sections_detected` 参数。`section_fields` 从硬编码 4-key dict 改为动态构建：保留 3 个 core 字段，从 sections_detected 追加 non-core 字段。调用方 `verify_answer()` 已更新传 ctx 中的 sections_detected。
6. **`executor.py`** — 两处 `do_fill()` 调用新增 `settings=ctx.get("settings")` 参数传递。

**未改动**：
- `prompts.py`、`planner.py`、`understand_plan.py`、`deep_pipeline.py`、`reflect.py`、`react_tools.py`、`react_loop.py`、`parse_documents.py` — 全部按设计要求不动。
- `GROUP_TO_MODULES`、`SCOPE_TO_GROUPS` — 保留不变，仅追踪 solve_lab 3 个主字段。
- 前端 `app.js` — L2 已完成，L3 不动。

### 与设计文档的偏差（L3）

1. **`_build_fill_hints` merge 跳过条件** — 设计文档说 non-core >= 2 就跳过 merge。实际改为"core 3 节全 present 且 non-core >= 2"才跳过。原因：若文档缺 result 节（如 variant_four_sections.docx），即使有目的/原理等 non-core 节，仍需要 merge_result_into 提示来保证内容不丢失。
2. **`_fill_other_section` 的 settings 为 None 时静默跳过** — 设计文档未明确此行为。实际：当 settings=None 或无 api_key 时，跳过该节并记录日志，不影响 core 节填充。这保证了 server.py 快速解题路径（不传 settings）的向后兼容。
3. **`verify_teacher_rules` 中 cover 字段移除** — L2 取消了封面概念，`section_fields` 不再包含 `"cover": ""`。原 cover 规则因无对应 section 不会被匹配。

---

*文档版本：2026-06-05（L0/L1/L2/L3 已完成）*
