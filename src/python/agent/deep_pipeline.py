"""
DeepPipeline: understand+plan → draft → preflight → reflect → revise → execute → verify.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from agent.cloze_run import is_code_cloze_run, is_mixed_assignment_run
from agent.decision_log import append_decision
from agent.reflect import run_reflect
from agent.run_control import emit_event, is_cancelled, map_api_error, release_run
from agent.types import ModuleResult
from log_util import loge
from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
from modules.preflight import run_preflight
from modules.revise_answer import revise_answer
from modules.solve_pipeline import should_use_pipeline

MAX_REFLECT_ROUNDS = 2
MAX_FIX_CODE_ROUNDS = 2
_TEXT_ONLY_FIELDS = frozenset(
    {"steps_analysis", "result_description", "expected_output", "summary", "notes"}
)


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


def _pipeline_code_status(solve_data: dict, ctx: dict) -> tuple[str, str]:
    """Return (pipeline_version, code_status). v1 when legacy single-shot path."""
    session = solve_data.get("solve_session") or ctx.get("solve_session") or {}
    meta = solve_data.get("pipeline_meta") or ctx.get("pipeline_meta") or {}
    version = (meta.get("version") or session.get("pipeline_version") or "").lower()
    if not version:
        version = "v4" if should_use_pipeline(ctx.get("settings")) else "v1"
    status = (session.get("code_status") or meta.get("code_status") or "").lower()
    return version, status


def _issues_to_scope(issues: list, *, text_only: bool = False) -> list[str]:
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
    scope = list(dict.fromkeys(scope))
    if text_only:
        scope = [s for s in scope if s != "code"]
        if not scope or scope == ["full"]:
            scope = ["steps", "result", "summary"]
    return scope or (["steps", "result", "summary"] if text_only else ["full"])


def _apply_revise_to_solve_data(
    solve_data: dict,
    parsed: dict,
    rev: dict,
    *,
    text_only: bool,
) -> dict:
    """Merge revise output; V4 paths must not overwrite verified code."""
    solve_data = dict(solve_data)
    parsed = dict(parsed)
    solve_data["parsed"] = parsed
    if text_only:
        for field in _TEXT_ONLY_FIELDS:
            if field in parsed:
                solve_data["parsed"][field] = parsed[field]
        return solve_data
    solve_data["code"] = parsed.get("code") or solve_data.get("code")
    if parsed.get("code_files"):
        solve_data["code_files"] = parsed["code_files"]
    if parsed.get("main_file"):
        solve_data["main_file"] = parsed["main_file"]
    return solve_data


def _run_preflight_fix_loop(
    ctx: dict,
    solve_data: dict,
    *,
    include_uml: bool,
    emit: Callable,
    run_id: str,
) -> dict:
    """v1 legacy preflight → fix_code loop; skipped when V4 already validated in solve_lab."""
    version, code_status = _pipeline_code_status(solve_data, ctx)
    if version == "v4":
        append_decision(
            ctx,
            agent="deep_pipeline",
            decision="skip_preflight_fix",
            target="solve_lab",
            reason=f"v4 code_status={code_status or 'pending'}",
            emit=lambda e: emit({"type": "decision", **e}),
        )
        return solve_data

    fix_round = 0
    while fix_round <= MAX_FIX_CODE_ROUNDS:
        if is_cancelled(run_id):
            return solve_data

        pf = run_preflight(solve_data, include_uml=include_uml)
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
    return solve_data


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

    mixed_assignment = is_mixed_assignment_run(ctx, steps)
    code_cloze = is_code_cloze_run(ctx, steps)
    summary = str(understand.get("summary") or "").strip()
    if summary and not understand.get("cloze_fast_path"):
        if not (understand.get("degraded") and (code_cloze or mixed_assignment)):
            _emit_thought(emit, "understand", summary[:2000])
    solve_step = next((s for s in steps if s.get("module") == "solve_lab"), None)
    if solve_step is None and not code_cloze and not mixed_assignment:
        solve_step = {"module": "solve_lab", "params": {}, "default_checked": True}
    if mixed_assignment or code_cloze:
        append_decision(
            ctx,
            agent="deep_pipeline",
            decision="skip_solve_lab_draft",
            target="solve_code_cloze",
            reason="code_cloze/mixed plan: no solve_lab draft/reflect",
            emit=on_decision,
        )
    elif solve_step and solve_step.get("default_checked", True):
        emit({"type": "progress", "module": "solve_lab", "phase": "draft", "status": "running"})
        draft_result = _run_draft(ctx, solve_step.get("params") or {})
        ctx.setdefault("module_results", {})["solve_lab"] = draft_result
        if draft_result.get("ok"):
            completed_modules.append("solve_lab")
            emit({"type": "progress", "module": "solve_lab", "phase": "draft", "status": "done"})
            solve_data = draft_result.get("data") or {}
            include_uml = bool((solve_step.get("params") or {}).get("include_uml"))
            pipeline_version, _code_status = _pipeline_code_status(solve_data, ctx)
            text_only_revise = pipeline_version == "v4"

            solve_data = _run_preflight_fix_loop(
                ctx,
                solve_data,
                include_uml=include_uml,
                emit=emit,
                run_id=run_id,
            )
            if is_cancelled(run_id):
                return {"cancelled": True}

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
                        scope=_issues_to_scope(issues, text_only=text_only_revise),
                        feedback="; ".join(i.get("message", "") for i in issues[:5]),
                    )
                    parsed = rev.get("parsed") or parsed
                    solve_data = _apply_revise_to_solve_data(
                        solve_data,
                        parsed,
                        rev,
                        text_only=text_only_revise,
                    )
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

    from agent.orchestrator import RunOrchestrator, RunStepsOptions
    from agent.run_result import complete_agent_run

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
    _completed, cancelled = orch.run_steps(steps, options=tail_opts)
    if cancelled:
        release_run(run_id, "cancelled")
        emit({"type": "done", "ok": False, "cancelled": True})
        return {"cancelled": True}

    return complete_agent_run(
        run_id,
        ctx,
        orch,
        emit=emit,
        use_fallback=use_fallback,
        agent_log_tag="deep_pipeline",
    )


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

    short_id = (run_id or "unknown")[:8]
    t = threading.Thread(target=_target, daemon=True, name=f"agent-run-{short_id}")
    t.start()
    return t
