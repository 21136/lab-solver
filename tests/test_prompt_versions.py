"""IR-15: prompt version full-chain tracking in ctx and run_summary."""

from unittest.mock import patch

import pytest

from agent.orchestrator import RunOrchestrator
from agent.planner import make_agent_context, plan_from_report
from agent.prompts import PROMPTS, merge_prompt_versions, record_prompt_version
from agent.react_prompts import REACT_PROMPT_VERSION


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        with patch("agent.react_loop.is_cancelled", return_value=False):
            yield


def test_record_prompt_version_merges_without_overwriting_unrelated():
    ctx: dict = {"prompt_versions": {"planner": "1.0.0"}}
    record_prompt_version(ctx, "code_only")
    assert ctx["prompt_versions"]["planner"] == "1.0.0"
    assert ctx["prompt_versions"]["code_only"] == PROMPTS["code_only"].version


def test_merge_prompt_versions():
    ctx: dict = {}
    merge_prompt_versions(ctx, {"react": REACT_PROMPT_VERSION, "planner": "9.9.9"})
    assert ctx["prompt_versions"]["react"] == REACT_PROMPT_VERSION
    assert ctx["prompt_versions"]["planner"] == "9.9.9"


def test_make_agent_context_records_planner_version():
    ctx = make_agent_context("report", {"api_key": "k"})
    assert ctx["prompt_versions"]["planner"] == PROMPTS["planner"].version


def test_make_agent_context_records_understand_plan_version():
    plan = {
        "steps": [],
        "plan_fingerprint": "fp",
        "prompt_version": PROMPTS["understand_plan"].version,
    }
    ctx = make_agent_context("report", {"api_key": "k"}, plan=plan)
    assert ctx["prompt_versions"]["understand_plan"] == PROMPTS["understand_plan"].version
    assert ctx["prompt_versions"]["planner"] == PROMPTS["planner"].version


def test_plan_from_report_records_planner_prompt_version():
    fake_plan = {
        "steps": [{"module": "solve_lab", "params": {}, "reason": "r"}],
        "clarifications": [],
    }
    with patch(
        "llm_client.chat",
        return_value={"content": '{"steps":[{"module":"solve_lab","params":{}}]}'},
    ):
        with patch("agent.planner.parse_plan_json", return_value=fake_plan):
            plan = plan_from_report(
                "实验步骤：编写 Java 程序",
                settings={"api_key": "k", "provider": "deepseek", "model": "deepseek-chat"},
            )
    assert plan["prompt_version"] == PROMPTS["planner"].version


def test_build_run_summary_includes_prompt_versions():
    ctx = {
        "run_mode": "standard",
        "settings": {},
        "prompt_versions": {
            "planner": PROMPTS["planner"].version,
            "code_only": PROMPTS["code_only"].version,
        },
        "module_results": {},
        "verification_report": {"passed": True},
    }
    orch = RunOrchestrator("pv1", ctx, emit=lambda _e: None)
    with patch("llm_client.get_llm_call_count", return_value=0):
        with patch("llm_client.get_llm_calls_by_phase", return_value={}):
            summary = orch.build_run_summary()
    assert summary["prompt_versions"] == ctx["prompt_versions"]


def test_solve_lab_merges_pipeline_prompt_versions():
    from agent.executor_solve import _run_solve_lab

    ctx = {
        "run_id": "solve-pv",
        "settings": {"api_key": "k"},
        "report_text": "实验",
        "module_results": {},
        "prompt_versions": {"planner": PROMPTS["planner"].version},
    }
    pipeline_versions = {
        "code_only": PROMPTS["code_only"].version,
        "write_report_text": PROMPTS["write_report_text"].version,
    }

    def _fake_solve_lab(*_a, **_kw):
        return {
            "answer": "ok",
            "pipeline_meta": {
                "version": "v4",
                "code_status": "verified",
                "prompt_versions": pipeline_versions,
            },
        }

    with patch("agent.executor_solve.solve_lab", side_effect=_fake_solve_lab):
        result = _run_solve_lab(ctx, {})
    assert result["ok"] is True
    assert ctx["prompt_versions"]["code_only"] == PROMPTS["code_only"].version
    assert ctx["prompt_versions"]["write_report_text"] == PROMPTS["write_report_text"].version
    assert ctx["prompt_versions"]["planner"] == PROMPTS["planner"].version


def test_react_loop_records_react_prompt_version():
    from agent.react_loop import run_react_loop

    ctx = {
        "run_id": "react-pv",
        "settings": {"api_key": "k"},
        "report_text": "实验报告",
        "module_results": {},
        "plan": {"steps": [{"module": "present_deliverable", "params": {}, "default_checked": True}]},
        "decision_log": [],
        "run_mode": "react",
        "output_mode": "deliverable",
    }
    steps = [{"module": "present_deliverable", "params": {}, "default_checked": True}]
    events: list[dict] = []

    def _fake_chat_messages(_settings, messages, *, phase="", max_tokens=2000):
        if phase == "react":
            return {
                "content": '{"thought":"完成","action":"done","params":{}}',
            }
        return {"content": "{}"}

    with patch("agent.react_loop.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
        with patch("agent.react_loop.release_run"):
            with patch("agent.react_loop.chat_messages", side_effect=_fake_chat_messages):
                with patch("agent.react_loop._bootstrap_solve_pipeline"):
                    with patch("agent.quality.verify_answer", return_value={"passed": True}):
                        run_react_loop("react-pv", ctx, steps, use_fallback=False)

    assert ctx["prompt_versions"]["react"] == REACT_PROMPT_VERSION
    done = next(e for e in events if e.get("type") == "done")
    assert done["run_summary"]["prompt_versions"]["react"] == REACT_PROMPT_VERSION
