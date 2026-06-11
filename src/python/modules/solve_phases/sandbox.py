"""IR-19/20: run_code_sandbox phase."""

from __future__ import annotations

import time

from modules.solve_phases import deps
from modules.solve_phases._common import combined_code, record_phase
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult, last_phase_record
from modules.user_constraints import has_disallowed_external_imports


def run_sandbox(
    session,
    *,
    skip_run: bool,
    on_jar_consent=None,
    approved_jar_ids: list[str] | None = None,
) -> None:
    if skip_run:
        session.code_status = "skipped"
        session.run_result = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "is_error": False,
            "skipped": True,
            "reason": "skip_validation",
        }
        record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    combined = combined_code(session)
    if not combined.strip():
        session.code_status = "skipped"
        session.run_result = {"stdout": "", "stderr": "", "exit_code": 0, "is_error": False, "skipped": True}
        record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    if not deps.runtime_available_for(session.language):
        session.code_status = "skipped"
        session.run_result = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "is_error": False,
            "skipped": True,
            "reason": "no_runtime",
        }
        record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    if "no_external_jar" in session.constraints_applied and has_disallowed_external_imports(
        combined, session.language
    ):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": "代码含非 JDK 第三方 import（用户约束 no_external_jar）",
            "exit_code": 1,
            "is_error": True,
            "pattern": "external_jar",
        }
        record_phase(session, "run_code_sandbox", "failed", llm_calls=0)
        return

    t0 = time.monotonic()
    syntax = deps.check_code_syntax(combined, session.language)
    if not syntax.get("ok"):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": syntax.get("message") or "语法检查失败",
            "exit_code": 1,
            "is_error": True,
            "pattern": "syntax",
        }
        record_phase(session, "preflight_code", "failed", llm_calls=0, ms=int((time.monotonic() - t0) * 1000))
        return
    record_phase(session, "preflight_code", "ok", llm_calls=0, ms=int((time.monotonic() - t0) * 1000))

    java_classpath_jars: list[str] | None = None
    if (session.language or "").lower() == "java" and "no_external_jar" not in session.constraints_applied:
        jar_paths, jar_skip = deps.prepare_validation_jars(
            combined,
            session.language,
            session.constraints_applied,
            on_jar_consent=on_jar_consent,
            approved_jar_ids=approved_jar_ids,
        )
        if jar_skip:
            session.code_status = "skipped"
            session.run_result = jar_skip
            phase_status = "failed" if jar_skip.get("is_error") else "skipped"
            record_phase(session, "run_code_sandbox", phase_status, llm_calls=0)
            return
        if jar_paths:
            java_classpath_jars = jar_paths

    pattern = deps.check_execution_pattern(combined, session.language)
    if not pattern.get("ok"):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": pattern.get("message") or "预检未通过",
            "exit_code": 1,
            "is_error": True,
            "pattern": pattern.get("pattern"),
        }
        record_phase(session, "run_code_sandbox", "failed", llm_calls=0)
        return

    t1 = time.monotonic()
    try:
        if len(session.code_files) > 1:
            output, is_error = deps.execute_multi_file(
                session.code_files,
                session.language,
                session.main_file,
                java_classpath_jars=java_classpath_jars,
            )
        else:
            output, is_error = deps.execute_code(
                combined, session.language, java_classpath_jars=java_classpath_jars
            )
    except Exception as e:
        output, is_error = str(e), True

    classified = deps.classify_run_error(output, pattern.get("pattern") or "")
    session.run_result = {
        "stdout": output if not is_error else "",
        "stderr": output if is_error else "",
        "output": output,
        "exit_code": 1 if is_error else 0,
        "is_error": is_error,
        "error_category": classified.get("category"),
        "pattern": pattern.get("pattern"),
    }
    if is_error:
        session.code_status = "degraded"
        record_phase(session, "run_code_sandbox", "failed", llm_calls=0, ms=int((time.monotonic() - t1) * 1000))
    else:
        session.code_status = "verified"
        record_phase(session, "run_code_sandbox", "ok", llm_calls=0, ms=int((time.monotonic() - t1) * 1000))


def run_sandbox_phase(ctx: SolvePhaseContext) -> SolvePhaseResult:
    run_sandbox(
        ctx.session,
        skip_run=ctx.skip_run,
        on_jar_consent=ctx.on_jar_consent,
        approved_jar_ids=ctx.approved_jar_ids,
    )
    rec = last_phase_record(ctx.session, "run_code_sandbox")
    status = str((rec or {}).get("status") or ctx.session.code_status)
    return SolvePhaseResult(phase_id="run_code_sandbox", status=status, llm_calls=0)
