"""Plan feedback diff, C2 behavior hints (no LLM)."""

from agent.plan_feedback import compute_plan_diff, record_plan_feedback  # noqa: E402
from agent.prompts import render_plan_prompt  # noqa: E402
from agent.user_profile import (  # noqa: E402
    BEHAVIOR_MIN_SAMPLES,
    apply_behavior_to_steps,
    apply_plan_feedback_to_profile,
    behavior_hints_block,
    normalize_profile,
)


def test_compute_plan_diff_no_change():
    steps = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True},
    ]
    diff = compute_plan_diff(steps, steps)
    assert diff["changed"] is False
    assert diff["toggles"] == []


def test_compute_plan_diff_toggle():
    baseline = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True},
    ]
    confirmed = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": False},
    ]
    diff = compute_plan_diff(baseline, confirmed)
    assert diff["changed"] is True
    assert len(diff["toggles"]) == 1
    assert diff["toggles"][0]["module"] == "run_code"
    assert diff["toggles"][0]["to_checked"] is False


def test_compute_plan_diff_reorder():
    baseline = [
        {"module": "solve_lab"},
        {"module": "run_code"},
    ]
    confirmed = [
        {"module": "run_code"},
        {"module": "solve_lab"},
    ]
    diff = compute_plan_diff(baseline, confirmed)
    assert diff["reordered"] is True
    assert diff["changed"] is True


def test_record_plan_feedback_appends_decision_log():
    baseline = [{"module": "fill_report", "default_checked": True}]
    confirmed = [{"module": "fill_report", "default_checked": False}]
    out = record_plan_feedback(
        baseline,
        confirmed,
        plan_fingerprint="fp_test",
        document_ids=["doc1"],
    )
    assert out["recorded"] is True
    assert out["diff"]["changed"] is True
    entry = out["decision_log_entry"]
    assert entry["agent"] == "user"
    assert entry["decision"] == "plan_feedback"
    assert entry["overridden"] is True
    assert out["history"]["plan_feedback"]["changed"] is True
    assert len(out["history"]["decision_summary"]) >= 1


def test_agent_plan_feedback_route():
    from server import app  # noqa: E402

    client = app.test_client()
    resp = client.post(
        "/api/agent/plan/feedback",
        json={
            "baseline_steps": [{"module": "solve_lab", "default_checked": True}],
            "steps": [{"module": "solve_lab", "default_checked": False}],
            "plan_fingerprint": "abc",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["recorded"] is True
    assert data["diff"]["changed"] is True
    assert data["decision_log_entry"]["decision"] == "plan_feedback"


def test_behavior_cancel_unchecks_after_min_samples():
    profile = normalize_profile({"optimize_plan_from_usage": True})
    diff = {
        "changed": True,
        "toggles": [{"module": "render_uml", "to_checked": False}],
    }
    for _ in range(BEHAVIOR_MIN_SAMPLES):
        profile = apply_plan_feedback_to_profile(profile, diff)
    steps = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "render_uml", "default_checked": True, "reason": "需要 UML"},
    ]
    adjusted = apply_behavior_to_steps(steps, profile)
    uml = next(s for s in adjusted if s["module"] == "render_uml")
    assert uml["default_checked"] is False
    assert "历史习惯" in uml.get("reason", "")


def test_behavior_disabled_leaves_steps_unchanged():
    profile = normalize_profile({"optimize_plan_from_usage": False})
    profile["behavior"]["module_cancel_count"]["render_uml"] = BEHAVIOR_MIN_SAMPLES
    steps = [{"module": "render_uml", "default_checked": True}]
    assert apply_behavior_to_steps(steps, profile) == steps
    assert behavior_hints_block(profile) == ""


def test_failure_modules_hint_in_planner_prompt():
    profile = normalize_profile({"optimize_plan_from_usage": True})
    profile["behavior"]["failure_modules"] = ["run_code"] * BEHAVIOR_MIN_SAMPLES
    prompt = render_plan_prompt("实验步骤 编写 Java 程序", profile=profile)
    assert "run_code" in prompt
    assert "历史行为" in prompt


def test_failure_modules_adds_step_reason_hint():
    profile = normalize_profile({"optimize_plan_from_usage": True})
    profile["behavior"]["failure_modules"] = ["run_code"] * BEHAVIOR_MIN_SAMPLES
    steps = [{"module": "run_code", "default_checked": True, "reason": "复验"}]
    adjusted = apply_behavior_to_steps(steps, profile)
    assert adjusted[0]["default_checked"] is True
    assert "历史上此步骤曾失败" in adjusted[0]["reason"]
