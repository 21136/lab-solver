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

from agent.decision_log import append_decision
from agent.prompt_budget import fit_budget
from agent.react_prompts import REACT_SYSTEM_PROMPT, build_plan_checklist
from agent.react_tools import (
    build_tools_prompt,
    emit_react_cycle,
    emit_react_thinking,
    execute_tool,
    tool_to_module,
)
from agent.run_control import emit_event, is_cancelled, release_run
from llm_client import chat_messages
from log_util import loge, logi

MAX_REACT_ROUNDS = 16
MAX_CONSECUTIVE_FAILURES = 4
MAX_RUN_CODE_FIX_CYCLES = 4

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
            continue
    return None


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
        params = obj.get("params")
        return {
            "thought": str(obj.get("thought") or "").strip(),
            "action": str(obj.get("action") or "").strip().lower(),
            "params": params if isinstance(params, dict) else {},
        }
    return _parse_react_response_legacy(content)


# Backward-compatible alias for existing tests
_parse_react_response = parse_react_response


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

    history: list[dict] = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": (
                f"【实验报告全文】\n{budgeted_report}\n\n"
                f"【输出模式】{mode_note}\n\n"
                "请开始解题。先调用 solve_lab 生成答案。"
            ),
        },
    ]

    consecutive_failures = 0
    empty_retries = 0
    run_code_failures = 0
    last_action = ""
    thought_history: list[dict[str, Any]] = []

    def _emit(ev: dict):
        emit_event(run_id, ev)

    from agent.orchestrator import RunOrchestrator

    def on_decision(entry):
        _emit({"type": "decision", **entry})

    orch = RunOrchestrator(run_id, ctx, emit=_emit, on_decision=on_decision)

    append_decision(
        ctx,
        agent="react_loop",
        decision="react_run_start",
        target="run",
        reason=f"ReAct mode, max {MAX_REACT_ROUNDS} rounds",
    )

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
            chat_result = chat_messages(settings, history, phase="react")
        except Exception as e:
            loge("react", f"LLM call failed round {round_num}: {e}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                break
            history.append(
                {"role": "user", "content": f"[系统提示]\nLLM 调用失败: {e}\n请重试或输出 ACTION: done 结束。"}
            )
            continue

        # 2. Parse response
        parsed = parse_react_response(chat_result.get("content") or "")
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
                hint = (
                    "你已经连续多轮未输出有效 ACTION。如果认为任务已完成请输出 ACTION: done。"
                    "如果需要继续，请选择: solve_lab / run_code / screenshot / fill_report / render_uml / done。"
                )
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
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "[系统提示]\n"
                            "代码验证已尝试多次。请立即停止 fix_code/run_code，"
                            "调用 ACTION: finalize_report（一键 UML+截图+填表），"
                            "或依次 render_uml → screenshot → fill_report。"
                            "实验报告类作业必须产出 Word 文档，代码运行失败不能作为跳过填表的理由。"
                        ),
                    }
                )
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

    report = orch.run_verify(auto_remediate=bool(ctx.get("auto_remediate")))

    # If solve_lab never ran successfully, try fallback
    any_solve = (ctx.get("module_results") or {}).get("solve_lab", {}).get("ok")
    if not any_solve and use_fallback:
        try:
            from agent.fallback import fallback_to_solve

            fallback_to_solve(ctx)
        except Exception:
            pass

    # Collect final state
    fill_mr = (ctx.get("module_results") or {}).get("fill_report")
    final = {
        "run_id": run_id,
        "ok": bool(any_solve or report.get("passed", False)),
        "module_results": {
            k: {"ok": v.get("ok"), "data": v.get("data")}
            for k, v in (ctx.get("module_results") or {}).items()
        },
        "verification_report": report,
        "output_path": (fill_mr or {}).get("data", {}).get("output_path") if fill_mr else None,
        "thought_trace": thought_history,
        "decision_log": ctx.get("decision_log") or [],
    }
    release_run(run_id, "completed")
    # Clean up run temp
    from agent.document_store import clear_run_temp
    from agent.orchestrator import finalize_run_payload

    clear_run_temp(run_id)
    final = finalize_run_payload(orch, final)
    _emit({"type": "done", **final})
    logi("react", f"run_id={run_id} done ok={final.get('ok')}")
    return final


def _emit_progress_done_steps(ctx: dict, steps: list):
    """After the ReAct loop finishes, mark all plan steps as done in SSE."""
    results = ctx.get("module_results") or {}
    for step in steps:
        module = step.get("module") or ""
        if module and module in results:
            continue  # Already run by ReAct
    emit_event(
        ctx.get("run_id") or "",
        {"type": "progress", "module": "fill_report", "phase": "final", "status": "done"},
    )
