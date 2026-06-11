"""IR-19/20: write_report_text phase."""

from __future__ import annotations

import time

from agent.prompts import render_write_report_prompt
from modules.lab_parse import parse_lab_json
from modules.solve_phases._common import combined_code, record_phase
from modules.solve_phases._llm import track_prompt
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult, last_phase_record


def write_report_text(settings: dict, session, question: dict) -> None:
    stdout = ""
    if session.run_result and not session.run_result.get("is_error"):
        stdout = session.run_result.get("stdout") or session.run_result.get("output") or ""
    degraded = session.code_status == "degraded"
    prompt = render_write_report_prompt(
        task_summary=session.brief.get("task_summary") or "",
        language=session.language,
        code_summary=combined_code(session)[:2000],
        sample_stdout=stdout,
        code_status=session.code_status,
        degraded=degraded,
        format_constraints=question.get("format_constraints") or "",
    )
    track_prompt(session, "write_report_text")
    t0 = time.monotonic()
    from modules.solve_pipeline import _call_llm

    answer = _call_llm(settings, prompt, phase="write_report_text", max_tokens=4000)
    parsed = parse_lab_json(answer)
    session.steps_analysis = parsed.get("steps_analysis") or ""
    session.result_description = parsed.get("result_description") or ""
    session.summary = parsed.get("summary") or ""
    session.notes = parsed.get("notes") or ""
    session.expected_output = stdout or parsed.get("expected_output") or ""
    if degraded and "未能运行" not in session.result_description:
        session.result_description = (
            "（代码未能通过内化验证，以下为预期行为说明）\n" + session.result_description
        ).strip()
    record_phase(session, "write_report_text", "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))


def run_report_phase(ctx: SolvePhaseContext) -> SolvePhaseResult:
    write_report_text(ctx.settings, ctx.session, ctx.question)
    rec = last_phase_record(ctx.session, "write_report_text") or {}
    return SolvePhaseResult(
        phase_id="write_report_text",
        status=str(rec.get("status") or "ok"),
        llm_calls=int(rec.get("llm_calls") or 1),
    )
