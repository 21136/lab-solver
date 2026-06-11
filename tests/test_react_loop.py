"""Unit tests for ReAct agent loop (Phase R1)."""

from unittest.mock import patch

import pytest

from agent.react_loop import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_REACT_ROUNDS,
    REACT_TAIL_MAX_MESSAGES,
    _parse_react_response,
    _attempt_react_repair,
    _compact_history_for_llm,
    run_react_loop,
)
from agent.react_prompts import REACT_SYSTEM_PROMPT
from agent.react_tools import (
    REACT_TOOL_SCHEMAS,
    build_tools_prompt,
    execute_tool,
    tool_to_module,
)


# ── prompt / schema tests ──


class TestBuildToolsPrompt:
    def test_includes_all_tools(self):
        text = build_tools_prompt()
        for name in ("solve_lab", "run_code", "fill_report", "render_uml", "finalize_report"):
            assert f"[TOOL: {name}]" in text

    def test_includes_descriptions(self):
        text = build_tools_prompt()
        for name, schema in REACT_TOOL_SCHEMAS.items():
            assert schema["description"] in text


class TestToolToModule:
    def test_known_actions(self):
        assert tool_to_module("solve_lab") == "solve_lab"
        assert tool_to_module("run_code") == "run_code"
        assert tool_to_module("fill_report") == "fill_report"
        assert tool_to_module("render_uml") == "render_uml"

    def test_case_insensitive(self):
        assert tool_to_module("Solve_Lab") == "solve_lab"
        assert tool_to_module("  RUN_CODE  ") == "run_code"

    def test_unknown_action(self):
        assert tool_to_module("nonexistent") == ""
        assert tool_to_module("") == ""


# ── parse tests ──


class TestParseReactResponse:
    def test_normal_response(self):
        resp = "THOUGHT: 应该先解题\nACTION: solve_lab\nPARAMS: {\"language\": \"python\"}"
        parsed = _parse_react_response(resp)
        assert parsed["action"] == "solve_lab"
        assert parsed["params"] == {"language": "python"}
        assert "应该先解题" in parsed["thought"]

    def test_done_response(self):
        resp = "THOUGHT: 全部完成\nACTION: done"
        parsed = _parse_react_response(resp)
        assert parsed["action"] == "done"
        assert "全部完成" in parsed["thought"]

    def test_no_params(self):
        resp = "THOUGHT: 执行代码\nACTION: run_code"
        parsed = _parse_react_response(resp)
        assert parsed["action"] == "run_code"
        assert parsed["params"] == {}

    def test_empty_response(self):
        parsed = _parse_react_response("")
        assert parsed["thought"] == ""
        assert parsed["action"] == ""
        assert parsed["params"] == {}

    def test_malformed_json_params(self):
        resp = "THOUGHT: test\nACTION: solve_lab\nPARAMS: {broken json"
        parsed = _parse_react_response(resp)
        assert parsed["action"] == "solve_lab"
        assert parsed["params"] == {}  # Falls back to empty

    def test_only_done_text(self):
        parsed = _parse_react_response("done")
        assert parsed["action"] == "done"

    def test_multiline_thought(self):
        resp = """THOUGHT: 第一行
第二行
第三行
ACTION: fill_report
PARAMS: {}"""
        parsed = _parse_react_response(resp)
        assert parsed["action"] == "fill_report"
        assert "第一行" in parsed["thought"]


# ── tool execution tests ──


class TestExecuteTool:
    def test_unknown_tool_returns_error(self):
        result = execute_tool({}, "nonexistent_tool", {})
        assert result["ok"] is False
        assert "未知工具" in result["result_summary"]

    @patch("agent.executor._MODULE_RUNNERS", {})
    def test_missing_runner_returns_error(self):
        result = execute_tool({}, "solve_lab", {})
        assert result["ok"] is False


# ── react loop tests ──


class TestRunReactLoop:
    def _make_ctx(self, **overrides):
        ctx = {
            "settings": {
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "report_text": "实验报告全文...",
            "planner_input_text": "【作业要求】\n页面置换算法\n\n【待填报告】\n三、实验步骤",
            "question": {"type": "lab_report"},
            "user_profile": {"default_language": "python"},
            "module_results": {},
            "run_id": "test-run",
        }
        ctx.update(overrides)
        return ctx

    def _mock_chat_sequence(self, responses):
        calls = [0]

        def side_effect(settings, messages, **_kwargs):
            idx = min(calls[0], len(responses) - 1)
            calls[0] += 1
            return {"content": responses[idx], "reasoning_content": "", "finish_reason": "stop"}

        return side_effect

    # All loop tests need is_cancelled patched — without a run state in run_control
    # it defaults to True (run not found = cancelled).

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_done_on_first_round(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """LLM immediately says done."""
        mock_cancel.return_value = False
        mock_chat.side_effect = self._mock_chat_sequence(
            ["THOUGHT: 已完成\nACTION: done"]
        )
        result = run_react_loop("test-1", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_max_rounds_fallback(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """LLM never says done — loop exceeds MAX_REACT_ROUNDS."""
        mock_cancel.return_value = False
        mock_chat.side_effect = self._mock_chat_sequence(
            ["THOUGHT: 再试一次\nACTION: run_code\nPARAMS: {}"]
        )
        result = run_react_loop("test-2", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result  # Should complete gracefully

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_consecutive_failures_break(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """Consecutive tool failures should trigger fallback."""
        mock_cancel.return_value = False
        responses = []
        for _ in range(MAX_CONSECUTIVE_FAILURES + 2):
            responses.append("THOUGHT: 试一下\nACTION: nonexistent\nPARAMS: {}")
        mock_chat.side_effect = self._mock_chat_sequence(responses)
        result = run_react_loop("test-3", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_empty_action_retry(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """Empty action should be retried once then degrade."""
        mock_cancel.return_value = False
        mock_chat.side_effect = self._mock_chat_sequence(
            ["THOUGHT: hmm\nACTION: \nPARAMS: {}", "THOUGHT: ok\nACTION: done"]
        )
        result = run_react_loop("test-5", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_llm_exception_retry(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """LLM API exception should be caught and retried."""
        mock_cancel.return_value = False
        mock_chat.side_effect = [
            Exception("API timeout"),
            {"content": "THOUGHT: 重试成功\nACTION: done", "reasoning_content": "", "finish_reason": "stop"},
        ]
        result = run_react_loop("test-6", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_bootstrap_solve_lab_before_llm(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """AO-7: solve_lab runs via V4 pipeline before first LLM round."""
        mock_cancel.return_value = False
        mock_chat.return_value = {
            "content": '{"thought": "完成", "action": "done", "params": {}}',
            "reasoning_content": "",
            "finish_reason": "stop",
        }
        solve_calls: list[str] = []

        def solve_runner(ctx, p):
            solve_calls.append("solve_lab")
            return {
                "ok": True,
                "data": {
                    "code": "print(1)",
                    "parsed": {"steps_analysis": "s", "result_description": "r"},
                    "pipeline_meta": {"version": "v4", "code_status": "verified"},
                },
            }

        with patch.dict(
            "agent.executor._MODULE_RUNNERS",
            {
                "solve_lab": solve_runner,
                "present_deliverable": lambda c, p: {
                    "ok": True,
                    "data": {"deliverable": {"sections": []}},
                },
            },
            clear=False,
        ):
            with patch("agent.quality.verify_answer", return_value={"passed": True}):
                result = run_react_loop("test-bootstrap", self._make_ctx(), [], use_fallback=False)

        assert solve_calls == ["solve_lab"]
        trace = result.get("thought_trace") or []
        assert trace and trace[0].get("bootstrap") is True
        assert trace[0].get("action") == "solve_lab"
        mock_chat.assert_called()

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_cancel_mid_loop(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """Cancellation should trigger clean exit."""
        mock_cancel.return_value = True
        mock_chat.return_value = {"content": "THOUGHT: ...\nACTION: solve_lab\nPARAMS: {}", "reasoning_content": ""}
        result = run_react_loop("test-7", self._make_ctx(), [], use_fallback=False)
        assert result.get("cancelled") is True


    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_repair_on_malformed_json_success(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """IR-11: malformed JSON triggers single repair call, then continues."""
        mock_cancel.return_value = False

        def side_effect(settings, messages, phase=None, **_kwargs):
            if phase == "react_repair":
                return {
                    "content": '{"thought": "修正", "action": "done", "params": {}}',
                    "reasoning_content": "",
                    "finish_reason": "stop",
                }
            return {
                "content": '{"thought": "分析", "action": "", "params": {}}',
                "reasoning_content": "",
                "finish_reason": "stop",
            }

        mock_chat.side_effect = side_effect
        result = run_react_loop("test-repair-ok", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result
        repair_calls = [c for c in mock_chat.call_args_list if c.kwargs.get("phase") == "react_repair"]
        assert len(repair_calls) == 1

    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_repair_on_malformed_json_still_fails(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """IR-11: repair failure falls back to empty-action retry hints."""
        mock_cancel.return_value = False
        bad_json = '{"thought": "分析", "action": "", "params": {}}'
        main_calls = [0]

        def side_effect(settings, messages, phase=None, **_kwargs):
            if phase == "react_repair":
                return {"content": bad_json, "reasoning_content": "", "finish_reason": "stop"}
            main_calls[0] += 1
            if main_calls[0] >= 2:
                return {"content": "THOUGHT: ok\nACTION: done", "reasoning_content": "", "finish_reason": "stop"}
            return {"content": bad_json, "reasoning_content": "", "finish_reason": "stop"}

        mock_chat.side_effect = side_effect
        result = run_react_loop("test-repair-fail", self._make_ctx(), [], use_fallback=False)
        assert "ok" in result
        repair_calls = [c for c in mock_chat.call_args_list if c.kwargs.get("phase") == "react_repair"]
        assert len(repair_calls) == 1


class TestReactRepairHelper:
    @patch("agent.react_loop.chat_messages")
    def test_attempt_react_repair_success(self, mock_chat):
        mock_chat.return_value = {
            "content": '{"thought": "x", "action": "done", "params": {}}',
            "reasoning_content": "",
            "finish_reason": "stop",
        }
        settings = {"api_key": "sk-test", "provider": "deepseek", "model": "deepseek-chat"}
        result = _attempt_react_repair(
            settings,
            '{"thought": "bad", "action": ""}',
            error_reason="缺少 action",
        )
        assert result is not None
        assert result["action"] == "done"
        mock_chat.assert_called_once()
        assert mock_chat.call_args.kwargs.get("phase") == "react_repair"

    @patch("agent.react_loop.chat_messages")
    def test_attempt_react_repair_still_invalid(self, mock_chat):
        mock_chat.return_value = {
            "content": '{"thought": "still bad", "action": ""}',
            "reasoning_content": "",
            "finish_reason": "stop",
        }
        settings = {"api_key": "sk-test", "provider": "deepseek", "model": "deepseek-chat"}
        assert _attempt_react_repair(settings, '{"action": ""}', error_reason="缺少 action") is None


# ── System prompt tests ──


class TestReactSystemPrompt:
    def test_contains_tool_placeholder(self):
        assert "{tool_descriptions}" in REACT_SYSTEM_PROMPT
        assert "{plan_checklist}" in REACT_SYSTEM_PROMPT

    def test_format_works(self):
        from agent.react_prompts import react_response_schema_hint

        formatted = REACT_SYSTEM_PROMPT.format(
            tool_descriptions="[TOOL: test] desc",
            plan_checklist="- [ ] solve_lab",
            react_schema_hint=react_response_schema_hint(),
        )
        assert "[TOOL: test] desc" in formatted
        assert "- [ ] solve_lab" in formatted
        assert '"thought"' in formatted


# ── Execute tool integration test ──


class TestExecuteToolIntegration:
    def test_solve_lab_calls_runner(self):
        with patch("agent.executor._MODULE_RUNNERS", {
            "solve_lab": lambda ctx, p: {"ok": True, "data": {"language": "python", "code": "print(1)", "parsed": {"steps_analysis": "test", "result_description": "test"}}},
        }):
            result = execute_tool(
                {"user_profile": {"default_language": "python"}},
                "solve_lab",
                {"language": "python"},
            )
            assert result["ok"] is True
            assert "解题成功" in result["result_summary"]

    def test_run_code_calls_runner(self):
        with patch("agent.executor._MODULE_RUNNERS", {
            "run_code": lambda ctx, p: {"ok": True, "data": {"output": "Hello\n", "is_error": False}},
        }):
            result = execute_tool({}, "run_code", {})
            assert result["ok"] is True
            assert "代码执行成功" in result["result_summary"]

    def test_fill_report_calls_runner(self):
        with patch("agent.executor._MODULE_RUNNERS", {
            "fill_report": lambda ctx, p: {"ok": True, "data": {"output_path": "/tmp/out.docx"}},
        }):
            result = execute_tool({"output_mode": "fill_original"}, "fill_report", {})
            assert result["ok"] is True
            assert "报告填充完成" in result["result_summary"]


class TestReactHistoryCompaction:
    def test_keeps_system_and_bootstrap_then_recent_tail(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "bootstrap"},
        ]
        for i in range(40):
            history.append({"role": "assistant", "content": f"a{i}"})
            history.append({"role": "user", "content": f"[观察结果]\nresult {i}"})

        compacted = _compact_history_for_llm(history)
        assert compacted[0]["role"] == "system"
        assert compacted[1]["content"] == "bootstrap"
        assert len(compacted) <= 2 + REACT_TAIL_MAX_MESSAGES
        assert compacted[-1]["content"].startswith("[观察结果]\nresult 39")

    def test_observation_is_budget_trimmed(self):
        long_obs = "[观察结果]\n" + ("错误信息 " * 1000)
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "bootstrap"},
            {"role": "assistant", "content": "try fix"},
            {"role": "user", "content": long_obs},
        ]
        compacted = _compact_history_for_llm(history)
        trimmed = compacted[-1]["content"]
        assert trimmed.startswith("[观察结果]\n")
        assert len(trimmed) < len(long_obs)
