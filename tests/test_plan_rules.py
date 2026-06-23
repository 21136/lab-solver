"""IR-22: declarative plan rule chain."""

from agent.plan_rules import (
    PlanRuleContext,
    apply_post_llm_plan_rules,
    apply_question_type_plan_rules,
)


def test_v4_pipeline_demotes_run_code():
    steps = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True, "reason": "复验"},
    ]
    result = apply_post_llm_plan_rules(
        steps,
        settings={"solvePipelineVersion": "v4"},
        report_text="三、实验步骤 编写 Java",
    )
    assert "v4_pipeline_demote_run_code" in result.rules_applied
    run_code = next(s for s in result.steps if s["module"] == "run_code")
    assert run_code["default_checked"] is False


def test_code_cloze_rule_replaces_lab_steps():
    steps = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True},
    ]
    metadata = {
        "question_type": "code_cloze",
        "code_cloze": {"is_code_cloze": True, "blank_count": 3},
    }
    result = apply_question_type_plan_rules(steps, metadata=metadata, question_type="code_cloze")
    assert "code_cloze" in result.rules_applied
    mods = [s["module"] for s in result.steps]
    assert "solve_code_cloze" in mods
    assert "solve_lab" not in mods
    assert "present_deliverable" in mods


def test_mixed_assignment_rule():
    steps = [{"module": "solve_lab", "default_checked": True}]
    metadata = {
        "mixed_assignment": True,
        "assignment_questions": [
            {"id": 1, "type": "theory", "title": "Q1", "full_text": "简答1"},
            {"id": 2, "type": "theory", "title": "Q2", "full_text": "简答2"},
        ],
    }
    result = apply_post_llm_plan_rules(steps, settings={}, report_text="", metadata=metadata)
    assert "mixed_assignment" in result.rules_applied
    assert any(s["module"] == "solve_theory" for s in result.steps)
    assert result.steps[-1]["module"] == "present_deliverable"
