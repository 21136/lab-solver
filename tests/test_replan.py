"""IR-12: replan_incremental strategy table + max_replan_rounds config."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.planner import replan_incremental
from agent.types import max_replan_rounds_for_ctx


def _base_ctx(**overrides):
    confirmed = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
    ]
    ctx = {
        "report_text": "三、实验步骤",
        "user_profile": {"default_language": "java"},
        "confirmed_steps": confirmed,
        "plan": {"steps": confirmed},
        "decision_log": [],
        "replan_rounds": 0,
        "document_ids": [],
        "settings": {"maxReplanRounds": 1},
    }
    ctx.update(overrides)
    return ctx


class TestReplanStrategy:
    def test_run_code_inserts_fix_code(self):
        ctx = _base_ctx()
        plan = replan_incremental(
            ctx,
            {
                "failed_module": "run_code",
                "error_summary": "compile error",
                "error_category": "compile_error",
                "completed_modules": ["solve_lab"],
            },
        )
        mods = [s["module"] for s in plan["steps"]]
        assert mods == ["solve_lab", "fix_code"]
        assert ctx["replan_rounds"] == 1

    def test_render_uml_inserts_fix_diagrams_then_render(self):
        confirmed = [
            {"module": "solve_lab", "params": {}, "default_checked": True},
            {"module": "render_uml", "params": {}, "default_checked": True},
        ]
        ctx = _base_ctx(confirmed_steps=confirmed, plan={"steps": confirmed})
        plan = replan_incremental(
            ctx,
            {
                "failed_module": "render_uml",
                "error_summary": "plantuml invalid",
                "error_category": "validation_error",
                "completed_modules": ["solve_lab"],
            },
        )
        mods = [s["module"] for s in plan["steps"]]
        assert mods == ["solve_lab", "fix_diagrams", "render_uml"]

    def test_fix_code_failure_retries_run_code(self):
        confirmed = [
            {"module": "solve_lab", "params": {}, "default_checked": True},
            {"module": "run_code", "params": {}, "default_checked": True},
            {"module": "fix_code", "params": {}, "default_checked": True},
        ]
        ctx = _base_ctx(confirmed_steps=confirmed, plan={"steps": confirmed}, replan_rounds=0)
        plan = replan_incremental(
            ctx,
            {
                "failed_module": "fix_code",
                "error_summary": "still broken",
                "error_category": "compile_error",
                "completed_modules": ["solve_lab", "run_code"],
            },
        )
        mods = [s["module"] for s in plan["steps"]]
        assert "run_code" in mods


class TestMaxReplanRounds:
    def test_max_replan_rounds_from_ctx(self):
        assert max_replan_rounds_for_ctx({"max_replan_rounds": 3}) == 3
        assert max_replan_rounds_for_ctx({"settings": {"maxReplanRounds": 2}}) == 2
        assert max_replan_rounds_for_ctx({}) == 1
        assert max_replan_rounds_for_ctx({"max_replan_rounds": 99}) == 5

    def test_replan_skipped_when_rounds_exhausted(self):
        ctx = _base_ctx(replan_rounds=1, max_replan_rounds=1)
        plan = replan_incremental(
            ctx,
            {
                "failed_module": "run_code",
                "error_summary": "fail again",
                "completed_modules": ["solve_lab"],
            },
        )
        assert plan.get("steps") == ctx["plan"]["steps"] or not plan.get("steps")
        assert ctx["replan_rounds"] == 1
        skipped = [e for e in ctx["decision_log"] if e.get("decision") == "replan_skipped"]
        assert skipped

    def test_second_replan_allowed_when_max_is_two(self):
        ctx = _base_ctx(replan_rounds=1, max_replan_rounds=2)
        plan = replan_incremental(
            ctx,
            {
                "failed_module": "run_code",
                "error_summary": "fail again",
                "error_category": "runtime_exception",
                "completed_modules": ["solve_lab"],
            },
        )
        assert ctx["replan_rounds"] == 2
        assert "fix_code" in [s["module"] for s in plan["steps"]]


class TestReplanOrchestrator:
    def test_maybe_replan_passes_error_category(self):
        from agent.orchestrator import RunOrchestrator

        ctx = _base_ctx(
            module_results={
                "run_code": {
                    "ok": False,
                    "data": {"error": "boom", "error_category": "compile_error"},
                }
            }
        )
        events = []

        def emit(ev):
            events.append(ev)

        orch = RunOrchestrator("repl-1", ctx, emit=emit)
        orch.completed_modules = ["solve_lab"]

        with patch("agent.orchestrator.replan_incremental", wraps=replan_incremental) as mock_replan:
            ok = orch.maybe_replan("run_code", "boom")
            assert ok is True
            ctx_arg = mock_replan.call_args[0][1]
            assert ctx_arg.get("error_category") == "compile_error"


class TestMaxReplanRoundsServer:
    def test_agent_run_sets_max_replan_rounds(self):
        from server import app

        client = app.test_client()
        payload = {
            "api_key": "sk-test",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "run_mode": "standard",
            "document_ids": ["missing-doc-id"],
            "steps": [{"module": "solve_lab", "default_checked": True}],
            "plan_fingerprint": "sha256:dummy",
            "max_replan_rounds": 3,
            "agent_context_snapshot": {
                "report_text": "实验报告正文",
                "planner_input_text": "实验报告正文",
                "metadata": {},
                "question": {"type": "lab_report"},
                "document_ids": ["missing-doc-id"],
            },
        }

        with patch("server.verify_plan_fingerprint", return_value=(True, "sha256:dummy")):
            with patch("server.acquire_run", return_value="ir12-replan-rounds"):
                with patch("server.start_run_async") as mock_start:
                    resp = client.post("/api/agent/run", json=payload)

        assert resp.status_code == 200
        ctx = mock_start.call_args[0][1]
        assert ctx.get("max_replan_rounds") == 3
        assert (ctx.get("settings") or {}).get("maxReplanRounds") == 3
