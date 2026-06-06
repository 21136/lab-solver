"""AO-1: deep_pipeline skips V4 duplicate preflight/fix; v1 keeps legacy loop."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.deep_pipeline import execute_deep_run  # noqa: E402


def _v4_verified_solve_data():
    code = 'public class Main { public static void main(String[] a) { System.out.println("ok"); } }'
    return {
        "parsed": {
            "steps_analysis": "步骤",
            "result_description": "结果",
            "summary": "总结",
            "code": code,
            "code_files": [{"name": "Main.java", "code": code}],
            "main_file": "Main.java",
            "language": "java",
        },
        "code": code,
        "code_files": [{"name": "Main.java", "code": code}],
        "main_file": "Main.java",
        "language": "java",
        "pipeline_meta": {"version": "v4", "code_status": "verified"},
        "solve_session": {
            "pipeline_version": "v4",
            "code_status": "verified",
            "run_result": {"stdout": "ok\n", "is_error": False},
        },
    }


def _v1_solve_data_with_bad_code():
    return {
        "parsed": {
            "steps_analysis": "步骤",
            "result_description": "结果",
            "summary": "总结",
            "code": "public class Main {",
            "code_files": [{"name": "Main.java", "code": "public class Main {"}],
            "main_file": "Main.java",
            "language": "java",
        },
        "code": "public class Main {",
        "code_files": [{"name": "Main.java", "code": "public class Main {"}],
        "main_file": "Main.java",
        "language": "java",
    }


@pytest.fixture
def deep_ctx():
    return {
        "run_id": "test-deep-v4",
        "settings": {"api_key": "k", "provider": "deepseek", "model": "m", "solvePipelineVersion": "v4"},
        "understand": {"summary": "测试"},
        "confirmed_steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
        "planner_input_text": "实验要求",
    }


@patch("agent.deep_pipeline.is_cancelled", return_value=False)
@patch("agent.run_result.complete_agent_run")
@patch("agent.orchestrator.RunOrchestrator")
@patch("agent.deep_pipeline.run_reflect")
@patch("agent.deep_pipeline._run_draft")
@patch("agent.deep_pipeline.fix_code_from_error")
@patch("agent.deep_pipeline.run_preflight")
def test_v4_verified_skips_preflight_and_fix(
    mock_preflight,
    mock_fix,
    mock_draft,
    mock_reflect,
    mock_orch_cls,
    mock_complete,
    _mock_cancelled,
    deep_ctx,
):
    mock_draft.return_value = {"ok": True, "data": _v4_verified_solve_data()}
    mock_reflect.return_value = {"pass": True, "issues": []}
    mock_orch = MagicMock()
    mock_orch.run_steps.return_value = ([], False)
    mock_orch_cls.return_value = mock_orch
    mock_complete.return_value = {"ok": True}

    execute_deep_run("test-deep-v4", deep_ctx, deep_ctx["confirmed_steps"], use_fallback=False)

    mock_preflight.assert_not_called()
    mock_fix.assert_not_called()
    mock_reflect.assert_called_once()


@patch("agent.deep_pipeline.is_cancelled", return_value=False)
@patch("agent.run_result.complete_agent_run")
@patch("agent.orchestrator.RunOrchestrator")
@patch("agent.deep_pipeline.run_reflect")
@patch("agent.deep_pipeline._run_draft")
@patch("agent.deep_pipeline.fix_code_from_error")
@patch("agent.deep_pipeline.run_preflight")
def test_v4_degraded_skips_preflight_and_fix(
    mock_preflight,
    mock_fix,
    mock_draft,
    mock_reflect,
    mock_orch_cls,
    mock_complete,
    _mock_cancelled,
    deep_ctx,
):
    data = _v4_verified_solve_data()
    data["pipeline_meta"]["code_status"] = "degraded"
    data["solve_session"]["code_status"] = "degraded"
    mock_draft.return_value = {"ok": True, "data": data}
    mock_reflect.return_value = {"pass": True, "issues": []}
    mock_orch = MagicMock()
    mock_orch.run_steps.return_value = ([], False)
    mock_orch_cls.return_value = mock_orch
    mock_complete.return_value = {"ok": True}

    execute_deep_run("test-deep-v4", deep_ctx, deep_ctx["confirmed_steps"], use_fallback=False)

    mock_preflight.assert_not_called()
    mock_fix.assert_not_called()


@patch("agent.deep_pipeline.is_cancelled", return_value=False)
@patch("agent.run_result.complete_agent_run")
@patch("agent.orchestrator.RunOrchestrator")
@patch("agent.deep_pipeline.run_reflect")
@patch("agent.deep_pipeline.revise_answer")
@patch("agent.deep_pipeline._run_draft")
@patch("agent.deep_pipeline.fix_code_from_error")
@patch("agent.deep_pipeline.run_preflight")
def test_v4_verified_revise_text_only(
    mock_preflight,
    mock_fix,
    mock_draft,
    mock_revise,
    mock_reflect,
    mock_orch_cls,
    mock_complete,
    _mock_cancelled,
    deep_ctx,
):
    original_code = _v4_verified_solve_data()
    mock_draft.return_value = {"ok": True, "data": original_code}
    mock_reflect.return_value = {
        "pass": False,
        "issues": [{"field": "code", "message": "应优化代码"}, {"field": "summary", "message": "总结太短"}],
        "issues_fingerprint": "fp1",
    }
    mock_revise.return_value = {
        "parsed": {
            **original_code["parsed"],
            "code": "public class Evil {}",
            "code_files": [{"name": "Main.java", "code": "public class Evil {}"}],
            "summary": "更完整的总结",
        },
        "changed_fields": ["code", "summary"],
    }
    mock_orch = MagicMock()
    mock_orch.run_steps.return_value = ([], False)
    mock_orch_cls.return_value = mock_orch
    mock_complete.return_value = {"ok": True}

    execute_deep_run("test-deep-v4", deep_ctx, deep_ctx["confirmed_steps"], use_fallback=False)

    scope = mock_revise.call_args.kwargs.get("scope") or mock_revise.call_args[1].get("scope")
    assert "code" not in scope
    stored = deep_ctx["module_results"]["solve_lab"]["data"]
    assert "Evil" not in (stored.get("code") or "")
    assert stored["parsed"]["summary"] == "更完整的总结"


@patch("agent.deep_pipeline.is_cancelled", return_value=False)
@patch("modules.solve_pipeline.pipeline_version", return_value="v1")
@patch("agent.run_result.complete_agent_run")
@patch("agent.orchestrator.RunOrchestrator")
@patch("agent.deep_pipeline.run_reflect")
@patch("agent.deep_pipeline._run_draft")
@patch("agent.deep_pipeline.fix_code_from_error")
@patch("agent.deep_pipeline.apply_fix_to_solve_data")
@patch("agent.deep_pipeline.run_preflight")
def test_v1_keeps_preflight_fix_loop(
    mock_preflight,
    mock_apply,
    mock_fix,
    mock_draft,
    mock_reflect,
    mock_orch_cls,
    mock_complete,
    _mock_pipeline_ver,
    _mock_cancelled,
    deep_ctx,
):
    deep_ctx["settings"]["solvePipelineVersion"] = "v1"
    bad = _v1_solve_data_with_bad_code()
    mock_draft.return_value = {"ok": True, "data": bad}
    mock_preflight.side_effect = [
        {"ok": False, "checks": [{"id": "code_syntax", "ok": False, "message": "syntax"}], "failed_ids": ["code_syntax"]},
        {"ok": True, "checks": [], "failed_ids": []},
    ]
    fixed = dict(bad)
    fixed["code"] = "public class Main { public static void main(String[] a) {} }"
    mock_fix.return_value = {"code": fixed["code"]}
    mock_apply.return_value = fixed
    mock_reflect.return_value = {"pass": True, "issues": []}
    mock_orch = MagicMock()
    mock_orch.run_steps.return_value = ([], False)
    mock_orch_cls.return_value = mock_orch
    mock_complete.return_value = {"ok": True}

    execute_deep_run("test-deep-v4", deep_ctx, deep_ctx["confirmed_steps"], use_fallback=False)

    assert mock_preflight.call_count >= 1
    mock_fix.assert_called_once()
