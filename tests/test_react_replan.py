"""ReAct consecutive failures trigger orchestrator.maybe_replan (V3-4)."""

from unittest.mock import MagicMock, patch

from agent.react_loop import MAX_CONSECUTIVE_FAILURES, run_react_loop


class TestReactReplan:
    def _make_ctx(self):
        return {
            "settings": {
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "report_text": "实验报告",
            "planner_input_text": "实验报告",
            "question": {"type": "lab_report"},
            "user_profile": {"default_language": "python"},
            "module_results": {},
            "run_id": "react-replan",
            "plan": {
                "steps": [
                    {"module": "solve_lab", "default_checked": True},
                    {"module": "run_code", "default_checked": True},
                ],
                "plan_fingerprint": "fp-old",
            },
            "confirmed_steps": [
                {"module": "solve_lab", "default_checked": True},
                {"module": "run_code", "default_checked": True},
            ],
            "replan_rounds": 0,
            "decision_log": [],
        }

    def _mock_chat_sequence(self, responses):
        calls = [0]

        def side_effect(settings, messages, **kwargs):
            idx = min(calls[0], len(responses) - 1)
            calls[0] += 1
            return {"content": responses[idx], "reasoning_content": "", "finish_reason": "stop"}

        return side_effect

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    @patch("agent.react_loop.execute_tool")
    @patch("agent.react_finalize.react_finalize_pipeline")
    @patch("agent.orchestrator.RunOrchestrator.maybe_replan")
    def test_replan_on_run_code_failures(
        self,
        mock_maybe_replan,
        mock_finalize,
        mock_tool,
        mock_cancel,
        mock_release,
        mock_emit,
        mock_chat,
    ):
        mock_cancel.return_value = False
        mock_finalize.return_value = []
        mock_tool.return_value = {"ok": False, "result_summary": "run failed"}
        mock_maybe_replan.return_value = True

        responses = []
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            responses.append('{"thought":"retry","action":"run_code","params":{}}')
        responses.append('{"thought":"done","action":"done","params":{}}')
        mock_chat.side_effect = self._mock_chat_sequence(responses)

        emitted = []

        def capture_emit(_run_id, ev):
            emitted.append(ev)

        mock_emit.side_effect = capture_emit

        result = run_react_loop("react-replan", self._make_ctx(), [], use_fallback=False)

        assert mock_maybe_replan.called
        assert mock_maybe_replan.call_args[0][0] == "run_code"
        assert "ok" in result
        done_events = [e for e in emitted if e.get("type") == "done"]
        assert done_events
        assert "run_summary" in done_events[-1]
