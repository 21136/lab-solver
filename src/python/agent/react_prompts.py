"""
ReAct agent system prompt template (Phase R1, V3-3 JSON + plan checklist).
"""

from __future__ import annotations

import re

from agent.registry import react_tool_schemas

# IR-15: versioned alongside prompts.py PromptTemplate entries
REACT_PROMPT_VERSION = "1.2.0"
REACT_REPAIR_PROMPT_VERSION = "1.0.0"

# IR-11: machine-readable schema for prompts + validation
REACT_RESPONSE_JSON_SCHEMA: dict[str, str] = {
    "type": "object",
    "required": "thought, action, params",
    "thought": "string — 中文分析与下一步计划",
    "action": "string — 工具名或 done",
    "params": "object — 工具参数；无参数时用 {}",
}

REACT_REPAIR_USER_PROMPT = """你上一轮的 ReAct 输出无法被程序解析。请**仅**输出一个合法 JSON 对象（不要 markdown 代码块，不要其它说明）。

JSON schema（必填）：
{{"thought": "<string>", "action": "<tool|done>", "params": {{}}}}

合法 action 值：{valid_actions}

解析失败原因：{error_reason}

原始输出：
{raw_content}

请直接输出修正后的 JSON："""


def react_valid_actions() -> frozenset[str]:
    """Known ReAct tool names plus terminal ``done``."""
    return frozenset(list(react_tool_schemas().keys()) + ["done"])


def build_react_repair_prompt(raw_content: str, error_reason: str) -> str:
    actions = ", ".join(sorted(react_valid_actions()))
    return REACT_REPAIR_USER_PROMPT.format(
        valid_actions=actions,
        error_reason=error_reason or "格式无效或缺少 action",
        raw_content=(raw_content or "")[:2000],
    )


def react_response_schema_hint() -> str:
    """Compact schema block for the system prompt."""
    actions = ", ".join(sorted(react_valid_actions()))
    return (
        f'{{"thought": "<string>", "action": "<{actions}>", "params": {{}}}}'
    )


def _content_looks_like_json_attempt(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    lower = text.lower()
    if "```json" in lower:
        return True
    if text.startswith("{") and ("thought" in lower or "action" in lower):
        return True
    if re.search(r'\{\s*"thought"', text, re.IGNORECASE):
        return True
    return False


def react_parse_error(content: str, parsed: dict) -> str:
    """Human-readable reason why a ReAct parse needs repair."""
    action = (parsed.get("action") or "").strip().lower()
    if not action:
        return "缺少或空的 action 字段"
    if action not in react_valid_actions():
        return f"未知 action: {action}"
    if _content_looks_like_json_attempt(content):
        return "JSON 结构不完整或无法解析"
    return "格式无效"


def react_parse_needs_repair(content: str, parsed: dict) -> bool:
    """True when JSON-mode output is malformed and a repair LLM call may help (IR-11)."""
    action = (parsed.get("action") or "").strip().lower()
    if action in react_valid_actions():
        return False
    if not _content_looks_like_json_attempt(content):
        return False
    return True


REACT_SYSTEM_PROMPT = """你是实验报告解题 ReAct Agent。你的任务是对实验报告解题：生成答案、可选验证代码，并在答案工作区交付内容。

你可以调用以下工具（每次只调用一个）：

{tool_descriptions}

{plan_checklist}

【推荐工作流】（AO-7：solve_lab 已由 V4 流水线自动完成，勿重复调用除非明显失败）
1. solve_lab — 仅当 bootstrap 未成功或答案全错时再调用
2. render_uml — 若 solve_lab 返回了 diagrams，**尽早**渲染（不依赖 run_code 成功）
2b. fix_diagrams — render_uml 失败或验错未通过时，根据 validation/issues 修正 diagrams，然后**再次** render_uml
3. run_code — 运行代码验证（可选；多文件/设计模式类实验允许失败后继续）
3b. fix_code — run_code 失败时修复，**最多反复 2～3 次**
4. present_deliverable — 汇编答案交付物（默认终点；用户从答案工作区复制）
5. fill_report — 【实验性 / 高级】尝试填入 Word；失败不影响主流程
6. finalize_report — **一键**完成 render_uml + present_deliverable（或高级填表）
7. done — 全部完成后终止

【输出格式】仅输出一个 JSON 对象（不要 markdown 代码块），必须包含 thought / action / params 三个字段：

{react_schema_hint}

- action 必须是合法工具名或 done；params 必须是 JSON 对象（无参数时用 {{}}）
- 不要输出 markdown 代码块或其它说明文字

若无法输出 JSON，可退化为 THOUGHT/ACTION/PARAMS 文本格式（不推荐）。

【规则】
- 每次只输出一组 thought/action/params
- 调用工具后会收到观察结果，请根据结果决定下一步
- **交付优先**：solve_lab 完成后优先 present_deliverable 或 finalize_report；填表为可选实验能力
- run_code 失败处理：
  1. 编译/运行错误 → fix_code 后重试 run_code（最多 2～3 轮）
  2. 仍失败 → 调用 finalize_report 或 present_deliverable，不要无限 fix_code
  3. 设计模式/多文件 Java：可合并为单文件 main，或跳过 run_code 直接 finalize
- render_uml 与 present_deliverable / fill_report 不依赖 run_code 成功
- render_uml 返回 validation 失败或 errors 时，优先 fix_diagrams 再 render_uml，不要直接 done
- 代码中禁止 Servlet/JSP；Java 优先单文件 public class + main
- 代码及 println/print 输出禁止 emoji 与装饰性 Unicode（✅❌🔴 等），只用中文和 ASCII
- 同一个工具连续失败 3 次后应换策略（finalize_report）或 action: done
- 不需要输出 solved 标记，thought 直接写分析内容"""


def _plan_is_mixed_assignment(steps: list, ctx: dict) -> bool:
    from agent.cloze_run import is_mixed_assignment_run

    return is_mixed_assignment_run(ctx, steps or [])


def _plan_is_code_cloze(steps: list, ctx: dict) -> bool:
    if _plan_is_mixed_assignment(steps, ctx):
        return False
    if any(
        (s.get("module") or "") == "solve_code_cloze"
        and s.get("default_checked", True) is not False
        for s in (steps or [])
    ):
        return True
    question = ctx.get("question") or {}
    if question.get("type") == "code_cloze":
        return True
    meta = ctx.get("metadata") or {}
    return meta.get("question_type") == "code_cloze" or bool(
        (meta.get("code_cloze") or {}).get("is_code_cloze")
    )


def _segment_step_done(ctx: dict, module: str, seg_id) -> bool:
    if seg_id is not None:
        for row in ctx.get("segment_solve_results") or []:
            if row.get("module") == module and row.get("segment_id") == seg_id:
                return bool(row.get("data"))
    return bool((ctx.get("module_results") or {}).get(module, {}).get("ok"))


def build_plan_checklist(steps: list, ctx: dict) -> str:
    """Build deterministic plan checklist from confirmed steps + module_results."""
    mixed = _plan_is_mixed_assignment(steps, ctx)
    code_cloze = _plan_is_code_cloze(steps, ctx)
    if not steps and not mixed and not code_cloze:
        return ""

    from modules.deliverable import is_content_only_output_mode

    output_mode = ctx.get("output_mode", "deliverable")
    content_only = is_content_only_output_mode(output_mode)
    results = ctx.get("module_results") or {}
    lines: list[str] = []
    if mixed:
        lines.extend(
            [
                "【题型】混排卷 — 按文档顺序 solve_theory / solve_code_cloze，禁止 solve_lab / run_code",
                "",
            ]
        )
    elif code_cloze:
        lines.extend(
            [
                "【题型】代码完形填空 — 使用 solve_code_cloze，禁止 solve_lab / run_code",
                "",
            ]
        )
    lines.append("【用户已确认的计划步骤】")

    for step in steps:
        module = (step.get("module") or "").strip()
        if not module:
            continue
        checked = step.get("default_checked", True) is not False
        if not checked:
            lines.append(f"- [—] {module}（用户未勾选）")
            continue
        params = step.get("params") or {}
        seg_id = params.get("segment_id")
        ok = (
            _segment_step_done(ctx, module, seg_id)
            if mixed and module in ("solve_theory", "solve_code_cloze")
            else bool((results.get(module) or {}).get("ok"))
        )
        mark = "x" if ok else " "
        param_bits = []
        title = (params.get("segment_title") or "").strip()
        if title:
            param_bits.append(title)
        if params.get("language"):
            param_bits.append(f"language={params['language']}")
        suffix = f" ({', '.join(param_bits)})" if param_bits else ""
        lines.append(f"- [{mark}] {module}{suffix}")

    lines.append("")
    if mixed:
        lines.append(
            "规则：按上表顺序完成各段 → present_deliverable；"
            "勿 solve_lab / run_code / fix_code / fill_report。"
        )
    elif code_cloze:
        lines.append(
            "规则：须 solve_code_cloze → present_deliverable；"
            "勿 solve_lab / run_code / fix_code / fill_report（无完整可运行程序要求）。"
        )
    elif content_only:
        lines.append(
            "规则：须先完成 solve_lab；默认以 present_deliverable 结束（答案工作区复制）；"
            "若 run_code 多次失败，优先 finalize_report，勿默认 fill_report。"
        )
    else:
        lines.append(
            "规则：须先完成 solve_lab；默认以 present_deliverable 或 fill_report 结束；"
            "若 run_code 多次失败，优先 finalize_report。"
        )
    return "\n".join(lines)
