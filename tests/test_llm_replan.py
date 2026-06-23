"""LLM replan on module failure (AGENT_CAPABILITY_GAPS step 2)."""

import json
from unittest.mock import patch

import pytest

from agent.planner import replan_incremental, replan_steps_with_llm
from agent.types import PlanStep


@pytest.fixture
def replan_ctx():
    return {
        "settings": {
            "api_key": "sk-test",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "solvePipelineVersion": "v4",
        },
        "llm_replan": True,
        "report_text": "三、实验步骤 编写 Java 程序",
        "confirmed_steps": [
            PlanStep(module="solve_lab", params={}, reason="", evidence="", default_checked=True),
            PlanStep(module="run_code", params={}, reason="", evidence="", default_checked=True),
        ],
        "user_profile": {"default_language": "java"},
        "decision_log": [],
        "replan_rounds": 0,
        "max_replan_rounds": 1,
    }


@patch("llm_client.chat")
def test_replan_steps_with_llm_returns_steps(mock_chat, replan_ctx):
    mock_chat.return_value = {
        "content": json.dumps(
            {
                "steps": [
                    {
                        "module": "fix_code",
                        "params": {},
                        "reason": "修代码",
                        "evidence": "",
                        "source": "replan",
                        "confidence": "medium",
                        "default_checked": True,
                    },
                    {
                        "module": "present_deliverable",
                        "params": {},
                        "reason": "交付",
                        "evidence": "",
                        "source": "replan",
                        "confidence": "high",
                        "default_checked": True,
                    },
                ]
            }
        )
    }
    steps = replan_steps_with_llm(
        replan_ctx,
        {
            "failed_module": "run_code",
            "error_summary": "编译错误",
            "completed_modules": ["solve_lab"],
        },
    )
    assert steps is not None
    mods = [s["module"] for s in steps]
    assert "fix_code" in mods


@patch("agent.planner.replan_steps_with_llm")
def test_replan_incremental_uses_llm_when_available(mock_llm, replan_ctx):
    mock_llm.return_value = [
        PlanStep(module="solve_lab", params={}, reason="", evidence="", default_checked=True),
        PlanStep(module="fix_code", params={}, reason="", evidence="", default_checked=True),
        PlanStep(module="present_deliverable", params={}, reason="", evidence="", default_checked=True),
    ]
    plan = replan_incremental(
        replan_ctx,
        {
            "failed_module": "run_code",
            "error_summary": "error",
            "completed_modules": ["solve_lab"],
        },
    )
    assert replan_ctx.get("_llm_replan_used") is True
    mods = [s["module"] for s in plan["steps"]]
    assert "fix_code" in mods
    assert mock_llm.called


@patch("agent.planner.replan_steps_with_llm", return_value=None)
def test_replan_incremental_rule_fallback(mock_llm, replan_ctx):
    plan = replan_incremental(
        replan_ctx,
        {
            "failed_module": "run_code",
            "error_summary": "compile error",
            "completed_modules": ["solve_lab"],
        },
    )
    mods = [s["module"] for s in plan["steps"]]
    assert "fix_code" in mods
    assert mock_llm.called
