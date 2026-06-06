"""
ReAct post-loop finalize: run plan steps the agent never reached (UML / screenshot / fill).

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
    """Single-shot tool: render_uml → screenshot → fill_report."""
    steps = [{"module": "render_uml"}, {"module": "screenshot_ide"}, {"module": "fill_report"}]
    cycles = react_finalize_pipeline(ctx.get("run_id") or "tool", ctx, steps, max_rounds=0)
    fill_ok = _module_done(ctx, "fill_report")
    uml_n = len(
        (((ctx.get("module_results") or {}).get("render_uml") or {}).get("data") or {}).get("images_b64") or []
    )
    shot_n = 0
    for mod in ("screenshot_ide", "screenshot_terminal"):
        if _module_done(ctx, mod):
            shot_n = len(((ctx.get("module_results") or {}).get(mod) or {}).get("data", {}).get("images_b64") or [])
            break
    summary = f"finalize_report: UML {uml_n} 张, 截图 {shot_n} 张, 填表={'成功' if fill_ok else '失败'}"
    if not fill_ok:
        fill_err = ((ctx.get("module_results") or {}).get("fill_report") or {}).get("data") or {}
        err = fill_err.get("error", "")
        if err:
            summary += f" — {err}"
    out = {"ok": fill_ok, "result_summary": summary, "data": {"cycles": len(cycles)}, "module": "finalize_report"}
    ctx.setdefault("module_results", {})["finalize_report"] = {"ok": fill_ok, "data": out["data"]}
    return out


def _summarize_finalize(module: str, result: dict) -> str:
    from agent.react_tools import _format_result_summary

    return _format_result_summary(module, result)
