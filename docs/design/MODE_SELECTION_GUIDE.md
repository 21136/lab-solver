# Agent 模式与质量档位选择指南

**版本**: 2026-06-09  
**状态**: ✅ IR-13a  
**关联**: [STANDARD_MODE_QUALITY.md](STANDARD_MODE_QUALITY.md) · [AGENT_IMPROVEMENT_RECOMMENDATIONS.md](../architecture/AGENT_IMPROVEMENT_RECOMMENDATIONS.md) § IR-13

---

## 1. 运行模式（run_mode）

| 模式 | 适用场景 | 典型代价 | 不建议 |
|------|----------|----------|--------|
| **standard** | 默认；实验报告、混排卷、需可预期流水线 | V4 约 3～5 次 LLM + 内化沙箱；执行后规则校验 | 需要执行前 LLM 审稿时 |
| **deep** | 长报告、约束多、愿多等 30～60s 换质量 | 在 standard 基础上 +understand +reflect（约 +2～3 LLM） | 赶时间、简单填空/纯简答 |
| **react**（实验） | 计划难覆盖的收尾（UML/交付补跑） | bootstrap V4 + 最多 16 轮 tool 调用 | 生产默认；API 预算紧张 |

**深度 vs 标准**：深度多「执行前审稿」；二者执行尾段均走 `RunOrchestrator` + `verify_answer`。

**ReAct**：需设置中开启「实验：自主选题模式」；适合探索性任务，延迟与费用最高。

---

## 2. 质量档位（solveQualityTier）

与 `run_mode` **独立**；控制 V4 `solve_pipeline` 深度（`modules/solve_pipeline.py` `_TIER_LIMITS`）。

| 档位 | 行为概要 | 约 LLM | 适用 |
|------|----------|--------|------|
| **fast** | 少 fix、可 skip 内化验证、无图表 phase | ~2 | 纯理论、代码完形填空、无编程关键词的简答 |
| **standard** | 默认；内化验证 + 适量 fix/regen | 3～5 | 一般编程实验报告 |
| **thorough** | 多 fix + 同错 regen + 图表 phase | 5+ | Java 多文件、屡次 sandbox 失败 |

### 自动极速（IR-13a）

设置 **`autoFastTierForLightQuestions`**（默认开）时，若用户**未锁定档位**（`solveQualityTierExplicit=false`），且题为轻量题型（`code_cloze`、纯理论、`solve_theory`-only 等），执行期 `resolve_solve_quality_tier` 解析为 `fast`。

用户曾在设置中改过档位 → `solveQualityTierExplicit=true`，始终尊重所选档位。

`deep` / `react` 模式不自动降档。

---

## 3. 并行执行（IR-13b）

`RunOrchestrator` 在计划含相邻无依赖步骤时可并行（需 `enableParallelModuleSteps=true`）：

| 并行组 | 前提 |
|--------|------|
| `run_code` + `render_uml` | `solve_lab` 已完成 |
| `solve_theory` + `solve_code_cloze` | 混排卷相邻两步 |

`present_deliverable` 仍在并行组**之后**顺序执行（需 UML 图时可并入 deliverable）。

---

## 4. 快速决策

```
赶时间 / 填空 / 纯简答     → standard + 自动 fast（或手动选极速）
一般实验报告 + 要代码质量   → standard + 标准档位
老师约束多 / 长报告        → deep + 标准或稳妥
计划难收尾 / 愿意实验      → react（开启实验开关）
编程屡次失败              → thorough 或 deep
```
