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
    compute_plan_fingerprint,
    normalize_plan,
    parse_plan_json,
    plan_from_report,
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
    profile = {"default_language": "java", "screenshot_style": "ide", "prefer_uml": False}
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
    print("test_planner: OK")


if __name__ == "__main__":
    main()
