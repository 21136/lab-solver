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

CODE_CLOZE_PLAN = [
    {"module": "solve_code_cloze", "params": {"language": "java"}, "default_checked": True},
    {"module": "present_deliverable", "params": {}, "default_checked": True},
]

MIXED_PLAN = [
    {
        "module": "solve_theory",
        "params": {"segment_id": 0, "segment_title": "简答"},
        "default_checked": True,
    },
    {
        "module": "solve_code_cloze",
        "params": {"segment_id": 1, "segment_title": "填空", "language": "java"},
        "default_checked": True,
    },
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
            if name == "solve_theory":
                return {"ok": True, "data": {"answer": "外观模式封装子系统。"}}
            if name == "solve_code_cloze":
                return {
                    "ok": True,
                    "data": {
                        "type": "code_cloze",
                        "blanks": {"1": {"answer": "abstract class", "brief": "抽象类"}},
                    },
                }
            if name == "present_deliverable":
                return {
                    "ok": True,
                    "data": {"deliverable": {"sections": [], "code_files": []}},
                }
            return {"ok": True, "data": {}}

        return _run

    def as_dict(self) -> dict:
        return {
            name: self.runner(name)
            for name in (
                "solve_lab",
                "solve_theory",
                "solve_code_cloze",
                "present_deliverable",
                "render_uml",
                "fill_report",
            )
        }


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
                with patch("agent.fallback.fallback_to_solve"):
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


def test_deep_mode_code_cloze_skips_solve_lab_draft(base_ctx):
    """R1: deep + code_cloze plan must not bootstrap solve_lab draft (BF50)."""
    tracker = ModuleSequenceTracker()
    events: list[dict] = []
    draft_called = {"n": 0}

    def _draft(ctx, params):
        draft_called["n"] += 1
        return _mock_solve_payload()

    cloze_ctx = {
        **base_ctx,
        "run_mode": "deep",
        "understand": {"summary": "代码填空理解"},
        "question": {"type": "code_cloze"},
        "metadata": {"code_cloze": {"is_code_cloze": True, "blank_count": 4}},
        "plan": {"steps": CODE_CLOZE_PLAN},
        "confirmed_steps": CODE_CLOZE_PLAN,
    }

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
                                        "golden-deep-cloze",
                                        cloze_ctx,
                                        CODE_CLOZE_PLAN,
                                        use_fallback=False,
                                    )

    assert draft_called["n"] == 0
    assert tracker.order == ["solve_code_cloze", "present_deliverable"]
    assert "solve_lab" not in tracker.order
    draft_events = [
        e
        for e in events
        if e.get("module") == "solve_lab" and e.get("phase") == "draft"
    ]
    assert draft_events == []


def test_deep_mode_mixed_assignment_skips_solve_lab_draft(base_ctx):
    tracker = ModuleSequenceTracker()
    events: list[dict] = []
    draft_called = {"n": 0}

    def _draft(ctx, params):
        draft_called["n"] += 1
        return {"ok": True, "data": {}}

    mixed_ctx = {
        **base_ctx,
        "metadata": {
            "mixed_assignment": True,
            "assignment_questions": [
                {"id": 0, "type": "theory", "title": "简答", "full_text": "说明 Facade"},
                {
                    "id": 1,
                    "type": "code_cloze",
                    "title": "填空",
                    "full_text": "class T { ( 1 ) a; ( 2 ) b; }",
                },
            ],
        },
        "question": {"type": "mixed_assignment"},
        "plan": {"steps": MIXED_PLAN},
        "confirmed_steps": MIXED_PLAN,
    }

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
                                        "golden-deep-mixed",
                                        mixed_ctx,
                                        MIXED_PLAN,
                                        use_fallback=False,
                                    )

    assert draft_called["n"] == 0
    assert tracker.order == ["solve_theory", "solve_code_cloze", "present_deliverable"]
    assert "solve_lab" not in tracker.order


def test_standard_mode_code_cloze_module_sequence(base_ctx):
    """Pure code_cloze: solve_code_cloze → present_deliverable, no solve_lab."""
    tracker = ModuleSequenceTracker()
    events: list[dict] = []
    cloze_ctx = {
        **base_ctx,
        "run_mode": "standard",
        "question": {"type": "code_cloze"},
        "metadata": {"code_cloze": {"is_code_cloze": True, "blank_count": 4}},
        "plan": {"steps": CODE_CLOZE_PLAN},
        "confirmed_steps": CODE_CLOZE_PLAN,
    }

    with patch("agent.executor.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
        with patch("agent.executor.release_run"):
            with patch("agent.executor.clear_run_temp"):
                with patch("agent.fallback.fallback_to_solve"):
                    with patch.dict("agent.executor._MODULE_RUNNERS", tracker.as_dict(), clear=False):
                        with patch("agent.quality.verify_answer", return_value={"passed": True, "checks": []}):
                            _execute_standard_via_orchestrator(
                                "golden-std-cloze",
                                cloze_ctx,
                                CODE_CLOZE_PLAN,
                                use_fallback=False,
                            )

    assert tracker.order == ["solve_code_cloze", "present_deliverable"]
    assert "solve_lab" not in tracker.order
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("run_summary", {}).get("mode") == "standard"


@patch("agent.react_loop.chat_messages")
@patch("agent.react_loop.emit_event")
@patch("agent.react_loop.release_run")
def test_react_mode_code_cloze_bootstrap(mock_release, mock_emit, mock_chat, base_ctx):
    """Pure code_cloze: bootstrap solve_code_cloze, not solve_lab (BF49)."""
    tracker = ModuleSequenceTracker()
    solve_lab_calls: list[str] = []

    def _solve_lab(_ctx, _p):
        solve_lab_calls.append("solve_lab")
        return {"ok": False, "data": {}}

    mock_chat.return_value = {
        "content": '{"thought": "收尾", "action": "done", "params": {}}',
        "reasoning_content": "",
        "finish_reason": "stop",
    }

    cloze_ctx = {
        **base_ctx,
        "run_mode": "react",
        "question": {"type": "code_cloze"},
        "metadata": {"code_cloze": {"is_code_cloze": True, "blank_count": 4}},
        "plan": {"steps": CODE_CLOZE_PLAN},
        "confirmed_steps": CODE_CLOZE_PLAN,
    }

    runners = tracker.as_dict()
    runners["solve_lab"] = _solve_lab

    with patch.dict("agent.executor._MODULE_RUNNERS", runners, clear=False):
        with patch("agent.quality.verify_answer", return_value={"passed": True, "checks": []}):
            result = run_react_loop(
                "golden-react-cloze",
                cloze_ctx,
                CODE_CLOZE_PLAN,
                use_fallback=False,
            )

    assert tracker.order == ["solve_code_cloze", "present_deliverable"]
    assert "solve_lab" not in tracker.order
    assert solve_lab_calls == []
    trace = result.get("thought_trace") or []
    bootstrap_actions = [t.get("action") for t in trace if t.get("bootstrap")]
    assert bootstrap_actions == ["solve_code_cloze"]
    assert "solve_lab" not in bootstrap_actions


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
