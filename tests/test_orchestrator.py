"""RunOrchestrator unit tests (V3-2) — mock runners, assert progress order."""

from unittest.mock import patch

import pytest

from agent.orchestrator import RunOrchestrator, RunStepsOptions


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        yield


def _collect_emit():
    events: list[dict] = []

    def emit(ev):
        events.append(ev)

    return events, emit


def test_run_steps_progress_order():
    ctx = {
        "run_id": "orch1",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "document_ids": [],
        "report_text": "实验",
    }
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
    ]
    call_order: list[str] = []
    mocks = {
        "solve_lab": lambda c, p: (call_order.append("solve_lab") or {"ok": True, "data": {"code": "x"}}),
        "run_code": lambda c, p: (call_order.append("run_code") or {"ok": True, "data": {"output": "ok"}}),
    }
    events, emit = _collect_emit()
    orch = RunOrchestrator("orch1", ctx, emit=emit)

    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        completed, cancelled = orch.run_steps(steps)

    assert not cancelled
    assert completed == ["solve_lab", "run_code"]
    assert call_order == ["solve_lab", "run_code"]

    progress = [e for e in events if e.get("type") == "progress"]
    statuses = [(e["module"], e["status"]) for e in progress]
    assert statuses == [
        ("solve_lab", "running"),
        ("solve_lab", "done"),
        ("run_code", "running"),
        ("run_code", "done"),
    ]


def test_should_reuse_dirty_module():
    ctx = {
        "module_results": {
            "run_code": {"ok": True, "data": {"output": "x"}, "fingerprint": "fp1"},
        },
        "dirty_modules": ["run_code"],
    }
    orch = RunOrchestrator("t", ctx, emit=lambda _e: None)
    assert orch.should_reuse("run_code") is False
    ctx["dirty_modules"] = []
    assert orch.should_reuse("run_code") is True


def test_fill_report_failure_is_non_blocking():
    ctx = {
        "run_id": "orch_fill",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
    }
    steps = [{"module": "fill_report", "params": {}, "default_checked": True}]
    mocks = {
        "fill_report": lambda c, p: {"ok": False, "data": {"error": "节未匹配"}},
    }
    events, emit = _collect_emit()
    orch = RunOrchestrator("orch_fill", ctx, emit=emit)

    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        completed, cancelled = orch.run_steps(steps)

    assert cancelled is False
    assert completed == []
    assert ctx["consecutive_failures"] == 0
    progress = [e for e in events if e.get("type") == "progress" and e.get("module") == "fill_report"]
    assert len(progress) == 2
    assert progress[-1]["status"] == "degraded"
    assert progress[-1].get("error_meta", {}).get("degraded") is True


def test_run_steps_skips_unchecked():
    ctx = {
        "run_id": "orch2",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
    }
    steps = [
        {"module": "render_uml", "params": {}, "default_checked": False},
        {"module": "fill_report", "params": {}, "default_checked": True},
    ]
    mocks = {
        "fill_report": lambda c, p: {"ok": True, "data": {"output_path": "/tmp/out.docx"}},
    }
    events, emit = _collect_emit()
    orch = RunOrchestrator("orch2", ctx, emit=emit)

    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        completed, _ = orch.run_steps(steps)

    assert completed == ["fill_report"]
    skipped = [e for e in events if e.get("status") == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["module"] == "render_uml"


def test_deep_tail_options_exclude_solve_lab():
    ctx = {
        "run_id": "deep1",
        "module_results": {"solve_lab": {"ok": True, "data": {}}},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
    }
    steps = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
        {"module": "fix_code", "params": {}, "default_checked": True},
    ]
    ran: list[str] = []
    mocks = {
        "run_code": lambda c, p: (ran.append("run_code") or {"ok": True, "data": {}}),
    }
    events, emit = _collect_emit()
    opts = RunStepsOptions(
        exclude_modules=frozenset({"solve_lab", "fix_code"}),
        emit_skipped=False,
        enable_reuse=False,
        log_step_decisions=False,
        initial_completed=["solve_lab"],
    )
    orch = RunOrchestrator("deep1", ctx, emit=emit)

    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        completed, _ = orch.run_steps(steps, options=opts)

    assert ran == ["run_code"]
    assert "solve_lab" not in completed or completed == ["solve_lab", "run_code"]


def test_ir1_execute_standard_run_delegates_to_orchestrator():
    """IR-1: standard mode has no legacy loop — only RunOrchestrator path."""
    from agent.executor import execute_standard_run

    ctx = {
        "run_id": "ir1-std",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "document_ids": [],
        "report_text": "实验",
        "settings": {},
    }
    steps = [{"module": "solve_lab", "params": {}, "default_checked": True}]

    with patch("agent.orchestrator.RunOrchestrator") as mock_orch_cls:
        orch = mock_orch_cls.return_value
        orch.run_steps.return_value = (["solve_lab"], False)
        with patch("agent.run_result.complete_agent_run", return_value={"ok": True, "run_id": "ir1-std"}):
            with patch("agent.executor.emit_event"):
                result = execute_standard_run("ir1-std", ctx, steps, use_fallback=False)

    mock_orch_cls.assert_called_once()
    orch.run_steps.assert_called_once()
    assert result.get("ok") is True
