from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.understand_plan import understand_and_plan  # noqa: E402


def _settings() -> dict:
    return {
        "api_key": "sk-test",
        "provider": "deepseek",
        "model": "deepseek-chat",
    }


def test_understand_and_plan_success():
    fake = {
        "content": """
{
  "understand": {"summary": "读取成功", "grading_points": ["代码可运行"]},
  "plan": {
    "steps": [
      {"module": "solve_lab", "params": {"language": "java"}, "reason": "需要代码", "confidence": "high"},
      {"module": "present_deliverable", "params": {}, "reason": "整理输出", "confidence": "high"}
    ],
    "clarifications": []
  }
}
""",
        "reasoning_content": "reasoning",
    }
    with patch("agent.understand_plan.chat", return_value=fake):
        understand, plan = understand_and_plan(
            "实验报告正文",
            settings=_settings(),
            profile={"default_language": "java"},
        )

    assert understand.get("summary") == "读取成功"
    assert understand.get("degraded") is not True
    assert isinstance(plan.get("steps"), list) and len(plan["steps"]) >= 1
    assert plan.get("plan_fingerprint", "").startswith("sha256:")


def test_understand_and_plan_fallback_marks_degraded():
    fallback_plan = {
        "steps": [{"module": "solve_lab", "params": {"language": "java"}, "default_checked": True}],
        "clarifications": [],
        "plan_fingerprint": "sha256:fallback",
    }
    with patch("agent.understand_plan.chat", side_effect=Exception("boom")):
        with patch("agent.planner.plan_from_report", return_value=fallback_plan):
            understand, plan = understand_and_plan(
                "实验报告正文",
                settings=_settings(),
                profile={"default_language": "java"},
            )

    assert understand.get("degraded") is True
    assert "回退标准计划" in (understand.get("summary") or "")
    assert plan.get("steps")


def test_understand_and_plan_parse_failure_marks_degraded():
    fallback_plan = {
        "steps": [{"module": "solve_lab", "params": {"language": "java"}, "default_checked": True}],
        "clarifications": [],
        "plan_fingerprint": "sha256:fallback",
    }
    fake = {
        "content": '{"thought": "wrong schema", "action": "done"}',
        "reasoning_content": "",
    }
    with patch("agent.understand_plan.chat", return_value=fake):
        with patch("agent.planner.plan_from_report", return_value=fallback_plan):
            understand, plan = understand_and_plan(
                "实验报告正文",
                settings=_settings(),
                profile={"default_language": "java"},
            )

    assert understand.get("degraded") is True
    assert plan.get("steps")
