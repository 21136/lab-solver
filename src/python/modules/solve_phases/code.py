"""IR-19/20: solve_code / regen_code_full phases."""

from __future__ import annotations

import time

from agent.prompts import render_code_only_prompt
from modules.lab_parse import complete_lab_parsed, parse_lab_json
from modules.solve_phases._common import record_phase
from modules.solve_phases._llm import track_prompt
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult, last_phase_record
from modules.user_constraints import build_constraints_prompt_block


def solve_code(
    settings: dict,
    session,
    question: dict,
    *,
    phase_id: str = "solve_code",
) -> None:
    prompt = render_code_only_prompt(
        session.brief.get("task_summary") or question.get("full_text") or "",
        language=session.language,
        constraints_block=build_constraints_prompt_block(session.constraints_applied),
        format_constraints=question.get("format_constraints") or "",
    )
    track_prompt(session, "code_only")
    t0 = time.monotonic()
    from modules.solve_pipeline import _call_llm

    answer = _call_llm(settings, prompt, phase="solve_code", max_tokens=4000)
    parsed = complete_lab_parsed(parse_lab_json(answer), answer)
    session.code_files = parsed.get("code_files") or []
    session.main_file = parsed.get("main_file") or ""
    session.language = parsed.get("language") or session.language
    if not session.code_files and (parsed.get("code") or "").strip():
        ext = {"python": "main.py", "java": "Main.java", "c": "main.c", "cpp": "main.cpp", "javascript": "main.js"}
        fname = session.main_file or ext.get(session.language.lower(), "main.txt")
        session.code_files = [{"name": fname, "code": parsed.get("code") or ""}]
        session.main_file = fname
    if "single_file" in session.constraints_applied and len(session.code_files) > 1:
        session.code_files = [session.code_files[0]]
        session.main_file = session.code_files[0].get("name") or session.main_file
    session.code_attempts += 1
    record_phase(session, phase_id, "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))


def regen_code_full(
    settings: dict,
    session,
    question: dict,
    *,
    failure_note: str,
) -> None:
    """Full code regen after repeated same-category failures (thorough/standard tiers)."""
    regen_question = dict(question)
    note = (failure_note or "上轮内化验证失败")[:800]
    extra = f"\n\n【上轮失败摘要】{note}\n请重写完整可运行源码，勿重复相同错误。"
    regen_question["format_constraints"] = ((regen_question.get("format_constraints") or "") + extra).strip()
    solve_code(settings, session, regen_question, phase_id="regen_code_full")


def run_code_phase(ctx: SolvePhaseContext, *, phase_id: str = "solve_code") -> SolvePhaseResult:
    before = len(ctx.session.phases)
    solve_code(ctx.settings, ctx.session, ctx.question, phase_id=phase_id)
    rec = last_phase_record(ctx.session, phase_id) or {}
    llm_calls = int(rec.get("llm_calls") or 0)
    status = str(rec.get("status") or "ok")
    if len(ctx.session.phases) <= before:
        return SolvePhaseResult(phase_id=phase_id, status="ok", llm_calls=llm_calls)
    return SolvePhaseResult(phase_id=phase_id, status=status, llm_calls=llm_calls)
