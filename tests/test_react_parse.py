"""ReAct JSON parse + THOUGHT/ACTION fallback (V3-3a)."""

import pytest

from agent.react_loop import parse_react_response
from agent.react_prompts import REACT_SYSTEM_PROMPT, build_plan_checklist


class TestParseReactJson:
    def test_pure_json(self):
        resp = '{"thought": "先解题", "action": "solve_lab", "params": {"language": "java"}}'
        parsed = parse_react_response(resp)
        assert parsed["action"] == "solve_lab"
        assert parsed["params"] == {"language": "java"}
        assert "先解题" in parsed["thought"]

    def test_json_code_fence(self):
        resp = '```json\n{"thought": "完成", "action": "done", "params": {}}\n```'
        parsed = parse_react_response(resp)
        assert parsed["action"] == "done"

    def test_json_with_surrounding_text(self):
        resp = '分析如下：\n{"thought": "运行", "action": "run_code", "params": {}}'
        parsed = parse_react_response(resp)
        assert parsed["action"] == "run_code"

    def test_empty_params_default(self):
        resp = '{"thought": "x", "action": "fill_report"}'
        parsed = parse_react_response(resp)
        assert parsed["params"] == {}


class TestParseReactLegacyFallback:
    def test_thought_action_params(self):
        resp = "THOUGHT: 应该先解题\nACTION: solve_lab\nPARAMS: {\"language\": \"python\"}"
        parsed = parse_react_response(resp)
        assert parsed["action"] == "solve_lab"
        assert parsed["params"]["language"] == "python"

    def test_done_legacy(self):
        resp = "THOUGHT: 全部完成\nACTION: done"
        parsed = parse_react_response(resp)
        assert parsed["action"] == "done"

    def test_only_done_text(self):
        parsed = parse_react_response("done")
        assert parsed["action"] == "done"


class TestPlanChecklist:
    def test_checklist_marks_completed(self):
        steps = [
            {"module": "solve_lab", "params": {"language": "java"}, "default_checked": True},
            {"module": "run_code", "default_checked": True},
        ]
        ctx = {"module_results": {"solve_lab": {"ok": True}}}
        text = build_plan_checklist(steps, ctx)
        assert "[x] solve_lab (language=java)" in text
        assert "[ ] run_code" in text
        assert "用户已确认的计划步骤" in text

    def test_system_prompt_includes_checklist(self):
        formatted = REACT_SYSTEM_PROMPT.format(
            tool_descriptions="[TOOL: test]",
            plan_checklist="- [ ] solve_lab",
        )
        assert "[TOOL: test]" in formatted
        assert "- [ ] solve_lab" in formatted
        assert '"thought"' in formatted
