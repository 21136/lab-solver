"""
Planner unit tests (no LLM).

Usage:
  python tests/test_planner.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from agent.planner import (  # noqa: E402
    apply_question_type_overrides,
    adjust_plan_for_code_cloze,
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
from server import app  # noqa: E402
from tests.test_toolbox import SAMPLE_CLOZE_TEXT  # noqa: E402
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


FACADE_CLOZE_TEXT = """
( 1 ) AbstractFacade {
    public abstract void execute(String fileName);
}

class XMLFacade extends AbstractFacade {
    public void execute(String fileName){
        String str = ( 2 );
        String strResult = ( 3 );
        ( 4 );
    }
}
""".strip()

DIRTY_LAB_PLAN_STEPS = [
    {"module": "solve_lab", "params": {"language": "java"}, "default_checked": True},
    {"module": "run_code", "params": {}, "default_checked": True},
    {"module": "present_deliverable", "params": {}, "default_checked": True},
]


def _assert_code_cloze_plan_only(steps: list) -> None:
    modules = [s["module"] for s in steps]
    assert modules == ["solve_code_cloze", "present_deliverable"]
    assert "solve_lab" not in modules
    assert "run_code" not in modules


def test_adjust_plan_for_code_cloze_singleton():
    metadata = {
        "code_cloze": {"is_code_cloze": True, "blank_count": 3, "language_hint": "java"},
        "question_type": "code_cloze",
    }
    out = adjust_plan_for_code_cloze(DIRTY_LAB_PLAN_STEPS, metadata=metadata)
    _assert_code_cloze_plan_only(out)
    assert out[0]["params"].get("language") == "java"


def test_adjust_plan_for_code_cloze_facade():
    from modules.code_cloze import detect_code_cloze

    probe = detect_code_cloze(FACADE_CLOZE_TEXT)
    assert probe.get("is_code_cloze") is True
    metadata = {
        "code_cloze": probe,
        "question_type": "code_cloze",
    }
    out = adjust_plan_for_code_cloze(DIRTY_LAB_PLAN_STEPS, metadata=metadata)
    _assert_code_cloze_plan_only(out)


@patch("server.plan_from_report")
def test_agent_plan_paste_singleton_overrides_dirty_llm_plan(mock_plan):
    """BF47: stale question.type + pasted cloze text → cloze plan at API boundary."""
    mock_plan.return_value = {
        "steps": list(DIRTY_LAB_PLAN_STEPS),
        "clarifications": [{"question": "需要运行代码吗？"}],
        "plan_fingerprint": "dirty-fp",
        "decision_log": [],
        "prompt_version": "test",
    }
    client = app.test_client()
    resp = client.post(
        "/api/agent/plan",
        json={
            "api_key": "sk-test",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "report_text": "占位报告正文",
            "assignment_text": SAMPLE_CLOZE_TEXT,
            "question": {"type": "lab_report"},
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    _assert_code_cloze_plan_only(data["steps"])
    mock_plan.assert_called_once()


@patch("server.plan_from_report")
def test_agent_plan_paste_facade_overrides_dirty_llm_plan(mock_plan):
    mock_plan.return_value = {
        "steps": list(DIRTY_LAB_PLAN_STEPS),
        "clarifications": [],
        "plan_fingerprint": "dirty-fp",
        "decision_log": [],
        "prompt_version": "test",
    }
    client = app.test_client()
    resp = client.post(
        "/api/agent/plan",
        json={
            "api_key": "sk-test",
            "report_text": "占位",
            "assignment_text": FACADE_CLOZE_TEXT,
            "question": {"type": "lab_report"},
        },
    )
    assert resp.status_code == 200
    _assert_code_cloze_plan_only(resp.get_json()["steps"])


def test_plan_from_report_requires_key():
    try:
        plan_from_report("x", settings={})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "API Key" in str(e)


def test_plan_from_report_decision_log_contains_source():
    fake = {
        "content": """
{
  "steps": [
    {
      "module": "solve_lab",
      "params": {"language": "java"},
      "reason": "需要编程",
      "source": "llm",
      "confidence": "high",
      "default_checked": true
    }
  ],
  "clarifications": []
}
""",
        "reasoning_content": "",
    }
    with patch("llm_client.chat", return_value=fake):
        plan = plan_from_report(
            "三、实验步骤\n实现算法",
            settings={"api_key": "sk-test", "provider": "deepseek", "model": "deepseek-chat"},
            profile={"default_language": "java"},
            metadata={},
        )
    log = plan.get("decision_log") or []
    assert any(e.get("decision") == "plan_pipeline_stage" for e in log)
    generated = next(e for e in log if e.get("decision") == "plan_generated")
    assert generated.get("source") == "planner"


def test_apply_question_type_overrides_code_cloze():
    base_plan = {
        "steps": list(DIRTY_LAB_PLAN_STEPS),
        "clarifications": [{"question": "x"}],
        "decision_log": [],
        "plan_fingerprint": "fp-test",
    }
    out = apply_question_type_overrides(
        base_plan,
        metadata={"question_type": "code_cloze", "code_cloze": {"is_code_cloze": True, "blank_count": 2}},
        question_type="code_cloze",
    )
    _assert_code_cloze_plan_only(out["steps"])
    assert out["clarifications"] == []
    assert any(e.get("decision") == "plan_override" for e in (out.get("decision_log") or []))


def test_apply_question_type_overrides_mixed_assignment():
    base_plan = {
        "steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
        "clarifications": [{"question": "x"}],
        "decision_log": [],
        "plan_fingerprint": "fp-test",
    }
    metadata = {
        "mixed_assignment": True,
        "assignment_questions": [
            {"id": 1, "type": "theory", "title": "简答", "full_text": "说明操作系统"},
            {"id": 2, "type": "code_cloze", "title": "填空", "full_text": "class A {(1)}"},
        ],
    }
    out = apply_question_type_overrides(base_plan, metadata=metadata, question_type="mixed_assignment")
    assert [s["module"] for s in out["steps"]] == ["solve_theory", "solve_code_cloze", "present_deliverable"]
    assert out["clarifications"] == []
    assert any(
        e.get("decision") == "plan_override" and e.get("target") == "mixed_assignment"
        for e in (out.get("decision_log") or [])
    )


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
    test_plan_from_report_decision_log_contains_source()
    test_apply_question_type_overrides_code_cloze()
    test_apply_question_type_overrides_mixed_assignment()
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
