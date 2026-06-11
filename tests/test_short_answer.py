"""Short-answer (theory Q&A) detection and planning."""

from agent.parse_documents import detect_short_answer
from agent.planner import apply_question_type_overrides, adjust_plan_for_short_answer


def test_detect_short_answer_numbered_paste():
    text = """1. 什么是软件工程？
请简述。

2. 瀑布模型的优缺点是什么？

3. 敏捷开发与瀑布模型的主要区别？
"""
    assert detect_short_answer(text, metadata={"inline_paste": True}) is True


def test_detect_short_answer_rejects_lab_report_keywords():
    text = """1. 编写程序实现排序
2. 记录实验步骤
3. 粘贴运行结果截图说明
"""
    assert detect_short_answer(text, metadata={"inline_paste": True}) is False


def test_adjust_plan_for_short_answer():
    steps = adjust_plan_for_short_answer([], metadata={"question_type": "short_answer"})
    modules = [s["module"] for s in steps]
    assert modules == ["solve_short_answer", "present_deliverable"]


def test_build_deliverable_theory_type():
    from modules.deliverable import build_deliverable

    ctx = {
        "module_results": {
            "solve_short_answer": {
                "ok": True,
                "data": {
                    "type": "short_answer",
                    "answer": "**第1题**\n答案一\n\n**第2题**\n答案二",
                },
            },
        },
        "user_constraints": [],
    }
    dlv = build_deliverable(ctx)
    assert dlv["type"] == "theory"
    assert dlv["sections"]["answer"].startswith("**第1题**")
    assert dlv["execution"]["validation_status"] == "not_requested"


def test_apply_question_type_overrides_short_answer():
    plan = apply_question_type_overrides(
        {"steps": [{"module": "solve_lab", "params": {}}], "decision_log": []},
        metadata={"question_type": "short_answer"},
    )
    modules = [s["module"] for s in plan["steps"]]
    assert "solve_short_answer" in modules
    assert "present_deliverable" in modules
