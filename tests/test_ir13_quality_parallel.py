"""IR-13: auto fast tier + orchestrator parallel batches."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from agent.orchestrator import RunOrchestrator, RunStepsOptions
from agent.parallel_groups import scan_parallel_batch
from modules.solve_pipeline import is_light_question, resolve_solve_quality_tier


class TestIR13AutoFastTier:
    def test_code_cloze_auto_fast_when_not_explicit(self):
        settings = {"solveQualityTier": "standard", "solveQualityTierExplicit": False}
        ctx = {"question": {"type": "code_cloze"}}
        assert resolve_solve_quality_tier(settings, ctx) == "fast"

    def test_explicit_tier_wins_over_auto(self):
        settings = {
            "solveQualityTier": "thorough",
            "solveQualityTierExplicit": True,
        }
        ctx = {"question": {"type": "code_cloze"}}
        assert resolve_solve_quality_tier(settings, ctx) == "thorough"

    def test_deep_mode_no_auto_fast(self):
        settings = {
            "solveQualityTier": "standard",
            "solveQualityTierExplicit": False,
            "run_mode": "deep",
        }
        ctx = {"question": {"type": "code_cloze"}, "run_mode": "deep"}
        assert resolve_solve_quality_tier(settings, ctx) == "standard"

    def test_auto_fast_disabled(self):
        settings = {
            "solveQualityTier": "standard",
            "autoFastTierForLightQuestions": False,
        }
        ctx = {"question": {"type": "theory"}}
        assert resolve_solve_quality_tier(settings, ctx) == "standard"

    def test_pure_theory_plan_is_light(self):
        ctx = {
            "question": {"type": "lab_report"},
            "confirmed_steps": [
                {"module": "solve_lab", "default_checked": True},
                {"module": "present_deliverable", "default_checked": True},
            ],
            "planner_input_text": "简述 FIFO 原理",
        }
        assert is_light_question(ctx) is True

    def test_programming_plan_not_light(self):
        ctx = {
            "question": {"type": "lab_report"},
            "confirmed_steps": [
                {"module": "solve_lab", "default_checked": True},
                {"module": "run_code", "default_checked": True},
            ],
            "planner_input_text": "编写程序并运行",
        }
        assert is_light_question(ctx) is False


class TestIR13ParallelGroups:
    def test_scan_run_code_render_uml_batch(self):
        steps = [
            {"module": "solve_lab", "default_checked": True},
            {"module": "run_code", "default_checked": True},
            {"module": "render_uml", "default_checked": True},
            {"module": "present_deliverable", "default_checked": True},
        ]
        batch = scan_parallel_batch(
            steps,
            1,
            completed_modules={"solve_lab"},
            exclude_modules=frozenset(),
        )
        assert batch is not None
        assert [m for _, s in batch for m in [s["module"]]] == ["run_code", "render_uml"]

    def test_scan_requires_solve_lab_for_code_uml(self):
        steps = [
            {"module": "run_code", "default_checked": True},
            {"module": "render_uml", "default_checked": True},
        ]
        assert (
            scan_parallel_batch(
                steps,
                0,
                completed_modules=set(),
                exclude_modules=frozenset(),
            )
            is None
        )


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        yield


def test_orchestrator_parallel_run_code_render_uml():
    ctx = {
        "run_id": "par1",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "settings": {"enableParallelModuleSteps": True},
    }
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
        {"module": "render_uml", "params": {}, "default_checked": True},
    ]
    barrier = threading.Barrier(2, timeout=2)

    def _runner(name: str):
        def _run(_ctx, _params):
            if name in ("run_code", "render_uml"):
                barrier.wait(timeout=2)
            return {"ok": True, "data": {"module": name}}

        return _run

    mocks = {
        "solve_lab": _runner("solve_lab"),
        "run_code": _runner("run_code"),
        "render_uml": _runner("render_uml"),
    }
    events: list[dict] = []
    orch = RunOrchestrator("par1", ctx, emit=events.append)

    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        completed, cancelled = orch.run_steps(steps, options=RunStepsOptions())

    assert not cancelled
    assert completed == ["solve_lab", "run_code", "render_uml"]
    parallel_modules = [
        e["module"]
        for e in events
        if e.get("type") == "progress" and e.get("parallel") and e.get("status") == "running"
    ]
    assert "run_code" in parallel_modules
    assert "render_uml" in parallel_modules
    assert any(e.get("decision") == "run_parallel_batch" for e in ctx["decision_log"])
