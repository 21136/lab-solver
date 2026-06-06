"""
ReAct tool schemas and execution wrappers (Phase R1).

Each tool wraps an existing _run_* function from agent.executor.
No logic duplication — just parameter parsing + execution + result formatting.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from agent.registry import react_action_to_module, react_tool_schemas
from agent.run_control import emit_event
from log_util import loge

# ── Tool registry (sourced from agent.registry) ────────────────

REACT_TOOL_SCHEMAS: dict[str, dict[str, Any]] = react_tool_schemas()


def build_tools_prompt() -> str:
    """Render tool descriptions for the ReAct system prompt."""
    lines: list[str] = []
    for name, schema in REACT_TOOL_SCHEMAS.items():
        params = schema.get("params") or []
        params_str = ", ".join(params) if params else "无"
        lines.append(
            f"[TOOL: {name}] {schema['description']} 参数: {params_str}"
        )
    return "\n".join(lines)


def tool_to_module(action: str) -> str:
    """Map a ReAct action name to an executor module id."""
    return react_action_to_module(action)


def execute_tool(ctx: dict, action: str, params: dict | None) -> dict[str, Any]:
    """Dispatch a ReAct action to the corresponding executor runner.

    Returns {ok: bool, result_summary: str, data: dict|None, module: str}
    """
    action = (action or "").strip().lower()
    module = tool_to_module(action)
    if not module:
        return {"ok": False, "result_summary": f"未知工具: {action}", "data": None, "module": action}

    from agent.executor import _MODULE_RUNNERS

    runner = _MODULE_RUNNERS.get(module)
    if not runner and module != "finalize_report":
        return {"ok": False, "result_summary": f"工具未实现: {action}", "data": None, "module": module}

    try:
        # answer_only mode: fill_report is a no-op
        from modules.deliverable import is_content_only_output_mode

        if module == "fill_report" and is_content_only_output_mode(
            ctx.get("output_mode", "deliverable")
        ):
            ctx.setdefault("module_results", {})[module] = {
                "ok": True, "data": {"success": True, "mode": "answer_only"}
            }
            return {
                "ok": True,
                "result_summary": "answer_only 模式：跳过填表，答案已在界面展示",
                "data": {"mode": "answer_only"},
                "module": module,
            }

        p = dict(params or {}) if isinstance(params, dict) else {}
        # Inject default language from profile if not specified
        if module == "solve_lab" and "language" not in p:
            profile_lang = (ctx.get("user_profile") or {}).get("default_language", "")
            p["language"] = profile_lang or "python"

        if module == "finalize_report":
            from agent.react_finalize import execute_finalize_report
            return execute_finalize_report(ctx, p)

        orch = ctx.get("_orchestrator")
        if orch is not None:
            result = orch.run_module(
                module,
                p,
                emit_running=False,
                decision_agent="react_loop",
            )
        else:
            result = runner(ctx, p)
            ctx.setdefault("module_results", {})[module] = result
        ok = bool(result.get("ok"))

        # V5-4: fill_report failure is experimental — do not count as tool failure.
        if module == "fill_report" and not ok:
            err = (result.get("data") or {}).get("error", "未知错误")
            return {
                "ok": True,
                "result_summary": f"填表未成功（不影响答案工作区）: {err[:300]}",
                "data": result.get("data"),
                "module": module,
            }

        # run_code degraded → ReAct sees failure, but result stays in ctx for fill_report
        degraded = False
        if module == "run_code" and ok:
            data = result.get("data") or {}
            if data.get("degraded"):
                degraded = True
                ok = False
            elif not str(data.get("output") or "").strip() and not data.get("is_error"):
                degraded = True
                ok = False
                result["data"] = {
                    **data,
                    "degraded_reason": "程序运行成功但无任何输出，可能缺少依赖或逻辑未执行",
                }

        summary = _format_result_summary(module, result, degraded=degraded)
        return {"ok": ok, "result_summary": summary, "data": result.get("data"), "module": module}
    except Exception as e:
        loge("react", f"工具 {action} 执行异常: {e}\n{traceback.format_exc()}")
        return {"ok": False, "result_summary": f"工具执行异常: {e}", "data": None, "module": module}


def _format_result_summary(module: str, result: dict, *, degraded: bool = False) -> str:
    """Build a human-readable summary from a ModuleResult."""
    data = result.get("data") or {}
    ok = result.get("ok", False)

    if module == "run_code" and degraded:
        reason = data.get("degraded_reason", "") or ""
        category = data.get("error_category", "")
        return (
            f"代码执行失败({category}): 代码经过编译/运行仍无法通过，已降级。"
            f"请在 THOUGHT 中分析失败原因，然后用 fix_code 工具修复代码。"
            f"错误详情: {reason[:300]}"
        )

    if module == "solve_lab":
        if ok:
            parsed = data.get("parsed") or {}
            code = parsed.get("code") or data.get("code") or ""
            code_files = parsed.get("code_files") or data.get("code_files") or []
            lang = data.get("language") or "?"
            has_uml = bool(parsed.get("diagrams"))
            extra = f"，{len(code_files)} 个文件" if len(code_files) > 1 else ""
            uml_hint = " + UML图" if has_uml else ""
            return (
                f"解题成功。语言: {lang}，代码 {len(code)} 字符{extra}{uml_hint}。"
                f"步骤分析: {(parsed.get('steps_analysis') or '')[:80]}..."
            )
        return f"解题失败: {data.get('error', '未知错误')}"

    if module == "run_code":
        # Internal auto-fix succeeded (executor._fix_and_retry returned fix_code result)
        if data.get("fixed"):
            return f"代码经自动修复后运行成功（{data.get('retries', 0)} 次重试）。可继续 present_deliverable 或 finalize_report。"
        output = data.get("output") or ""
        is_error = data.get("is_error") or data.get("error") or False
        if is_error:
            return f"代码执行失败: {output[:300]}。请在 THOUGHT 中分析错误原因，用 fix_code 修复。"
        if not str(output).strip():
            reason = data.get("degraded_reason") or "无任何终端输出"
            return (
                f"代码编译通过但无输出: {reason}。"
                "请用 fix_code 修复（检查依赖/classpath/主函数逻辑），不要重复相同修复。"
            )
        return f"代码执行成功。输出: {output[:300]}"

    if module == "fix_code":
        if ok:
            lang = data.get("language") or "?"
            return f"代码修复成功。语言: {lang}，请调用 run_code 验证修复结果。"
        return f"代码修复失败: {data.get('error', '未知错误')}"

    if module == "fill_report":
        if ok:
            if data.get("mode") == "answer_only":
                return "answer_only 模式：跳过填表，答案已在界面展示"
            return f"报告填充完成，已保存至: {data.get('output_path', '?')}"
        return f"报告填充失败: {data.get('error', '未知错误')}"

    if module == "present_deliverable":
        if ok:
            dlv_id = data.get("deliverable_id") or "?"
            return f"答案交付物已汇编，可在答案工作区查看（id: {dlv_id}）"
        return f"交付物汇编失败: {data.get('error', '未知错误')}"

    if module == "render_uml":
        if ok:
            from modules.uml import format_render_summary
            summary = data.get("summary") or format_render_summary(data)
            validation = data.get("validation") or {}
            if validation and not validation.get("ok"):
                issues = validation.get("issues") or []
                hint = "; ".join(
                    (i.get("message") or str(i))[:80] for i in issues[:2]
                )
                return f"{summary}（验错未通过: {hint}；可 fix_diagrams）"
            return summary
        val = data.get("validation") or {}
        issues = val.get("issues") or []
        if issues:
            return "图表渲染/验错失败: " + "; ".join(
                (i.get("message") or str(i))[:100] for i in issues[:3]
            )
        return f"图表渲染失败: {data.get('error', data.get('summary', '未知错误'))}"

    if module == "fix_diagrams":
        if ok:
            n = len((data.get("diagrams") or []))
            return f"已修复 diagrams（共 {n} 项），请再次 render_uml"
        return f"图表修复失败: {data.get('error', '未知错误')}"

    if ok:
        return f"工具 {module} 执行成功"
    return f"工具 {module} 执行失败: {data.get('error', '未知错误')}"


def emit_react_thinking(run_id: str, round_num: int):
    """Emit a 'react_thinking' SSE event before the LLM call."""
    emit_event(run_id, {"type": "react_thinking", "round": round_num})


def emit_react_cycle(
    run_id: str,
    round_num: int,
    max_rounds: int,
    thought: str,
    action: str,
    result_ok: bool,
    result_summary: str,
):
    """Emit a 'react_cycle' SSE event after each tool execution."""
    emit_event(
        run_id,
        {
            "type": "react_cycle",
            "round": round_num,
            "max_rounds": max_rounds,
            "thought": (thought or "")[:8000],
            "action": action,
            "result_ok": result_ok,
            "result_summary": (result_summary or "")[:2000],
        },
    )
