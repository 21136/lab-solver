"""auto_remediate: verify fail → dirty → partial rerun → verify pass (V3-3)."""

from unittest.mock import patch

import pytest

from agent.executor_dirty import modules_to_rerun_from_verify
from agent.orchestrator import RunOrchestrator


def _incomplete_solve():
    return {
        "ok": True,
        "data": {
            "type": "lab_report",
            "parsed": {
                "steps_analysis": "步骤",
                "result_description": "结果",
                "code": "print(1)",
            },
            "code": "print(1)",
        },
    }


def _complete_solve():
    return {
        "ok": True,
        "data": {
            "type": "lab_report",
            "parsed": {
                "steps_analysis": "步骤",
                "result_description": "结果",
                "summary": "小结",
                "code": "print(1)",
            },
            "code": "print(1)",
        },
    }


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        yield


def test_auto_remediate_revise_full_passes_after_rerun():
    ctx = {
        "run_id": "rem1",
        "module_results": {"solve_lab": _incomplete_solve()},
        "confirmed_steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "auto_remediate": True,
    }
    events: list[dict] = []
    calls = {"n": 0}

    def mock_solve(c, p):
        calls["n"] += 1
        return _complete_solve()

    orch = RunOrchestrator("rem1", ctx, emit=events.append)
    orch.completed_modules = ["solve_lab"]

    with patch.dict("agent.executor._MODULE_RUNNERS", {"solve_lab": mock_solve}, clear=False):
        report = orch.run_verify(auto_remediate=True, max_rounds=1)

    assert report.get("passed") is True
    assert orch._auto_remediate_rounds == 1
    assert calls["n"] == 1

    verifications = [e for e in events if e.get("type") == "verification"]
    assert len(verifications) >= 2
    assert verifications[-1].get("remediated") is True
    assert verifications[-1].get("remediate_rounds") == 1

    decisions = [d for d in ctx["decision_log"] if d.get("decision") == "auto_remediate"]
    assert len(decisions) == 1
    assert "solve_lab" in decisions[0].get("target", "")


def test_modules_to_rerun_verified_code_uses_revise_not_solve_lab():
    ctx = {
        "pipeline_meta": {"code_status": "verified"},
        "module_results": {"solve_lab": {"ok": True, "data": {"pipeline_meta": {"code_status": "verified"}}}},
    }
    mods = modules_to_rerun_from_verify(["revise_full", "fix_code"], ctx)
    assert "solve_lab" not in mods
    assert "fix_code" not in mods
    assert "revise_answer" in mods


def test_auto_remediate_verified_uses_revise_answer():
    ctx = {
        "run_id": "rem3",
        "module_results": {"solve_lab": _incomplete_solve()},
        "pipeline_meta": {"code_status": "verified"},
        "confirmed_steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "auto_remediate": True,
        "settings": {"api_key": "k", "provider": "deepseek", "model": "m"},
    }
    solve_mr = ctx["module_results"]["solve_lab"]
    solve_mr["data"]["pipeline_meta"] = {"code_status": "verified"}
    events: list[dict] = []
    calls = {"solve": 0, "revise": 0}

    def mock_solve(c, p):
        calls["solve"] += 1
        return _complete_solve()

    def mock_revise(c, p):
        calls["revise"] += 1
        complete = _complete_solve()
        c.setdefault("module_results", {})["solve_lab"] = complete
        return {"ok": True, "data": {"changed_fields": ["summary"]}}

    orch = RunOrchestrator("rem3", ctx, emit=events.append)
    orch.completed_modules = ["solve_lab"]

    with patch.dict(
        "agent.executor._MODULE_RUNNERS",
        {"solve_lab": mock_solve, "revise_answer": mock_revise},
        clear=False,
    ):
        report = orch.run_verify(auto_remediate=True, max_rounds=1)

    assert report.get("passed") is True
    assert calls["solve"] == 0
    assert calls["revise"] == 1


def test_auto_remediate_off_no_rerun():
    ctx = {
        "run_id": "rem2",
        "module_results": {"solve_lab": _incomplete_solve()},
        "confirmed_steps": [{"module": "solve_lab", "default_checked": True}],
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "auto_remediate": False,
    }
    events: list[dict] = []
    calls = {"n": 0}

    def mock_solve(c, p):
        calls["n"] += 1
        return _incomplete_solve()

    orch = RunOrchestrator("rem2", ctx, emit=events.append)

    with patch.dict("agent.executor._MODULE_RUNNERS", {"solve_lab": mock_solve}, clear=False):
        report = orch.run_verify(auto_remediate=False)

    assert report.get("passed") is False
    assert orch._auto_remediate_rounds == 0
    assert calls["n"] == 0
    assert len([e for e in events if e.get("type") == "verification"]) == 1


def test_auto_remediate_max_rounds_from_ctx():
    ctx = {
        "run_id": "rem4",
        "module_results": {"solve_lab": _incomplete_solve()},
        "confirmed_steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "auto_remediate": True,
        "auto_remediate_max_rounds": 2,
    }
    events: list[dict] = []
    calls = {"n": 0}

    def mock_solve(c, p):
        calls["n"] += 1
        # first rerun still incomplete, second rerun completes
        if calls["n"] == 1:
            return _incomplete_solve()
        return _complete_solve()

    orch = RunOrchestrator("rem4", ctx, emit=events.append)
    orch.completed_modules = ["solve_lab"]

    with patch.dict("agent.executor._MODULE_RUNNERS", {"solve_lab": mock_solve}, clear=False):
        report = orch.run_verify(auto_remediate=True)

    assert report.get("passed") is True
    assert calls["n"] == 2
    assert orch._auto_remediate_rounds == 2
