"""Unit tests for ReAct agent loop (Phase R1)."""

from unittest.mock import patch

import pytest

from agent.react_loop import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_REACT_ROUNDS,
    _parse_react_response,
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
        for name in ("solve_lab", "run_code", "screenshot", "fill_report", "render_uml", "finalize_report"):
            assert f"[TOOL: {name}]" in text

    def test_includes_descriptions(self):
        text = build_tools_prompt()
        for name, schema in REACT_TOOL_SCHEMAS.items():
            assert schema["description"] in text


class TestToolToModule:
    def test_known_actions(self):
        assert tool_to_module("solve_lab") == "solve_lab"
        assert tool_to_module("run_code") == "run_code"
        assert tool_to_module("screenshot") == "screenshot_ide"
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

        def side_effect(settings, messages):
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
    def test_cancel_mid_loop(self, mock_cancel, mock_release, mock_emit, mock_chat):
        """Cancellation should trigger clean exit."""
        mock_cancel.return_value = True
        mock_chat.return_value = {"content": "THOUGHT: ...\nACTION: solve_lab\nPARAMS: {}", "reasoning_content": ""}
        result = run_react_loop("test-7", self._make_ctx(), [], use_fallback=False)
        assert result.get("cancelled") is True


# ── System prompt tests ──


class TestReactSystemPrompt:
    def test_contains_tool_placeholder(self):
        assert "{tool_descriptions}" in REACT_SYSTEM_PROMPT
        assert "{plan_checklist}" in REACT_SYSTEM_PROMPT

    def test_format_works(self):
        formatted = REACT_SYSTEM_PROMPT.format(
            tool_descriptions="[TOOL: test] desc",
            plan_checklist="- [ ] solve_lab",
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

    def test_screenshot_calls_runner(self):
        with patch("agent.executor._MODULE_RUNNERS", {
            "screenshot_ide": lambda ctx, p: {"ok": True, "data": {"images_b64": ["aaa", "bbb"]}},
        }):
            result = execute_tool({}, "screenshot", {})
            assert result["ok"] is True
            assert "共 2 张" in result["result_summary"]

    def test_fill_report_calls_runner(self):
        with patch("agent.executor._MODULE_RUNNERS", {
            "fill_report": lambda ctx, p: {"ok": True, "data": {"output_path": "/tmp/out.docx"}},
        }):
            result = execute_tool({"output_mode": "fill_original"}, "fill_report", {})
            assert result["ok"] is True
            assert "报告填充完成" in result["result_summary"]
