"""IR-20: shared sandbox validation + fix/regen loop."""

from __future__ import annotations

from typing import Any

from modules.java_jars import JarConsentCallback
from modules.solve_phases._common import REGEN_THRESHOLD, PhaseCallback, emit
from modules.solve_phases.sandbox import run_sandbox


def run_validation_loop(
    settings: dict,
    session,
    question: dict,
    *,
    limits: dict[str, Any],
    skip_run: bool,
    on_phase: PhaseCallback | None = None,
    on_jar_consent: JarConsentCallback | None = None,
    approved_jar_ids: list[str] | None = None,
    sandbox_detail: str = "内化验证",
    allow_regen: bool = True,
) -> None:
    """Run sandbox validation with fix/regen retries; mutates session in place."""
    from modules.solve_pipeline import _fix_code_narrow, _regen_code_full

    max_fix = limits["max_fix"]
    max_regen = limits["max_regen"]
    fix_rounds = 0
    regen_rounds = 0
    last_error_category = ""
    same_category_streak = 0
    while True:
        emit(on_phase, "run_code_sandbox", "running", sandbox_detail)
        run_sandbox(
            session,
            skip_run=skip_run,
            on_jar_consent=on_jar_consent,
            approved_jar_ids=approved_jar_ids,
        )
        if session.code_status == "verified" or skip_run:
            break
        if fix_rounds >= max_fix and regen_rounds >= max_regen:
            break
        if session.code_status != "degraded":
            break
        err_cat = (session.run_result or {}).get("error_category") or ""
        if err_cat and err_cat == last_error_category:
            same_category_streak += 1
        else:
            same_category_streak = 1
            last_error_category = err_cat
        if (
            allow_regen
            and same_category_streak >= REGEN_THRESHOLD
            and regen_rounds < max_regen
        ):
            emit(on_phase, "regen_code_full", "running", "同错重生代码")
            err_msg = (session.run_result or {}).get("stderr") or (session.run_result or {}).get("output") or ""
            _regen_code_full(settings, session, question, failure_note=err_msg)
            regen_rounds += 1
            same_category_streak = 0
            last_error_category = ""
            emit(on_phase, "regen_code_full", "ok")
            continue
        if fix_rounds >= max_fix:
            break
        emit(on_phase, "fix_code_narrow", "running", "修复代码")
        if not _fix_code_narrow(settings, session, question):
            break
        fix_rounds += 1
        emit(on_phase, "fix_code_narrow", "ok")
