"""Shared run outcome semantics and completion tail (RL3 / RL7 / RL12)."""

from __future__ import annotations

from typing import Any, Callable


def compute_run_ok(ctx: dict) -> bool:
    """True when solve_lab or solve_theory produced a usable result.

    Verification / fill_report failures do not veto run success.
    """
    mr = ctx.get("module_results") or {}
    return any(
        mr.get(m, {}).get("ok")
        for m in ("solve_lab", "solve_code_cloze", "solve_short_answer", "solve_theory")
    )


def unresolved_checks_from_verification(verification: dict | None) -> list[dict]:
    """Failed verify checks for run_summary / UI when verify did not pass."""
    if not verification or verification.get("passed"):
        return []
    return [
        {"id": c.get("id", ""), "message": c.get("message", "")}
        for c in (verification.get("checks") or [])
        if not c.get("ok")
    ]


def quality_status_from_verification(verification: dict | None) -> str:
    """Product-facing quality state orthogonal to solve-only ``compute_run_ok``."""
    if not verification:
        return "unknown"
    return "passed" if verification.get("passed") else "needs_review"


def slim_module_results(ctx: dict) -> dict:
    return {
        k: {"ok": v.get("ok"), "data": v.get("data")}
        for k, v in (ctx.get("module_results") or {}).items()
    }


def build_run_done_payload(
    ctx: dict,
    run_id: str,
    *,
    verification_report: dict | None = None,
    extra: dict | None = None,
) -> dict:
    fill_mr = (ctx.get("module_results") or {}).get("fill_report")
    present_mr = (ctx.get("module_results") or {}).get("present_deliverable")
    deliverable = ctx.get("deliverable") or (present_mr or {}).get("data", {}).get("deliverable")
    verification = verification_report or ctx.get("verification_report") or {}
    final: dict[str, Any] = {
        "run_id": run_id,
        "ok": compute_run_ok(ctx),
        "module_results": slim_module_results(ctx),
        "verification_report": verification,
        "quality_status": quality_status_from_verification(verification),
        "output_path": (fill_mr or {}).get("data", {}).get("output_path") if fill_mr else None,
    }
    if deliverable is not None:
        final["deliverable"] = deliverable
    if ctx.get("decision_log") is not None:
        final["decision_log"] = ctx.get("decision_log")
    if extra:
        final.update(extra)
    return final


def maybe_fallback_solve(
    ctx: dict,
    *,
    use_fallback: bool = True,
    emit: Callable[[dict], None] | None = None,
    fatal: bool = False,
) -> tuple[bool, Exception | None]:
    """Try fallback_to_solve when no solve module succeeded."""
    if not use_fallback or compute_run_ok(ctx):
        return False, None
    from agent.cloze_run import is_code_cloze_run, is_mixed_assignment_run

    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    if is_mixed_assignment_run(ctx, steps) or is_code_cloze_run(ctx, steps):
        return False, None
    try:
        from agent.fallback import fallback_to_solve

        on_decision = (lambda entry: emit({"type": "decision", **entry})) if emit else None
        fallback_to_solve(ctx, emit=on_decision)
        return True, None
    except Exception as e:
        if fatal:
            return False, e
        return False, None


def complete_agent_run(
    run_id: str,
    ctx: dict,
    orch: Any,
    *,
    emit: Callable[[dict], None],
    use_fallback: bool = True,
    fallback_fatal: bool = False,
    auto_remediate: bool | None = None,
    extra_final: dict | None = None,
    agent_log_tag: str = "agent",
) -> dict:
    """Shared run tail: fallback → verify → payload → finalize → cleanup → done SSE."""
    from agent.document_store import clear_run_temp
    from agent.orchestrator import finalize_run_payload
    from agent.run_control import map_api_error, release_run
    from log_util import logi

    fallback_ran, fallback_err = maybe_fallback_solve(
        ctx,
        use_fallback=use_fallback,
        emit=emit,
        fatal=fallback_fatal,
    )
    if fallback_err is not None:
        mapped = map_api_error(fallback_err)
        emit({"type": "error", **mapped})
        release_run(run_id, "error")
        clear_run_temp(run_id)
        final = build_run_done_payload(ctx, run_id, extra={"ok": False})
        emit({"type": "done", "ok": False, **final})
        return final

    do_remediate = auto_remediate if auto_remediate is not None else bool(ctx.get("auto_remediate"))
    verification = orch.run_verify(auto_remediate=do_remediate)

    extra = dict(extra_final or {})
    if fallback_ran:
        extra["fallback"] = True

    final = build_run_done_payload(ctx, run_id, verification_report=verification, extra=extra)
    final = finalize_run_payload(orch, final)

    release_run(run_id, "completed")
    clear_run_temp(run_id)
    emit({"type": "done", **final})
    logi(agent_log_tag, f"run_id={run_id} done ok={final.get('ok')}")
    return final

