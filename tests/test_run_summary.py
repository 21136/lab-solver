"""run_summary on done SSE (V3-4)."""

from unittest.mock import patch

import pytest

from agent.orchestrator import RunOrchestrator, finalize_run_payload


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        yield


def test_build_run_summary_fields():
    ctx = {
        "run_mode": "standard",
        "settings": {"solveQualityTier": "thorough"},
        "pipeline_meta": {"version": "v4", "code_status": "verified"},
        "prompt_versions": {"planner": "1.4.0", "code_only": "1.0.0"},
        "verification_report": {"passed": True},
        "skills_fired": ["java-no-servlet"],
        "finalize_ran": True,
        "module_results": {
            "fill_report": {"ok": True, "data": {"output_path": "/tmp/out.docx"}},
        },
    }
    orch = RunOrchestrator("rs1", ctx, emit=lambda _e: None)
    orch._auto_remediate_rounds = 1
    orch.replan_count = 2

    with patch("llm_client.get_llm_call_count", return_value=5):
        with patch(
            "llm_client.get_llm_calls_by_phase",
            return_value={"planner": 2, "solve_code": 3},
        ):
            summary = orch.build_run_summary()

    assert summary["mode"] == "standard"
    assert summary["solve_quality_tier"] == "thorough"
    assert summary["pipeline_version"] == "v4"
    assert summary["code_status"] == "verified"
    assert summary["llm_calls"] == 5
    assert summary["llm_calls_by_phase"] == {"planner": 2, "solve_code": 3}
    assert summary["prompt_versions"] == {"planner": "1.4.0", "code_only": "1.0.0"}
    assert summary["replan_count"] == 2
    assert summary["verify_pass"] is True
    assert summary["quality_status"] == "passed"
    assert summary["remediate_rounds"] == 1
    assert summary["auto_remediate_rounds"] == 1
    assert summary["unresolved_checks"] == []
    assert summary["skills_fired"] == ["java-no-servlet"]
    assert summary["finalize_ran"] is True
    assert summary["output_path"] == "/tmp/out.docx"


def test_build_run_summary_unresolved_checks_when_verify_fails():
    ctx = {
        "run_mode": "standard",
        "settings": {},
        "verification_report": {
            "passed": False,
            "checks": [
                {"id": "no_placeholder", "ok": False, "message": "检测到占位: TODO"},
                {"id": "schema_complete", "ok": True, "message": "结构完整"},
            ],
        },
        "module_results": {},
    }
    orch = RunOrchestrator("rs-fail", ctx, emit=lambda _e: None)
    orch._auto_remediate_rounds = 2

    with patch("llm_client.get_llm_call_count", return_value=0):
        with patch("llm_client.get_llm_calls_by_phase", return_value={}):
            summary = orch.build_run_summary()

    assert summary["verify_pass"] is False
    assert summary["quality_status"] == "needs_review"
    assert summary["remediate_rounds"] == 2
    assert len(summary["unresolved_checks"]) == 1
    assert summary["unresolved_checks"][0]["id"] == "no_placeholder"


def test_finalize_run_payload_attaches_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.skill_store.SKILL_CANDIDATES_PATH", tmp_path / "c.json")
    monkeypatch.setattr("agent.skill_store.APP_DATA", tmp_path)
    monkeypatch.setattr("agent.user_profile.PROFILE_PATH", tmp_path / "p.json")
    monkeypatch.setattr("agent.user_profile.APP_DATA", tmp_path)

    ctx = {
        "run_mode": "react",
        "run_id": "rs2",
        "verification_report": {"passed": False},
        "module_results": {},
        "decision_log": [],
    }
    orch = RunOrchestrator("rs2", ctx, emit=lambda _e: None)
    final = finalize_run_payload(orch, {"run_id": "rs2", "ok": True})
    assert "run_summary" in final
    assert final["run_summary"]["mode"] == "react"


def test_standard_run_done_includes_run_summary():
    from agent.executor import _execute_standard_via_orchestrator

    ctx = {
        "run_id": "std-rs",
        "module_results": {},
        "consecutive_failures": 0,
        "replan_rounds": 0,
        "plan": {"steps": []},
        "decision_log": [],
        "settings": {},
        "auto_remediate": False,
        "run_mode": "standard",
    }
    steps = [{"module": "fill_report", "params": {}, "default_checked": True}]
    events = []

    with patch("agent.executor.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
        with patch("agent.executor.release_run"):
            with patch("agent.executor.clear_run_temp"):
                with patch.dict(
                    "agent.executor._MODULE_RUNNERS",
                    {"fill_report": lambda c, p: {"ok": True, "data": {"output_path": "/x.docx"}}},
                    clear=False,
                ):
                    with patch("agent.quality.verify_answer", return_value={"passed": True}):
                        _execute_standard_via_orchestrator("std-rs", ctx, steps, use_fallback=False)

    done = next(e for e in events if e.get("type") == "done")
    assert "run_summary" in done
    assert done["run_summary"]["mode"] == "standard"
