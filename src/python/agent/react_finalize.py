"""
ReAct post-loop finalize: run plan steps the agent never reached (UML / deliver / fill).

Thin wrapper around RunOrchestrator.run_finalize (V3-2).
"""

from __future__ import annotations

from typing import Any, Callable

from agent.orchestrator import RunOrchestrator, _module_done, _should_render_uml


def react_finalize_pipeline(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    max_rounds: int = 12,
    emit_fn: Callable[[dict], None] | None = None,
) -> list[dict[str, Any]]:
    """Run missing finalize steps. Returns list of cycle records for thought_trace append."""
    orch = RunOrchestrator(run_id, ctx, emit=lambda _e: None)
    return orch.run_finalize(steps, max_rounds=max_rounds, emit_fn=emit_fn)


def execute_finalize_report(ctx: dict, params: dict | None = None) -> dict[str, Any]:
    """Single-shot tool: render_uml → present_deliverable or fill_report (non-blocking)."""
    from modules.deliverable import is_content_only_output_mode

    output_mode = ctx.get("output_mode", "deliverable")
    if is_content_only_output_mode(output_mode):
        steps = [
            {"module": "render_uml"},
            {"module": "present_deliverable"},
        ]
    else:
        steps = [{"module": "render_uml"}, {"module": "fill_report"}]
    cycles = react_finalize_pipeline(ctx.get("run_id") or "tool", ctx, steps, max_rounds=0)
    fill_ok = _module_done(ctx, "fill_report") or _module_done(ctx, "present_deliverable")
    uml_n = len(
        (((ctx.get("module_results") or {}).get("render_uml") or {}).get("data") or {}).get("images_b64") or []
    )
    tail_label = "汇编答案" if is_content_only_output_mode(output_mode) else "填表"
    summary = f"finalize_report: UML {uml_n} 张, {tail_label}={'成功' if fill_ok else '未成功（不影响主流程）'}"
    if not fill_ok and not is_content_only_output_mode(output_mode):
        fill_err = ((ctx.get("module_results") or {}).get("fill_report") or {}).get("data") or {}
        err = fill_err.get("error", "")
        if err:
            summary += f" — {err}"
    solve_ok = _module_done(ctx, "solve_lab")
    out = {"ok": solve_ok or fill_ok, "result_summary": summary, "data": {"cycles": len(cycles)}, "module": "finalize_report"}
    ctx.setdefault("module_results", {})["finalize_report"] = {"ok": out["ok"], "data": out["data"]}
    return out


def _summarize_finalize(module: str, result: dict) -> str:
    from agent.react_tools import _format_result_summary

    return _format_result_summary(module, result)
