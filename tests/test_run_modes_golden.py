"""AO-8: Golden module-sequence traces per run_mode (mock LLM + runners)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.deep_pipeline import execute_deep_run
from agent.executor import _execute_standard_via_orchestrator
from agent.react_loop import run_react_loop

GOLDEN_PLAN = [
    {"module": "solve_lab", "params": {}, "default_checked": True},
    {"module": "present_deliverable", "params": {}, "default_checked": True},
]

GOLDEN_SEQUENCES = {
    "standard": ["solve_lab", "present_deliverable"],
    "deep": ["solve_lab", "present_deliverable"],
    "react": ["solve_lab", "present_deliverable"],
}


def _mock_solve_payload():
    return {
        "ok": True,
        "data": {
            "code": "print(1)",
            "language": "python",
            "parsed": {
                "steps_analysis": "步骤",
                "result_description": "结果",
                "summary": "小结",
            },
            "pipeline_meta": {"version": "v4", "code_status": "verified"},
            "solve_session": {"code_status": "verified", "pipeline_version": "v4"},
        },
    }


class ModuleSequenceTracker:
    def __init__(self):
        self.order: list[str] = []

    def runner(self, name: str):
        def _run(_ctx, _params):
            self.order.append(name)
            if name == "solve_lab":
                return _mock_solve_payload()
            if name == "present_deliverable":
                return {
                    "ok": True,
                    "data": {"deliverable": {"sections": [], "code_files": []}},
                }
            return {"ok": True, "data": {}}

        return _run

    def as_dict(self) -> dict:
        return {name: self.runner(name) for name in ("solve_lab", "present_deliverable", "render_uml", "fill_report")}


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        with patch("agent.react_loop.is_cancelled", return_value=False):
            with patch("agent.deep_pipeline.is_cancelled", return_value=False):
                yield


@pytest.fixture
def base_ctx():
    return {
        "run_id": "golden-run",
        "settings": {"api_key": "k", "provider": "deepseek", "model": "m"},
        "report_text": "实验报告全文",
        "planner_input_text": "【作业要求】\nFIFO\n\n【待填报告】\n三、步骤",
        "question": {"type": "lab_report"},
        "user_profile": {"default_language": "python"},
        "module_results": {},
        "output_mode": "deliverable",
        "plan": {"steps": GOLDEN_PLAN},
        "confirmed_steps": GOLDEN_PLAN,
        "decision_log": [],
        "auto_remediate": False,
    }


def test_standard_mode_module_sequence(base_ctx):
    tracker = ModuleSequenceTracker()
    events: list[dict] = []

    with patch("agent.executor.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
        with patch("agent.executor.release_run"):
            with patch("agent.executor.clear_run_temp"):
                with patch("agent.executor.fallback_to_solve"):
                    with patch.dict("agent.executor._MODULE_RUNNERS", tracker.as_dict(), clear=False):
                        with patch("agent.quality.verify_answer", return_value={"passed": True, "checks": []}):
                            _execute_standard_via_orchestrator(
                                "golden-std",
                                {**base_ctx, "run_mode": "standard"},
                                GOLDEN_PLAN,
                                use_fallback=False,
                            )

    assert tracker.order == GOLDEN_SEQUENCES["standard"]
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("run_summary", {}).get("mode") == "standard"
    assert done["run_summary"].get("code_status") == "verified"


def test_deep_mode_module_sequence(base_ctx):
    tracker = ModuleSequenceTracker()
    events: list[dict] = []

    def _draft(ctx, params):
        tracker.order.append("solve_lab")
        return _mock_solve_payload()

    with patch("agent.deep_pipeline._run_draft", side_effect=_draft):
        with patch("agent.deep_pipeline.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
            with patch("agent.run_control.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
                with patch("agent.run_control.release_run"):
                    with patch("agent.document_store.clear_run_temp"):
                        with patch.dict("agent.executor._MODULE_RUNNERS", tracker.as_dict(), clear=False):
                            with patch(
                                "agent.reflect.run_reflect",
                                return_value={"pass": True, "issues": [], "skipped": False},
                            ):
                                with patch(
                                    "agent.quality.verify_answer",
                                    return_value={"passed": True, "checks": []},
                                ):
                                    execute_deep_run(
                                        "golden-deep",
                                        {
                                            **base_ctx,
                                            "run_mode": "deep",
                                            "understand": {"summary": "理解摘要"},
                                        },
                                        GOLDEN_PLAN,
                                        use_fallback=False,
                                    )

    assert tracker.order == GOLDEN_SEQUENCES["deep"]
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("run_summary", {}).get("mode") == "deep"


@patch("agent.react_loop.chat_messages")
@patch("agent.react_loop.emit_event")
@patch("agent.react_loop.release_run")
def test_react_mode_module_sequence(mock_release, mock_emit, mock_chat, base_ctx):
    tracker = ModuleSequenceTracker()
    mock_chat.return_value = {
        "content": '{"thought": "收尾", "action": "done", "params": {}}',
        "reasoning_content": "",
        "finish_reason": "stop",
    }

    def _emit_side(_rid, ev):
        mock_emit.call_args  # keep reference
        return None

    mock_emit.side_effect = _emit_side

    with patch.dict("agent.executor._MODULE_RUNNERS", tracker.as_dict(), clear=False):
        with patch("agent.quality.verify_answer", return_value={"passed": True, "checks": []}):
            result = run_react_loop(
                "golden-react",
                {**base_ctx, "run_mode": "react"},
                GOLDEN_PLAN,
                use_fallback=False,
            )

    assert tracker.order == GOLDEN_SEQUENCES["react"]
    assert result.get("ok") is not False
    assert any(
        item.get("action") == "solve_lab" and item.get("bootstrap")
        for item in (result.get("thought_trace") or [])
    )


def test_golden_sequences_snapshot():
    """Document expected module order — update intentionally when policy changes."""
    assert GOLDEN_SEQUENCES == {
        "standard": ["solve_lab", "present_deliverable"],
        "deep": ["solve_lab", "present_deliverable"],
        "react": ["solve_lab", "present_deliverable"],
    }
