"""
Phase 2b unit tests (no LLM).

Usage:
  python tests/test_phase2b.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.quality import (  # noqa: E402
    check_plagiarism,
    extract_numbers,
    verify_answer,
)
from agent.reflect import _issues_fingerprint  # noqa: E402
from agent.executor_dirty import (  # noqa: E402
    apply_revise_to_module_results,
    compute_sub_fingerprints,
    downstream_modules_for_groups,
    fill_sections_for_groups,
    mark_dirty_from_revise,
    should_rerun_module,
)
from modules.preflight import run_preflight  # noqa: E402


def test_extract_numbers():
    assert 3.14 in extract_numbers("pi=3.14 area=100")
    assert extract_numbers("") == []


def test_plagiarism_warn():
    tpl = "A" * 50 + "实验步骤详细说明" + "B" * 50
    gen = "前缀" + "实验步骤详细说明" + "后缀" * 20
    r = check_plagiarism(gen, tpl, min_chunk=10, ratio_threshold=0.3)
    assert "ratio" in r


def test_preflight_python_ok():
    data = {
        "parsed": {
            "steps_analysis": "步骤",
            "result_description": "结果",
            "summary": "总结",
            "code": "print(1)",
        },
        "code": "print(1)",
        "language": "python",
    }
    pf = run_preflight(data)
    assert pf["ok"] is True


def test_preflight_python_syntax_fail():
    data = {
        "parsed": {
            "steps_analysis": "x",
            "result_description": "x",
            "summary": "x",
            "code": "def (",
        },
        "code": "def (",
        "language": "python",
    }
    pf = run_preflight(data)
    assert pf["ok"] is False
    assert "code_syntax" in pf.get("failed_ids", [])


def test_verify_schema():
    ctx = {
        "confirmed_steps": [{"module": "solve_lab", "default_checked": True}],
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {
                    "type": "lab_report",
                    "parsed": {
                        "steps_analysis": "a",
                        "result_description": "b",
                        "summary": "c",
                        "code": "print(1)",
                    },
                    "code": "print(1)",
                },
            }
        },
    }
    report = verify_answer(ctx)
    assert "checks" in report
    assert any(c["id"] == "schema_complete" for c in report["checks"])


def test_issues_fingerprint_stable():
    issues = [{"field": "summary", "message": "太短"}]
    assert _issues_fingerprint(issues) == _issues_fingerprint(list(issues))


def test_sub_fingerprints_stable():
    data = {
        "parsed": {
            "steps_analysis": "步骤",
            "result_description": "结果",
            "summary": "总结",
            "code": "print(1)",
            "language": "python",
        },
        "code": "print(1)",
        "language": "python",
    }
    a = compute_sub_fingerprints(data)
    b = compute_sub_fingerprints(dict(data))
    assert a == b
    assert a["summary"] != a["code"]


def test_revise_summary_skips_run():
    solve = {
        "type": "lab_report",
        "parsed": {
            "steps_analysis": "步骤",
            "result_description": "结果",
            "summary": "旧总结",
            "code": "print(1)",
            "language": "python",
        },
        "code": "print(1)",
        "language": "python",
    }
    ctx = {
        "module_results": {
            "solve_lab": {"ok": True, "data": solve, "sub_fingerprints": compute_sub_fingerprints(solve)},
            "run_code": {"ok": True, "data": {"output": "1", "is_error": False}},
            "fill_report": {"ok": True, "data": {"output_path": "/tmp/x.docx"}},
        },
        "dirty_modules": [],
    }
    solve2 = dict(solve)
    solve2["parsed"] = {**solve["parsed"], "summary": "新总结更长"}
    apply_revise_to_module_results(ctx, solve2, changed_fields=["summary"])
    dirty = mark_dirty_from_revise(ctx, changed_fields=["summary"], scope=["summary"])
    assert "fill_report" in dirty
    assert "run_code" not in dirty
    assert not should_rerun_module(ctx, "run_code")
    assert should_rerun_module(ctx, "fill_report")
    assert fill_sections_for_groups({"summary"}) == ["summary"]


def test_revise_code_marks_run():
    dirty = downstream_modules_for_groups({"code"})
    assert "run_code" in dirty
    assert "fill_report" in dirty


if __name__ == "__main__":
    test_extract_numbers()
    test_plagiarism_warn()
    test_preflight_python_ok()
    test_preflight_python_syntax_fail()
    test_verify_schema()
    test_issues_fingerprint_stable()
    test_sub_fingerprints_stable()
    test_revise_summary_skips_run()
    test_revise_code_marks_run()
    print("test_phase2b: OK")
