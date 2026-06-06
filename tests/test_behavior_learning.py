"""C2 behavior learning — module cancel counts affect planner (V3-4)."""

import json
from unittest.mock import patch

import pytest

from agent.plan_feedback import record_plan_feedback
from agent.planner import plan_from_report
from agent.user_profile import (
    BEHAVIOR_MIN_SAMPLES,
    PROFILE_PATH,
    apply_behavior_to_steps,
    apply_plan_feedback_to_profile,
    load_profile,
    normalize_profile,
    save_profile,
)


@pytest.fixture(autouse=True)
def _isolate_profile(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setattr("agent.user_profile.PROFILE_PATH", path)
    monkeypatch.setattr("agent.user_profile.APP_DATA", tmp_path)
    yield


def test_apply_plan_feedback_increments_cancel_count():
    profile = normalize_profile({"optimize_plan_from_usage": True})
    diff = {
        "changed": True,
        "toggles": [{"module": "render_uml", "to_checked": False}],
    }
    updated = apply_plan_feedback_to_profile(profile, diff)
    count = updated["behavior"]["module_cancel_count"]["render_uml"]
    assert count == 1


def test_cancel_uml_three_times_unchecks_on_plan():
    profile = normalize_profile({"optimize_plan_from_usage": True})
    baseline = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "render_uml", "default_checked": True, "reason": "需要 UML"},
    ]
    confirmed = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "render_uml", "default_checked": False},
    ]
    for _ in range(BEHAVIOR_MIN_SAMPLES):
        profile = apply_plan_feedback_to_profile(
            profile,
            record_plan_feedback(baseline, confirmed)["diff"],
        )
    save_profile(profile)

    steps = [
        {"module": "solve_lab", "default_checked": True, "reason": "解题"},
        {"module": "render_uml", "default_checked": True, "reason": "需要 UML"},
    ]
    adjusted = apply_behavior_to_steps(steps, load_profile())
    uml = next(s for s in adjusted if s["module"] == "render_uml")
    assert uml["default_checked"] is False
    assert "历史习惯" in uml.get("reason", "")


def test_behavior_disabled_by_default():
    profile = load_profile()
    assert profile.get("optimize_plan_from_usage") is False
    steps = [{"module": "render_uml", "default_checked": True}]
    assert apply_behavior_to_steps(steps, profile) == steps


@patch("llm_client.chat")
def test_plan_from_report_applies_behavior(mock_chat):
    profile = normalize_profile({"optimize_plan_from_usage": True})
    profile["behavior"]["module_cancel_count"]["render_uml"] = BEHAVIOR_MIN_SAMPLES
    mock_chat.return_value = {
        "content": json.dumps(
            {
                "steps": [
                    {"module": "solve_lab", "default_checked": True},
                    {"module": "render_uml", "default_checked": True, "reason": "UML"},
                ]
            }
        )
    }
    result = plan_from_report(
        "实验报告 三、实验步骤",
        settings={"api_key": "sk-test", "provider": "deepseek", "model": "deepseek-chat"},
        profile=profile,
    )
    uml = next(s for s in result["steps"] if s["module"] == "render_uml")
    assert uml["default_checked"] is False
