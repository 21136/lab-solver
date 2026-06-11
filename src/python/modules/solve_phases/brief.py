"""IR-19/20: understand_brief phase."""

from __future__ import annotations

import time

from modules.code_keywords import assignment_needs_code
from modules.solve_phases._common import emit, record_phase
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult


def understand_brief(question: dict, language: str, constraints: list[str]) -> dict:
    full_text = (question.get("full_text") or question.get("content") or "").strip()
    text_lower = full_text.lower()
    needs_code = assignment_needs_code(full_text, text_lower)
    if question.get("include_code") is False:
        needs_code = False
    brief_constraints = list(constraints)
    if "no_external_jar" in constraints:
        brief_constraints.append("无外部 jar，仅 JDK 标准库")
    if "single_file" in constraints:
        brief_constraints.append("单文件源码")
    needs_uml = bool(question.get("include_uml"))
    if not needs_uml and full_text:
        try:
            from config import detect_needs_uml

            dneeds = detect_needs_uml(full_text)
            needs_uml = bool(dneeds.get("needs_uml"))
        except Exception:
            pass
    return {
        "task_summary": full_text[:400] or "实验报告",
        "language": language,
        "needs_code": needs_code,
        "needs_uml": needs_uml,
        "execution_profile": "cli_script",
        "constraints": brief_constraints,
        "risks": [],
    }


def run_brief_phase(ctx: SolvePhaseContext) -> SolvePhaseResult:
    emit(ctx.on_phase, "understand_brief", "running", "读题对齐")
    t0 = time.monotonic()
    ctx.session.brief = understand_brief(
        ctx.question,
        ctx.session.language,
        ctx.constraints,
    )
    ms = int((time.monotonic() - t0) * 1000)
    record_phase(ctx.session, "understand_brief", "ok", llm_calls=0, ms=ms)
    emit(ctx.on_phase, "understand_brief", "ok")
    return SolvePhaseResult(phase_id="understand_brief", status="ok", llm_calls=0)
