"""
ReAct agent loop — LLM thinks → acts → observes → repeats (Phase R1).

The LLM receives a system prompt listing tools, the report text as first user
message, then alternates between assistant responses (THOUGHT/ACTION/PARAMS)
and user observations (tool results).  The loop terminates when the LLM outputs
``ACTION: done``, or when max rounds / consecutive failures are exceeded.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.cloze_run import is_code_cloze_run, is_mixed_assignment_run, step_checked
from agent.decision_log import append_decision
from agent.prompt_budget import estimate_tokens, fit_budget
from agent.react_prompts import (
    REACT_PROMPT_VERSION,
    REACT_REPAIR_PROMPT_VERSION,
    REACT_SYSTEM_PROMPT,
    build_plan_checklist,
    build_react_repair_prompt,
    react_parse_error,
    react_parse_needs_repair,
    react_response_schema_hint,
)
from agent.react_tools import (
    build_tools_prompt,
    emit_react_cycle,
    emit_react_thinking,
    execute_tool,
    tool_to_module,
)

_BOOTSTRAP_THOUGHT = "V4 流水线优先解题（bootstrap）"
_BOOTSTRAP_CLOZE_THOUGHT = "代码完形填空优先解题（bootstrap）"
from agent.run_control import emit_event, is_cancelled, release_run
from agent.types import max_consecutive_failures_for_mode
from llm_client import chat_messages
from log_util import loge, logi

MAX_REACT_ROUNDS = 16
MAX_CONSECUTIVE_FAILURES = max_consecutive_failures_for_mode("react")
MAX_RUN_CODE_FIX_CYCLES = 4
REACT_TAIL_MAX_MESSAGES = 12
REACT_TAIL_BUDGET_TOKENS = 2200
REACT_OBSERVATION_BUDGET_TOKENS = 320

# Regex for legacy THOUGHT/ACTION/PARAMS parsing (fallback)
_RE_THOUGHT = re.compile(r"THOUGHT:\s*(.+?)(?=\nACTION:|\Z)", re.DOTALL | re.IGNORECASE)
_RE_ACTION = re.compile(r"ACTION:\s*(\S+)", re.IGNORECASE)
_RE_PARAMS = re.compile(r"PARAMS:\s*(\{.*?\})", re.DOTALL | re.IGNORECASE)


def _try_parse_react_json(content: str) -> dict[str, Any] | None:
    """Extract ReAct JSON object from LLM output."""
    text = (content or "").strip()
    if not text:
        return None

    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(text)
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        candidates.append(brace.group(0))

    for raw in candidates:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and ("action" in obj or "thought" in obj):
                return obj
        except (json.JSONDecodeError, TypeError):
            from modules.lab_parse import _repair_truncated_json

            repaired = _repair_truncated_json(raw)
            if isinstance(repaired, dict) and ("action" in repaired or "thought" in repaired):
                return repaired
            continue
    return None


def _normalize_react_parsed(obj: dict[str, Any]) -> dict[str, Any]:
    params = obj.get("params")
    return {
        "thought": str(obj.get("thought") or "").strip(),
        "action": str(obj.get("action") or "").strip().lower(),
        "params": params if isinstance(params, dict) else {},
    }


def _parse_react_response_legacy(content: str) -> dict[str, Any]:
    """Extract THOUGHT, ACTION, PARAMS from legacy LLM output."""
    if not content:
        return {"thought": "", "action": "", "params": {}}

    thought_m = _RE_THOUGHT.search(content)
    action_m = _RE_ACTION.search(content)
    params_m = _RE_PARAMS.search(content)

    thought = (thought_m.group(1) or "").strip() if thought_m else ""
    action = (action_m.group(1) or "").strip().lower() if action_m else ""
    params: dict = {}

    if params_m:
        try:
            parsed = json.loads(params_m.group(1))
            if isinstance(parsed, dict):
                params = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    if not action and not thought:
        text = content.strip()
        lower = text.lower()
        if "done" in lower and len(text) < 30:
            return {"thought": text, "action": "done", "params": {}}
        return {"thought": text, "action": "", "params": {}}

    return {"thought": thought, "action": action, "params": params}


def parse_react_response(content: str) -> dict[str, Any]:
    """Parse ReAct LLM output: JSON first, THOUGHT/ACTION fallback."""
    obj = _try_parse_react_json(content)
    if obj is not None:
        return _normalize_react_parsed(obj)
    return _parse_react_response_legacy(content)


def _attempt_react_repair(
    settings: dict,
    raw_content: str,
    *,
    error_reason: str,
    ctx: dict | None = None,
) -> dict[str, Any] | None:
    """Single-shot LLM repair when JSON-mode output is malformed (IR-11)."""
    from agent.prompts import record_prompt_version

    record_prompt_version(ctx, "react_repair", REACT_REPAIR_PROMPT_VERSION)
    prompt = build_react_repair_prompt(raw_content, error_reason)
    try:
        chat_result = chat_messages(
            settings,
            [{"role": "user", "content": prompt}],
            phase="react_repair",
        )
    except Exception as e:
        loge("react", f"repair LLM call failed: {e}")
        return None

    repaired_raw = chat_result.get("content") or ""
    repaired = parse_react_response(repaired_raw)
    if repaired.get("action") and not react_parse_needs_repair(repaired_raw, repaired):
        logi("react", f"repair succeeded action={repaired.get('action')}")
        return repaired
    logi("react", "repair did not yield a valid action")
    return None


# Backward-compatible alias for existing tests
_parse_react_response = parse_react_response


def _solve_lab_checked(steps: list) -> bool:
    for step in steps:
        if step.get("module") == "solve_lab":
            return step.get("default_checked", True) is not False
    return not step_checked(steps, "solve_code_cloze")


def _bootstrap_mixed_assignment_pipeline(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    thought_history: list[dict[str, Any]],
) -> bool:
    """Run solve_theory / solve_code_cloze segments in plan order before ReAct."""
    all_ok = True
    for step in steps:
        module = step.get("module") or ""
        if module not in ("solve_theory", "solve_code_cloze"):
            continue
        if not step_checked(steps, module):
            continue
        params = dict(step.get("params") or {})
        seg_id = params.get("segment_id")
        already = any(
            r.get("module") == module and r.get("segment_id") == seg_id
            for r in (ctx.get("segment_solve_results") or [])
        )
        if already:
            continue
        tool_result = execute_tool(ctx, module, params)
        ok = bool(tool_result.get("ok"))
        all_ok = all_ok and ok
        emit_react_cycle(
            run_id,
            0,
            MAX_REACT_ROUNDS,
            f"混排卷 bootstrap：{module}",
            module,
            ok,
            tool_result.get("result_summary") or "",
        )
        thought_history.append(
            {
                "round": 0,
                "max_rounds": MAX_REACT_ROUNDS,
                "thought": f"混排卷 bootstrap：{module}",
                "action": module,
                "params": params,
                "result_ok": ok,
                "result_summary": tool_result.get("result_summary") or "",
                "bootstrap": True,
            }
        )
    return all_ok


def _bootstrap_solve_pipeline(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    thought_history: list[dict[str, Any]],
) -> bool:
    if is_mixed_assignment_run(ctx, steps):
        return _bootstrap_mixed_assignment_pipeline(
            run_id, ctx, steps, thought_history=thought_history
        )
    if is_code_cloze_run(ctx, steps):
        return _bootstrap_solve_code_cloze_pipeline(
            run_id, ctx, steps, thought_history=thought_history
        )
    return _bootstrap_solve_lab_pipeline(
        run_id, ctx, steps, thought_history=thought_history
    )


def _bootstrap_solve_code_cloze_pipeline(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    thought_history: list[dict[str, Any]],
) -> bool:
    results = ctx.get("module_results") or {}
    if (results.get("solve_code_cloze") or {}).get("ok"):
        return True
    if steps and not step_checked(steps, "solve_code_cloze"):
        return False

    append_decision(
        ctx,
        agent="react_loop",
        decision="bootstrap_solve_code_cloze",
        target="solve_code_cloze",
        reason="code_cloze: structured blanks before ReAct LLM",
    )

    params: dict[str, Any] = {}
    for step in steps:
        if step.get("module") == "solve_code_cloze":
            params = dict(step.get("params") or {})
            break
    if not params.get("language"):
        cloze = (ctx.get("metadata") or {}).get("code_cloze") or {}
        lang = cloze.get("language_hint") or (ctx.get("user_profile") or {}).get("default_language")
        if lang:
            params["language"] = lang

    tool_result = execute_tool(ctx, "solve_code_cloze", params)
    ok = bool(tool_result.get("ok"))
    summary = tool_result.get("result_summary") or ""

    emit_react_cycle(
        run_id, 0, MAX_REACT_ROUNDS, _BOOTSTRAP_CLOZE_THOUGHT, "solve_code_cloze", ok, summary
    )
    thought_history.append(
        {
            "round": 0,
            "max_rounds": MAX_REACT_ROUNDS,
            "thought": _BOOTSTRAP_CLOZE_THOUGHT,
            "action": "solve_code_cloze",
            "params": params,
            "result_ok": ok,
            "result_summary": summary,
            "bootstrap": True,
        }
    )
    return ok


def _bootstrap_solve_lab_pipeline(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    thought_history: list[dict[str, Any]],
) -> bool:
    """AO-7: Run V4 solve_lab before ReAct LLM loop when not already done."""
    results = ctx.get("module_results") or {}
    if (results.get("solve_lab") or {}).get("ok"):
        return True
    if not _solve_lab_checked(steps):
        return False

    append_decision(
        ctx,
        agent="react_loop",
        decision="bootstrap_solve_lab",
        target="solve_lab",
        reason="AO-7 pipeline-first: V4 solve before ReAct LLM",
    )

    profile = ctx.get("user_profile") or {}
    params: dict[str, Any] = {}
    lang = profile.get("default_language")
    if lang:
        params["language"] = lang
    settings = ctx.get("settings") or {}
    if profile.get("prefer_uml") or settings.get("include_uml"):
        params["include_uml"] = True

    tool_result = execute_tool(ctx, "solve_lab", params)
    ok = bool(tool_result.get("ok"))
    summary = tool_result.get("result_summary") or ""

    emit_react_cycle(run_id, 0, MAX_REACT_ROUNDS, _BOOTSTRAP_THOUGHT, "solve_lab", ok, summary)
    thought_history.append(
        {
            "round": 0,
            "max_rounds": MAX_REACT_ROUNDS,
            "thought": _BOOTSTRAP_THOUGHT,
            "action": "solve_lab",
            "params": params,
            "result_ok": ok,
            "result_summary": summary,
            "bootstrap": True,
        }
    )

    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    solve_data = solve_mr.get("data") or {}
    meta = solve_data.get("pipeline_meta") or ctx.get("pipeline_meta")
    if meta:
        ctx["pipeline_meta"] = meta
    if solve_data.get("solve_session"):
        ctx["solve_session"] = solve_data["solve_session"]

    return ok


def _empty_action_recovery_hint(ctx: dict, steps: list) -> str:
    if is_mixed_assignment_run(ctx, steps) or is_code_cloze_run(ctx, steps):
        return (
            "你已经连续多轮未输出有效 ACTION。如果认为任务已完成请输出 ACTION: done。"
            "如果需要继续，请选择: present_deliverable / done（勿 solve_lab / run_code）。"
        )
    return (
        "你已经连续多轮未输出有效 ACTION。如果认为任务已完成请输出 ACTION: done。"
        "如果需要继续，请选择: solve_lab / run_code / fill_report / render_uml / done。"
    )


def _compress_observation_content(content: str) -> str:
    prefix = "[观察结果]\n"
    if not content.startswith(prefix):
        return content
    body = content[len(prefix) :]
    compact = fit_budget(
        body,
        budget_tokens=REACT_OBSERVATION_BUDGET_TOKENS,
        preserve_sections=["错误", "输出", "异常", "Traceback"],
    )
    return f"{prefix}{compact}"


def _compact_history_for_llm(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep system/bootstrap context + bounded tail for ReAct LLM calls (IR-7)."""
    if len(history) <= 2:
        return [
            {
                "role": str(m.get("role") or "user"),
                "content": str(m.get("content") or ""),
            }
            for m in history
        ]

    head = [
        {
            "role": str(m.get("role") or "user"),
            "content": str(m.get("content") or ""),
        }
        for m in history[:2]
    ]
    tail = history[2:]
    selected_rev: list[dict[str, str]] = []
    used_tokens = 0

    for msg in reversed(tail):
        role = str(msg.get("role") or "user")
        content = str(msg.get("content") or "")
        content = _compress_observation_content(content)
        need = estimate_tokens(content)

        if selected_rev and (
            len(selected_rev) >= REACT_TAIL_MAX_MESSAGES
            or (used_tokens + need) > REACT_TAIL_BUDGET_TOKENS
        ):
            break

        if not selected_rev and need > REACT_TAIL_BUDGET_TOKENS:
            content = fit_budget(
                content,
                budget_tokens=max(200, REACT_TAIL_BUDGET_TOKENS - 100),
                preserve_sections=["错误", "输出", "异常", "Traceback"],
            )
            need = estimate_tokens(content)

        selected_rev.append({"role": role, "content": content})
        used_tokens += need

    return head + list(reversed(selected_rev))


def _bootstrap_user_note(ctx: dict, steps: list) -> str:
    if is_mixed_assignment_run(ctx, steps):
        theory_ok = any(
            r.get("module") == "solve_theory" and r.get("data")
            for r in (ctx.get("segment_solve_results") or [])
        )
        cloze_ok = any(
            r.get("module") == "solve_code_cloze" and r.get("data")
            for r in (ctx.get("segment_solve_results") or [])
        )
        if theory_ok or cloze_ok:
            return (
                "【系统】混排卷各段解题 bootstrap 已按文档顺序执行。"
                "请调用 present_deliverable 汇编分段答案，或输出 action: done。"
                "勿调用 solve_lab / run_code（简答 + 编号填空，不是完整实验报告）。"
            )
        return (
            "本题是混排卷（简答 + 代码填空）。请按计划顺序调用 solve_theory / solve_code_cloze，"
            "然后 present_deliverable，或输出 action: done。勿调用 solve_lab / run_code。"
        )
    if is_code_cloze_run(ctx, steps):
        cloze_ok = bool((ctx.get("module_results") or {}).get("solve_code_cloze", {}).get("ok"))
        if not cloze_ok:
            return (
                "本题是代码完形填空。请调用 solve_code_cloze，然后 present_deliverable，"
                "或输出 action: done。勿调用 solve_lab / run_code。"
            )
        return (
            "【系统】solve_code_cloze 已自动完成。"
            "请调用 present_deliverable 汇编空号答案，或输出 action: done。"
            "勿调用 solve_lab / run_code（编号填空，不是完整实验报告）。"
        )

    solve_ok = bool((ctx.get("module_results") or {}).get("solve_lab", {}).get("ok"))
    if not solve_ok:
        return "请开始解题。若 solve_lab 失败可重试一次，否则输出 action: done。"
    return (
        "【系统】solve_lab（V4 流水线）已自动完成。"
        "请根据计划补跑 render_uml / present_deliverable / finalize_report，"
        "或输出 action: done。勿重复 solve_lab，除非解题明显失败。"
    )


def run_react_loop(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    use_fallback: bool = True,
) -> dict[str, Any]:
    """Execute the ReAct agent loop.

    Emits SSE events: react_thinking, react_cycle, verification, done.
    """
    settings = ctx.get("settings") or {}
    raw_report = ctx.get("planner_input_text") or ctx.get("report_text") or ""
    budgeted_report = fit_budget(
        raw_report,
        budget_tokens=2800,
        preserve_sections=["步骤", "结果", "要求"],
        section_map=(ctx.get("metadata") or {}).get("section_map"),
    )

    # Build initial messages
    tools_prompt = build_tools_prompt()

    def _refresh_system_message():
        checklist = build_plan_checklist(steps, ctx)
        return REACT_SYSTEM_PROMPT.format(
            tool_descriptions=tools_prompt,
            plan_checklist=checklist,
            react_schema_hint=react_response_schema_hint(),
        )

    system_msg = _refresh_system_message()

    output_mode = ctx.get("output_mode", "deliverable")
    _MODE_GUIDANCE = {
        "deliverable": "生成答案后调用 present_deliverable 完成；不要默认 fill_report，用户自行复制粘贴。",
        "fill_original": "【高级】最后可调用 fill_report 尝试填入上传文档（不保证版式）。",
        "new_document": "【高级】最后可调用 fill_report 生成独立 Word（实验性）。",
        "answer_only": "与 deliverable 相同：答案在界面展示，fill_report 非必须。",
    }
    mode_note = _MODE_GUIDANCE.get(output_mode, _MODE_GUIDANCE["deliverable"])

    thought_history: list[dict[str, Any]] = []
    _bootstrap_solve_pipeline(run_id, ctx, steps, thought_history=thought_history)
    bootstrap_note = _bootstrap_user_note(ctx, steps)

    history: list[dict] = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": (
                f"【实验报告全文】\n{budgeted_report}\n\n"
                f"【输出模式】{mode_note}\n\n"
                f"{bootstrap_note}"
            ),
        },
    ]

    consecutive_failures = 0
    empty_retries = 0
    run_code_failures = 0
    last_action = ""

    def _emit(ev: dict):
        emit_event(run_id, ev)

    from agent.orchestrator import RunOrchestrator

    def on_decision(entry):
        _emit({"type": "decision", **entry})

    orch = RunOrchestrator(run_id, ctx, emit=_emit, on_decision=on_decision)
    ctx["_orchestrator"] = orch

    append_decision(
        ctx,
        agent="react_loop",
        decision="react_run_start",
        target="run",
        reason=f"ReAct mode, max {MAX_REACT_ROUNDS} rounds",
    )
    from agent.prompts import record_prompt_version

    record_prompt_version(ctx, "react", REACT_PROMPT_VERSION)

    for round_num in range(1, MAX_REACT_ROUNDS + 1):
        if is_cancelled(run_id):
            release_run(run_id, "cancelled")
            _emit({"type": "done", "ok": False, "cancelled": True})
            return {"cancelled": True}

        history[0] = {"role": "system", "content": _refresh_system_message()}

        # 1. Emit thinking event + call LLM
        emit_react_thinking(run_id, round_num)
        logi("react", f"round {round_num}/{MAX_REACT_ROUNDS} calling LLM…")

        try:
            llm_history = _compact_history_for_llm(history)
            chat_result = chat_messages(settings, llm_history, phase="react")
        except Exception as e:
            loge("react", f"LLM call failed round {round_num}: {e}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                break
            history.append(
                {"role": "user", "content": f"[系统提示]\nLLM 调用失败: {e}\n请重试或输出 ACTION: done 结束。"}
            )
            continue

        # 2. Parse response (JSON first; optional single repair for malformed JSON)
        raw_content = chat_result.get("content") or ""
        parsed = parse_react_response(raw_content)
        if react_parse_needs_repair(raw_content, parsed):
            error_reason = react_parse_error(raw_content, parsed)
            append_decision(
                ctx,
                agent="react_loop",
                decision="react_parse_repair",
                target="parse",
                reason=error_reason,
            )
            repaired = _attempt_react_repair(
                settings,
                raw_content,
                error_reason=error_reason,
                ctx=ctx,
            )
            if repaired:
                parsed = repaired
                empty_retries = 0
        thought = parsed["thought"]
        action = parsed["action"]
        action_params = parsed["params"]

        logi("react", f"round {round_num} action={action} thought_len={len(thought)}")

        # 3. Check termination
        if action == "done":
            logi("react", f"LLM signalled done at round {round_num}")
            done_cycle = {
                "type": "react_cycle",
                "round": round_num,
                "max_rounds": MAX_REACT_ROUNDS,
                "thought": thought,
                "action": "done",
                "result_ok": True,
                "result_summary": "ReAct 自主完成",
            }
            thought_history.append(
                {
                    "round": round_num,
                    "max_rounds": MAX_REACT_ROUNDS,
                    "thought": thought,
                    "action": "done",
                    "params": {},
                    "result_ok": True,
                    "result_summary": "ReAct 自主完成",
                }
            )
            _emit(done_cycle)
            break

        # 4. Empty action → retry with escalating hints, then degrade
        if not action:
            empty_retries += 1
            if empty_retries >= 2:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    break
                hint = _empty_action_recovery_hint(ctx, steps)
                history.append({"role": "user", "content": f"[系统提示]\n{hint}"})
                empty_retries = 0
            else:
                history.append(
                    {"role": "user", "content": "[系统提示]\n未检测到有效 ACTION，请按格式输出 THOUGHT/ACTION/PARAMS。"}
                )
            continue

        # 5. Execute tool
        tool_result = execute_tool(ctx, action, action_params)
        result_ok = bool(tool_result.get("ok"))
        result_summary = tool_result.get("result_summary") or ""

        # 6. Emit react_cycle SSE event
        emit_react_cycle(run_id, round_num, MAX_REACT_ROUNDS, thought, action, result_ok, result_summary)
        thought_history.append(
            {
                "round": round_num,
                "max_rounds": MAX_REACT_ROUNDS,
                "thought": thought,
                "action": action,
                "params": action_params or {},
                "result_ok": result_ok,
                "result_summary": result_summary,
            }
        )

        # 7. Track failures
        if not result_ok:
            consecutive_failures += 1
            last_action = action
            if action in ("run_code", "fix_code"):
                run_code_failures += 1
            if run_code_failures >= MAX_RUN_CODE_FIX_CYCLES and action in ("run_code", "fix_code"):
                from modules.deliverable import is_content_only_output_mode

                if is_content_only_output_mode(output_mode):
                    hint = (
                        "[系统提示]\n"
                        "代码验证已尝试多次。请立即停止 fix_code/run_code，"
                        "调用 ACTION: finalize_report（一键 UML+交付），"
                        "或依次 render_uml → present_deliverable。"
                        "solve_lab 已生成答案，代码运行失败不能阻止在答案工作区交付。"
                    )
                else:
                    hint = (
                        "[系统提示]\n"
                        "代码验证已尝试多次。请立即停止 fix_code/run_code，"
                        "调用 ACTION: finalize_report（一键 UML+填表），"
                        "或依次 render_uml → present_deliverable / fill_report。"
                        "实验报告类作业应完成填表或交付，代码运行失败不能作为跳过理由。"
                    )
                history.append({"role": "user", "content": hint})
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                failed_mod = tool_to_module(last_action) or last_action
                if failed_mod and failed_mod != "solve_lab":
                    replanned = orch.maybe_replan(
                        failed_mod,
                        result_summary or "ReAct tool failed",
                        emit_plan_updated=True,
                    )
                    if replanned:
                        consecutive_failures = 0
                        run_code_failures = 0
                        steps = list(
                            (ctx.get("plan") or {}).get("steps")
                            or ctx.get("confirmed_steps")
                            or steps
                        )
                        history.append(
                            {
                                "role": "user",
                                "content": "[系统提示]\n计划已调整，请按新步骤继续。",
                            }
                        )
                        continue
                logi("react", f"consecutive failures={consecutive_failures}, falling back")
                break
        else:
            consecutive_failures = 0
            if action == "run_code":
                run_code_failures = 0

        # 8. Append to conversation history
        assistant_content = f"THOUGHT: {thought}\nACTION: {action}"
        if action_params:
            assistant_content += f"\nPARAMS: {json.dumps(action_params, ensure_ascii=False)}"
        history.append({"role": "assistant", "content": assistant_content})
        history.append({"role": "user", "content": f"[观察结果]\n{result_summary}"})

    # ── Post-loop: auto-finalize + verification + done ──
    from agent.react_finalize import react_finalize_pipeline

    finalize_cycles = react_finalize_pipeline(
        run_id, ctx, steps, max_rounds=MAX_REACT_ROUNDS, emit_fn=_emit
    )
    thought_history.extend(finalize_cycles)

    _emit_progress_done_steps(ctx, steps)

    from agent.run_result import complete_agent_run

    return complete_agent_run(
        run_id,
        ctx,
        orch,
        emit=_emit,
        use_fallback=use_fallback,
        extra_final={"thought_trace": thought_history},
        agent_log_tag="react",
    )


def _emit_progress_done_steps(ctx: dict, steps: list):
    """After ReAct loop, emit tail-step progress for UI (present_deliverable or fill_report)."""
    from agent.executor import progress_payload_for_module_result
    from modules.deliverable import is_content_only_output_mode

    results = ctx.get("module_results") or {}
    output_mode = ctx.get("output_mode", "deliverable")
    tail = "present_deliverable" if is_content_only_output_mode(output_mode) else "fill_report"
    if tail not in results:
        return
    payload = progress_payload_for_module_result(tail, results[tail])
    payload["phase"] = "final"
    emit_event(ctx.get("run_id") or "", payload)
