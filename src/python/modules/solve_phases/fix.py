"""IR-19/20: fix_code_narrow phase."""

from __future__ import annotations

import time

from modules.solve_phases import deps
from modules.solve_phases._common import record_phase
from modules.solve_phases._llm import track_prompt
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult, last_phase_record


def fix_code_narrow(settings: dict, session, question: dict) -> bool:
    run = session.run_result or {}
    err = run.get("stderr") or run.get("output") or ""
    if not err.strip():
        return False
    solve_stub = {
        "language": session.language,
        "code_files": session.code_files,
        "main_file": session.main_file,
        "parsed": {"code_files": session.code_files, "main_file": session.main_file},
    }
    t0 = time.monotonic()
    track_prompt(session, "fix_code")
    fix = deps.fix_code_from_error(
        settings,
        solve_stub,
        err,
        report_excerpt=(question.get("full_text") or "")[:1500],
        category=run.get("error_category") or "",
        pattern=run.get("pattern") or "",
    )
    updated = deps.apply_fix_to_solve_data(solve_stub, fix)
    session.code_files = updated.get("code_files") or session.code_files
    session.main_file = updated.get("main_file") or session.main_file
    session.language = updated.get("language") or session.language
    session.code_attempts += 1
    record_phase(session, "fix_code_narrow", "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))
    return True


def run_fix_narrow_phase(ctx: SolvePhaseContext) -> SolvePhaseResult:
    ok = fix_code_narrow(ctx.settings, ctx.session, ctx.question)
    if not ok:
        return SolvePhaseResult(phase_id="fix_code_narrow", status="skipped", llm_calls=0)
    rec = last_phase_record(ctx.session, "fix_code_narrow") or {}
    return SolvePhaseResult(
        phase_id="fix_code_narrow",
        status=str(rec.get("status") or "ok"),
        llm_calls=int(rec.get("llm_calls") or 1),
    )
