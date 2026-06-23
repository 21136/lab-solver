# Golden fixtures

## Phase 1.2 — 解析回归（3+4 份 docx）

| File | Role |
|------|------|
| `programming_lab.docx` | Programming-focused report |
| `theory_lab.docx` | Theory / analysis report |
| `combined_lab.docx` | Mixed requirements + code |
| `training_table.docx` | 实训周表格型报告 |
| `lab_report_table.docx` | 超星式表格报告 |
| `variant_four_sections.docx` | 四节变体 |
| `variant_three_sections.docx` | 三节变体 |
| `code_cloze_singleton.docx` | Singleton 代码填空（R5 / `code_cloze` Word 导入金样本） |
| `mixed_theory_cloze.docx` | 简答 + Singleton 填空混排（R8 / O10 金样本） |

Regenerate:

```bash
python tests/generate_fixtures.py
```

Run parse regression (no LLM):

```bash
python tests/run_golden_regression.py
```

---

## V4 解题金样本 — `solve_v4/`（AO-2，2026-06-06）

10 份简单实验 docx + `manifest.json`（含 mock LLM 响应与期望 `code_status`）。

| ID | 题型 | 期望 code_status |
|----|------|------------------|
| 01_fifo_lru | Java FIFO/LRU | verified |
| 02_factory_singleton | Java 工厂 | verified |
| 03_thread_join | Java 多线程 | verified |
| 04_sort_c | C 排序 | verified |
| 05_file_io_python | Python 文件 IO | verified |
| 06_theory_only | 纯理论 | skipped |
| 07_web_simulation | Java Web 模拟 | verified |
| 08_multifile_java | Java 多文件 | verified |
| 09_linked_list_cpp | C++ 链表 | verified |
| 10_no_emoji | Java 无 emoji | verified |

Regenerate:

```bash
python tests/fixtures/solve_v4/gen_fixtures.py
```

Run tests:

```bash
# CI 默认：mock LLM（无运行时则 verified 题断言 skipped）
python -m pytest tests/test_solve_pipeline_golden.py -v

# 本地可选：真 sandbox 通过率基线
python -m pytest tests/test_solve_pipeline_golden.py -m golden_sandbox -s
```

详见 [docs/architecture/AGENT_OPTIMIZATION_PLAN.md](../../docs/architecture/AGENT_OPTIMIZATION_PLAN.md) §9.1。

---

## IR-18 — Agent plan→run 矩阵 E2E（mock LLM）

| Case ID | Fixture | 题型 / 布局 |
|---------|---------|-------------|
| `programming_lab` | `programming_lab.docx` | 编程实验 |
| `code_cloze_singleton` | `code_cloze_singleton.docx` | 代码填空 |
| `theory_lab` | `theory_lab.docx` | 理论分析（剔除 run_code） |
| `training_table` | `training_table.docx` | 实训表格 → short_answer |
| `mixed_theory_cloze` | `mixed_theory_cloze.docx` | 混排简答 + 填空 |

```bash
python -m pytest tests/test_agent_fixture_e2e.py -v
```

---

## 统一入口

```bash
python -m pytest
scripts\run-tests.bat
```
