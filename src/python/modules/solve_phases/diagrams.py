"""IR-19/20: solve_diagrams phase."""

from __future__ import annotations

import time

from agent.prompts import render_solve_diagrams_prompt
from modules.lab_parse import parse_lab_json
from modules.solve_phases._common import combined_code, record_phase
from modules.solve_phases._llm import track_prompt
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult, last_phase_record


def code_structure_summary(session) -> str:
    lines: list[str] = []
    for f in session.code_files:
        name = f.get("name") or "file"
        code = (f.get("code") or f.get("content") or "").strip()
        if not code:
            continue
        for raw in code.splitlines()[:40]:
            line = raw.strip()
            if line.startswith("class ") or line.startswith("public class ") or line.startswith("def "):
                lines.append(f"{name}: {line[:120]}")
    return "\n".join(lines) or combined_code(session)[:1500]


def solve_diagrams(settings: dict, session, question: dict) -> None:
    if not session.brief.get("needs_uml"):
        return
    report_excerpt = (question.get("full_text") or question.get("content") or "")[:3000]
    prompt = render_solve_diagrams_prompt(
        task_summary=session.brief.get("task_summary") or "",
        code_summary=code_structure_summary(session),
        report_excerpt=report_excerpt,
    )
    track_prompt(session, "solve_diagrams")
    t0 = time.monotonic()
    from modules.solve_pipeline import _call_llm

    answer = _call_llm(settings, prompt, phase="solve_diagrams", max_tokens=6000)
    parsed = parse_lab_json(answer)
    diagrams = parsed.get("diagrams") or []
    session.diagrams = diagrams if isinstance(diagrams, list) else []
    record_phase(
        session,
        "solve_diagrams",
        "ok" if session.diagrams else "skipped",
        llm_calls=1,
        ms=int((time.monotonic() - t0) * 1000),
    )


def run_diagrams_phase(ctx: SolvePhaseContext) -> SolvePhaseResult:
    before = len(ctx.session.diagrams)
    solve_diagrams(ctx.settings, ctx.session, ctx.question)
    rec = last_phase_record(ctx.session, "solve_diagrams")
    if not rec:
        return SolvePhaseResult(phase_id="solve_diagrams", status="skipped", llm_calls=0)
    return SolvePhaseResult(
        phase_id="solve_diagrams",
        status=str(rec.get("status") or "ok"),
        llm_calls=int(rec.get("llm_calls") or 0),
    )
