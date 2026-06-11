"""
Standard-mode agent executor (Phase 2a.1).

Facade: module registry, run orchestration entry, and async run control.
Implementation runners live in executor_solve / executor_code / executor_deliver.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.decision_log import append_decision
from agent.document_store import clear_run_temp  # noqa: F401 — test patch target
from agent.executor_code import _run_fix_code, _run_run_code
from agent.executor_common import (
    _fail_result,
    _ok_result,
    module_failure_blocks_pipeline,
    progress_payload_for_module_result,
)
from agent.executor_deliver import (
    _run_fill_report,
    _run_fix_diagrams,
    _run_present_deliverable,
    _run_render_uml,
    _run_revise_answer,
)
from agent.executor_solve import (
    _run_solve_code_cloze,
    _run_solve_lab,
    _run_solve_short_answer,
    _run_solve_theory,
)
from agent.run_control import emit_event, map_api_error, release_run
from agent.types import ModuleResult, PlanStep
from log_util import loge

_MODULE_RUNNERS = {
    "solve_lab": _run_solve_lab,
    "solve_code_cloze": _run_solve_code_cloze,
    "solve_theory": _run_solve_theory,
    "solve_short_answer": _run_solve_short_answer,
    "run_code": _run_run_code,
    "fix_code": _run_fix_code,
    "render_uml": _run_render_uml,
    "fix_diagrams": _run_fix_diagrams,
    "revise_answer": _run_revise_answer,
    "fill_report": _run_fill_report,
    "present_deliverable": _run_present_deliverable,
}


def run_module(ctx: dict, step: PlanStep) -> ModuleResult:
    module = step.get("module") or ""
    params = step.get("params") or {}
    runner = _MODULE_RUNNERS.get(module)
    if not runner:
        return _fail_result(module, f"未知模块: {module}", params)
    return runner(ctx, params)


def _standard_run_ok(ctx: dict) -> bool:
    """Core solve success for standard mode done.ok (RL3 / RL7)."""
    from agent.run_result import compute_run_ok

    return compute_run_ok(ctx)


def execute_standard_run(
    run_id: str,
    ctx: dict,
    steps: list[PlanStep],
    *,
    use_fallback: bool = True,
) -> dict[str, Any]:
    """Execute confirmed steps; emit SSE via run_control."""
    return _execute_standard_via_orchestrator(
        run_id, ctx, steps, use_fallback=use_fallback
    )


def _execute_standard_via_orchestrator(
    run_id: str,
    ctx: dict,
    steps: list[PlanStep],
    *,
    use_fallback: bool = True,
) -> dict[str, Any]:
    from agent.orchestrator import RunOrchestrator, RunStepsOptions

    emit = lambda ev: emit_event(run_id, ev)
    ctx["run_id"] = run_id

    def on_decision(entry):
        emit({"type": "decision", **entry})

    append_decision(
        ctx,
        agent="executor",
        decision="run_start",
        target="run",
        reason=f"{len(steps)} steps",
        emit=on_decision,
    )

    orch = RunOrchestrator(run_id, ctx, emit=emit, on_decision=on_decision)
    completed, cancelled = orch.run_steps(steps, options=RunStepsOptions())
    if cancelled:
        release_run(run_id, "cancelled")
        return {"cancelled": True, "run_id": run_id}

    from agent.run_result import complete_agent_run

    return complete_agent_run(
        run_id,
        ctx,
        orch,
        emit=emit,
        use_fallback=use_fallback,
        fallback_fatal=True,
        agent_log_tag="executor",
    )


def _save_agent_insights(ctx: dict) -> None:
    """Scan module_results for LLM notes and append to AI_INSIGHTS.md."""
    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    notes = ((solve_mr.get("data") or {}).get("parsed") or {}).get("notes", "").strip()
    if not notes:
        return
    try:
        from log_util import logi

        insights_path = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "AI_INSIGHTS.md"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = f"\n## {today}\n\n### 自动记录（来自 AI 解题 notes — Agent 模式）\n\n{notes}\n"
        with open(insights_path, "a", encoding="utf-8") as f:
            f.write(entry)
        logi("insight", f"已保存 {len(notes)} 字 LLM 自述到 AI_INSIGHTS.md (Agent)")
    except Exception:
        pass


def start_run_async(
    run_id: str,
    ctx: dict,
    steps: list[PlanStep],
    *,
    use_fallback: bool = True,
    run_mode: str = "standard",
) -> threading.Thread:
    def _target():
        try:
            from llm_client import reset_llm_call_count

            reset_llm_call_count()
            mode = (run_mode or ctx.get("run_mode") or "standard").lower()
            if mode == "deep":
                from agent.deep_pipeline import execute_deep_run

                execute_deep_run(run_id, ctx, steps, use_fallback=use_fallback)
            elif mode == "react":
                from agent.react_loop import run_react_loop

                run_react_loop(run_id, ctx, steps, use_fallback=use_fallback)
            else:
                execute_standard_run(run_id, ctx, steps, use_fallback=use_fallback)
            _save_agent_insights(ctx)
        except Exception as e:
            loge("executor", str(e))
            mapped = map_api_error(e)
            emit_event(run_id, {"type": "error", **mapped})
            release_run(run_id, "error")
            emit_event(run_id, {"type": "done", "ok": False, "error": mapped["error"]})

    short_id = (run_id or "unknown")[:8]
    t = threading.Thread(target=_target, daemon=True, name=f"agent-run-{short_id}")
    t.start()
    return t


def retry_single_step(run_id: str, ctx: dict, module_id: str) -> None:
    """Re-run one module from confirmed steps."""
    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    target = next((s for s in steps if s.get("module") == module_id), None)
    if not target:
        raise ValueError(f"计划中无模块: {module_id}")

    from agent.run_control import set_retry_module

    set_retry_module(run_id, module_id)
    emit = lambda ev: emit_event(run_id, ev)

    def on_decision(entry):
        emit({"type": "decision", **entry})

    dirty = list(ctx.get("dirty_modules") or [])
    if module_id not in dirty:
        dirty.append(module_id)
    ctx["dirty_modules"] = dirty

    append_decision(
        ctx,
        agent="executor",
        decision="retry_step",
        target=module_id,
        reason="用户请求重试",
        emit=on_decision,
    )
    result = run_module(ctx, target)
    ctx.setdefault("module_results", {})[module_id] = result
    emit(
        {
            "type": "progress",
            "module": module_id,
            "status": "done" if result.get("ok") else "failed",
            "error": (result.get("data") or {}).get("error"),
        }
    )
