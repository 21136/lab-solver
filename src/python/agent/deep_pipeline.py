"""
DeepPipeline: understand+plan → draft → preflight → reflect → revise → execute → verify.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from agent.decision_log import append_decision
from agent.quality import verify_answer
from agent.reflect import run_reflect
from agent.run_control import emit_event, is_cancelled, map_api_error, release_run
from agent.types import ModuleResult
from log_util import loge, logi
from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
from modules.preflight import run_preflight
from modules.revise_answer import revise_answer

MAX_REFLECT_ROUNDS = 2
MAX_FIX_CODE_ROUNDS = 2


def _emit_thought(emit: Optional[Callable], phase: str, text: str, extra: dict | None = None):
    if not emit or not text:
        return
    payload = {"type": "thought", "phase": phase, "text": text[:4000]}
    if extra:
        payload.update(extra)
    emit(payload)


def _run_draft(ctx: dict, params: dict) -> ModuleResult:
    from agent.executor import _run_solve_lab

    return _run_solve_lab(ctx, params)


def _issues_to_scope(issues: list) -> list[str]:
    scope = []
    field_map = {
        "steps_analysis": "steps",
        "result_description": "result",
        "expected_output": "result",
        "summary": "summary",
        "code": "code",
    }
    for item in issues:
        field = (item.get("field") or item.get("target") or "").strip()
        scope.append(field_map.get(field, field or "full"))
    return list(dict.fromkeys(scope)) or ["full"]


def execute_deep_run(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    use_fallback: bool = True,
) -> dict[str, Any]:
    """
    Deep pipeline with verify before final done event.
    Reimplements tail by inlining execute after pre-reflect phases.
    """
    from agent.document_store import clear_run_temp
    from agent.executor import run_module
    from agent.planner import MAX_CONSECUTIVE_FAILURES, replan_incremental

    emit = lambda ev: emit_event(run_id, ev)
    ctx["run_id"] = run_id
    understand = ctx.get("understand") or {}
    prev_issue_fp: Optional[str] = None
    reflect_round = 0
    completed_modules: list[str] = []

    def on_decision(entry):
        emit({"type": "decision", **entry})

    append_decision(
        ctx,
        agent="deep_pipeline",
        decision="deep_run_start",
        target="run",
        reason=f"{len(steps)} steps",
        emit=on_decision,
    )

    if understand.get("summary"):
        _emit_thought(emit, "understand", str(understand.get("summary", ""))[:2000])

    solve_step = next(
        (s for s in steps if s.get("module") == "solve_lab"),
        {"module": "solve_lab", "params": {}, "default_checked": True},
    )
    if solve_step.get("default_checked", True):
        emit({"type": "progress", "module": "solve_lab", "phase": "draft", "status": "running"})
        draft_result = _run_draft(ctx, solve_step.get("params") or {})
        ctx.setdefault("module_results", {})["solve_lab"] = draft_result
        if draft_result.get("ok"):
            completed_modules.append("solve_lab")
            emit({"type": "progress", "module": "solve_lab", "phase": "draft", "status": "done"})
            solve_data = draft_result.get("data") or {}
            include_uml = bool((solve_step.get("params") or {}).get("include_uml"))

            fix_round = 0
            while fix_round <= MAX_FIX_CODE_ROUNDS:
                if is_cancelled(run_id):
                    release_run(run_id, "cancelled")
                    emit({"type": "done", "ok": False, "cancelled": True})
                    return {"cancelled": True}

                pf = run_preflight(solve_data, include_uml=include_uml)
                # Pick out the exec pattern check for frontend warning dialogs
                exec_check = next((c for c in pf.get("checks", []) if c.get("id") == "exec_pattern"), {})
                emit({
                    "type": "preflight",
                    "ok": pf["ok"],
                    "checks": pf.get("checks", []),
                    "exec_pattern": exec_check.get("pattern"),
                    "exec_ok": exec_check.get("ok"),
                    "exec_message": exec_check.get("message"),
                })
                if pf["ok"]:
                    break
                code_failed = "code_syntax" in pf.get("failed_ids", [])
                if not code_failed or fix_round >= MAX_FIX_CODE_ROUNDS:
                    break
                fix_round += 1
                err_msg = "; ".join(
                    c.get("message", "") for c in pf.get("checks", []) if not c.get("ok")
                )
                try:
                    fix = fix_code_from_error(
                        ctx["settings"],
                        code=solve_data.get("code") or "",
                        code_files=solve_data.get("code_files") or None,
                        main_file=solve_data.get("main_file") or "",
                        language=solve_data.get("language") or "java",
                        error_output=err_msg,
                        report_excerpt=ctx.get("planner_input_text") or ctx.get("report_text") or "",
                    )
                    solve_data = apply_fix_to_solve_data(solve_data, fix)
                    ctx["module_results"]["solve_lab"]["data"] = solve_data
                except Exception:
                    break

            parsed = solve_data.get("parsed") or {}
            while reflect_round < MAX_REFLECT_ROUNDS:
                if is_cancelled(run_id):
                    release_run(run_id, "cancelled")
                    emit({"type": "done", "ok": False, "cancelled": True})
                    return {"cancelled": True}
                reflect_round += 1
                reflect_out = run_reflect(
                    ctx,
                    understand=understand,
                    draft_parsed=parsed,
                )
                issues = reflect_out.get("issues") or []
                emit(
                    {
                        "type": "reflect",
                        "pass": reflect_out.get("pass"),
                        "issues": issues,
                        "round": reflect_round,
                    }
                )
                if reflect_out.get("pass") or not issues or reflect_out.get("skipped"):
                    break
                fp = reflect_out.get("issues_fingerprint") or ""
                if fp and fp == prev_issue_fp:
                    break
                prev_issue_fp = fp
                try:
                    rev = revise_answer(
                        ctx["settings"],
                        parsed=parsed,
                        report_excerpt=ctx.get("planner_input_text") or ctx.get("report_text") or "",
                        scope=_issues_to_scope(issues),
                        feedback="; ".join(i.get("message", "") for i in issues[:5]),
                    )
                    parsed = rev.get("parsed") or parsed
                    solve_data["parsed"] = parsed
                    solve_data["code"] = parsed.get("code") or solve_data.get("code")
                    if parsed.get("code_files"):
                        solve_data["code_files"] = parsed["code_files"]
                    if parsed.get("main_file"):
                        solve_data["main_file"] = parsed["main_file"]
                    ctx["module_results"]["solve_lab"]["data"] = solve_data
                    if not rev.get("changed_fields"):
                        break
                except Exception:
                    break
        else:
            emit(
                {
                    "type": "progress",
                    "module": "solve_lab",
                    "status": "failed",
                    "error": (draft_result.get("data") or {}).get("error"),
                }
            )

    # Execute tail modules (shared with standard via RunOrchestrator when enabled)
    from agent.orchestrator import RunOrchestrator, RunStepsOptions, orchestrator_enabled

    orch: RunOrchestrator | None = None
    if orchestrator_enabled(ctx):
        orch = RunOrchestrator(run_id, ctx, emit=emit, on_decision=on_decision)
        tail_opts = RunStepsOptions(
            exclude_modules=frozenset({"solve_lab", "fix_code"}),
            emit_skipped=False,
            enable_reuse=False,
            enable_retry_filter=False,
            emit_plan_updated=False,
            replan_restart_index=False,
            note_completion=False,
            set_last_error_on_fail=False,
            run_code_error_meta=False,
            log_step_decisions=False,
            initial_completed=list(completed_modules),
        )
        completed_modules, cancelled = orch.run_steps(steps, options=tail_opts)
        if cancelled:
            release_run(run_id, "cancelled")
            emit({"type": "done", "ok": False, "cancelled": True})
            return {"cancelled": True}
    else:
        i = 0
        exec_steps = [s for s in steps if s.get("module") != "solve_lab"]
        while i < len(exec_steps):
            if is_cancelled(run_id):
                release_run(run_id, "cancelled")
                emit({"type": "done", "ok": False, "cancelled": True})
                return {"cancelled": True}

            step = exec_steps[i]
            module = step.get("module") or ""
            if not step.get("default_checked", True):
                i += 1
                continue
            if module in completed_modules:
                i += 1
                continue
            if module == "fix_code":
                i += 1
                continue

            emit({"type": "progress", "module": module, "index": i, "status": "running"})
            try:
                result = run_module(ctx, step)
            except Exception as e:
                mapped = map_api_error(e)
                from agent.executor import _fail_result

                result = _fail_result(module, mapped["error"], step.get("params"))
            ctx.setdefault("module_results", {})[module] = result
            if result.get("ok"):
                completed_modules.append(module)
                ctx["consecutive_failures"] = 0
                emit({"type": "progress", "module": module, "index": i, "status": "done"})
            else:
                ctx["consecutive_failures"] = int(ctx.get("consecutive_failures") or 0) + 1
                emit(
                    {
                        "type": "progress",
                        "module": module,
                        "index": i,
                        "status": "failed",
                        "error": (result.get("data") or {}).get("error"),
                    }
                )
                if ctx["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                    new_plan = replan_incremental(
                        ctx,
                        {
                            "failed_module": module,
                            "error_summary": (result.get("data") or {}).get("error", ""),
                            "completed_modules": completed_modules,
                        },
                        emit=on_decision,
                    )
                    exec_steps = [
                        s
                        for s in (new_plan.get("steps") or exec_steps)
                        if s.get("module") != "solve_lab"
                    ]
                    ctx["consecutive_failures"] = 0
            i += 1

    any_solve = (ctx.get("module_results") or {}).get("solve_lab", {}).get("ok")
    if not any_solve and use_fallback:
        try:
            from agent.fallback import fallback_to_solve

            fallback_to_solve(ctx, emit=on_decision)
        except Exception:
            pass

    report = (
        orch.run_verify(auto_remediate=bool(ctx.get("auto_remediate")))
        if orch is not None
        else verify_answer(ctx)
    )
    if orch is None:
        ctx["verification_report"] = report
        emit({"type": "verification", **report})

    fill_mr = (ctx.get("module_results") or {}).get("fill_report")
    final = {
        "run_id": run_id,
        "ok": report.get("passed", True) and any(
            (ctx.get("module_results") or {}).get(m, {}).get("ok")
            for m in ("solve_lab", "solve_theory")
        ),
        "module_results": {
            k: {"ok": v.get("ok"), "data": v.get("data")}
            for k, v in (ctx.get("module_results") or {}).items()
        },
        "verification_report": report,
        "output_path": (fill_mr or {}).get("data", {}).get("output_path") if fill_mr else None,
    }
    if orch is None:
        from agent.orchestrator import RunOrchestrator, finalize_run_payload

        orch = RunOrchestrator(run_id, ctx, emit=emit, on_decision=on_decision)
    else:
        from agent.orchestrator import finalize_run_payload

    final = finalize_run_payload(orch, final)
    release_run(run_id, "completed")
    clear_run_temp(run_id)
    emit({"type": "done", **final})
    logi("deep_pipeline", f"run_id={run_id} done ok={final.get('ok')}")
    return final


def run_deep_pipeline(
    ctx: dict,
    *,
    emit: Optional[Callable[[dict], None]] = None,
) -> dict[str, Any]:
    """Sync entry for tests."""
    run_id = ctx.get("run_id") or "test"
    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    if emit:
        import agent.run_control as rc

        _orig = rc.emit_event

        def _patch(rid, ev):
            emit(ev)

        rc.emit_event = _patch
        try:
            return execute_deep_run(run_id, ctx, steps, use_fallback=False)
        finally:
            rc.emit_event = _orig
    return execute_deep_run(run_id, ctx, steps, use_fallback=False)


def start_deep_run_async(
    run_id: str,
    ctx: dict,
    steps: list,
    *,
    use_fallback: bool = True,
) -> threading.Thread:
    def _target():
        try:
            execute_deep_run(run_id, ctx, steps, use_fallback=use_fallback)
        except Exception as e:
            loge("deep_pipeline", str(e))
            mapped = map_api_error(e)
            emit_event(run_id, {"type": "error", **mapped})
            release_run(run_id, "error")
            emit_event(run_id, {"type": "done", "ok": False, "error": mapped["error"]})

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t
