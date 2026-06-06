"""
Planner unit tests (no LLM).

Usage:
  python tests/test_planner.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.planner import (  # noqa: E402
    adjust_plan_for_skip_validation,
    adjust_plan_for_v4_pipeline,
    adjust_plan_theory_only,
    adjust_plan_v4_aware,
    compute_plan_fingerprint,
    enrich_low_confidence_steps,
    normalize_plan,
    parse_plan_json,
    plan_from_report,
    report_needs_code,
    _fallback_plan,
    _render_uml_reason_evidence,
)
from agent.prompts import render_plan_prompt  # noqa: E402


def test_parse_plan_json():
    raw = """
```json
{
  "steps": [
    {
      "module": "solve_lab",
      "params": {"language": "python"},
      "reason": "需要编程",
      "evidence": "三、实验步骤 编写程序",
      "source": "report",
      "confidence": "high",
      "default_checked": true
    }
  ],
  "clarifications": []
}
```
"""
    obj = parse_plan_json(raw)
    assert len(obj.get("steps", [])) == 1
    assert obj["steps"][0]["module"] == "solve_lab"


def test_normalize_plan_filters_unknown():
    profile = {"default_language": "java", "prefer_uml": False}
    steps, clar = normalize_plan(
        {
            "steps": [
                {"module": "solve_lab", "params": {}, "reason": "r", "evidence": "e"},
                {"module": "automate_app", "params": {}},
            ]
        },
        profile,
    )
    assert len(steps) == 1
    assert steps[0]["module"] == "solve_lab"
    assert clar == []


def test_fingerprint_stable():
    steps = [{"module": "solve_lab", "params": {"language": "java"}, "default_checked": True}]
    a = compute_plan_fingerprint("hello", steps)
    b = compute_plan_fingerprint("hello", steps)
    assert a == b
    assert a.startswith("sha256:")


def test_render_plan_prompt():
    p = render_plan_prompt("实验报告正文", {"default_language": "java"})
    assert "实验报告正文" in p
    assert "solve_lab" in p


def test_render_plan_prompt_v4_block():
    p = render_plan_prompt(
        "实验报告正文",
        {"default_language": "java"},
        v4_pipeline=True,
        skip_validation=True,
    )
    assert "V4" in p
    assert "skip_validation" in p


def test_report_needs_code():
    assert report_needs_code("请用 Java 实现 FIFO 页面置换")
    assert not report_needs_code("简述操作系统进程与线程的区别")


def test_adjust_plan_theory_only_drops_run_code():
    steps = [
        {"module": "solve_lab", "params": {}, "reason": "r", "default_checked": True},
        {"module": "run_code", "params": {}, "reason": "r", "default_checked": True},
        {"module": "render_uml", "params": {}, "reason": "r", "default_checked": False},
    ]
    out = adjust_plan_theory_only(steps, "一、实验目的\n二、思考题")
    mods = [s["module"] for s in out]
    assert "solve_lab" in mods
    assert "run_code" not in mods
    assert "render_uml" not in mods


def test_adjust_plan_skip_validation():
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
    ]
    out = adjust_plan_for_skip_validation(steps, ["skip_validation"])
    assert [s["module"] for s in out] == ["solve_lab"]


def test_adjust_plan_v4_demotes_run_code():
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "reason": "复验", "default_checked": True},
    ]
    out = adjust_plan_for_v4_pipeline(steps, {"solvePipelineVersion": "v4"})
    run = next(s for s in out if s["module"] == "run_code")
    assert run["default_checked"] is False
    assert "内化验证" in run["reason"]


def test_enrich_low_confidence_steps():
    steps = [
        {
            "module": "render_uml",
            "params": {},
            "confidence": "low",
            "reason": "报告提及类图",
            "default_checked": True,
        }
    ]
    out = enrich_low_confidence_steps(steps)
    assert out[0]["default_checked"] is False
    assert "置信度较低" in out[0]["reason"]


def test_adjust_plan_v4_aware_combined():
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
    ]
    out = adjust_plan_v4_aware(
        steps,
        {"solvePipelineVersion": "v4"},
        "纯理论思考题",
        ["skip_validation"],
    )
    assert [s["module"] for s in out] == ["solve_lab"]


def test_plan_from_report_requires_key():
    try:
        plan_from_report("x", settings={})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "API Key" in str(e)


def test_fallback_plan_lab():
    steps = _fallback_plan("三、实验步骤\n四、实验结果\n需要截图和代码", {}, False)
    modules = [s["module"] for s in steps]
    assert "solve_lab" in modules
    assert "present_deliverable" in modules
    assert "fill_report" not in modules


def test_fallback_plan_uml_reason_lists_kinds():
    text = "三、实验步骤\n请画出六个设计模式的类图，并补充时序图。\n四、实验结果"
    dneeds = {
        "needs_uml": True,
        "needs_dfd": False,
        "kinds": ["类图", "时序图"],
        "evidence": "六个设计模式的类图",
    }
    steps = _fallback_plan(text, {}, True, dneeds)
    uml_steps = [s for s in steps if s["module"] == "render_uml"]
    assert len(uml_steps) == 1
    assert "类图" in uml_steps[0]["reason"]
    assert "时序图" in uml_steps[0]["reason"]
    assert uml_steps[0]["evidence"] == "六个设计模式的类图"


def test_render_uml_reason_evidence_default_independent():
    reason, _ = _render_uml_reason_evidence(
        {"needs_uml": True, "kinds": ["类图"], "evidence": "类图"}
    )
    assert "独立" in reason


def main():
    test_parse_plan_json()
    test_normalize_plan_filters_unknown()
    test_fingerprint_stable()
    test_render_plan_prompt()
    test_plan_from_report_requires_key()
    test_fallback_plan_lab()
    test_fallback_plan_uml_reason_lists_kinds()
    test_render_uml_reason_evidence_default_independent()
    test_render_plan_prompt_v4_block()
    test_report_needs_code()
    test_adjust_plan_theory_only_drops_run_code()
    test_adjust_plan_skip_validation()
    test_adjust_plan_v4_demotes_run_code()
    test_enrich_low_confidence_steps()
    test_adjust_plan_v4_aware_combined()
    print("test_planner: OK")


if __name__ == "__main__":
    main()
