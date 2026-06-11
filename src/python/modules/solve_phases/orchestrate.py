"""V4 solve pipeline orchestration — run / retry entry points (IR-21)."""

from __future__ import annotations

import uuid
from typing import Any

from log_util import logi
from modules.java_jars import JarConsentCallback
from modules.solve_phases._common import emit, record_phase
from modules.solve_phases.brief import run_brief_phase
from modules.solve_phases.code import run_code_phase
from modules.solve_phases.diagrams import run_diagrams_phase
from modules.solve_phases.loop import run_validation_loop
from modules.solve_phases.report import run_report_phase
from modules.solve_phases.session import PhaseCallback, SolveSession, session_from_dict
from modules.solve_phases.tier import resolve_solve_quality_tier, tier_limits
from modules.solve_phases.types import SolvePhaseContext
from modules.user_constraints import normalize_user_constraints, should_skip_validation


def phase_ctx(
    settings: dict,
    question: dict,
    session: SolveSession,
    *,
    limits: dict[str, Any],
    constraints: list[str],
    skip_run: bool,
    on_phase: PhaseCallback | None,
    on_jar_consent: JarConsentCallback | None,
    approved_jar_ids: list[str] | None,
) -> SolvePhaseContext:
    return SolvePhaseContext(
        settings=settings,
        question=question,
        session=session,
        constraints=constraints,
        limits=limits,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
        skip_run=skip_run,
    )


def finish_pipeline(
    settings: dict,
    session: SolveSession,
    question: dict,
    limits: dict[str, Any],
    *,
    constraints: list[str],
    skip_run: bool,
    on_phase: PhaseCallback | None,
    on_jar_consent: JarConsentCallback | None,
    approved_jar_ids: list[str] | None,
    report_detail: str = "撰写报告",
) -> dict[str, Any]:
    ctx = phase_ctx(
        settings,
        question,
        session,
        limits=limits,
        constraints=constraints,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
    )
    emit(on_phase, "write_report_text", "running", report_detail)
    run_report_phase(ctx)
    emit(on_phase, "write_report_text", "ok")

    if limits["include_diagrams"] and session.brief.get("needs_uml"):
        emit(on_phase, "solve_diagrams", "running", "生成设计图")
        run_diagrams_phase(ctx)
        emit(on_phase, "solve_diagrams", "ok", f"{len(session.diagrams)} 张图")

    record_phase(session, "assemble_answer", "ok", llm_calls=0)
    return session.to_solve_lab_data()


def retry_pipeline_validation(
    settings: dict,
    session_data: dict,
    question: dict,
    *,
    tier: str = "standard",
    on_phase: PhaseCallback | None = None,
    on_jar_consent: JarConsentCallback | None = None,
    approved_jar_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-run sandbox validation (+ report refresh) without regenerating code."""
    question = dict(question or {})
    session = session_from_dict(session_data)
    session.constraints_applied = normalize_user_constraints(session.constraints_applied)
    tier_norm = resolve_solve_quality_tier({"solveQualityTier": tier})
    session.quality_tier = tier_norm
    limits = tier_limits(tier_norm)
    skip_run = should_skip_validation(session.constraints_applied) or limits["force_skip_validation"]

    run_validation_loop(
        settings,
        session,
        question,
        limits=limits,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
        sandbox_detail="内化验证（jar 就绪后重试）",
    )

    data = finish_pipeline(
        settings,
        session,
        question,
        limits,
        constraints=session.constraints_applied,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
    )
    logi(
        "pipeline",
        f"retry-validation session={session.session_id} code_status={session.code_status}",
    )
    return data


def run_solve_pipeline(
    settings: dict,
    question: dict,
    *,
    include_uml: bool = False,
    format_spec: dict | None = None,
    tier: str = "standard",
    user_constraints: list[str] | None = None,
    on_phase: PhaseCallback | None = None,
    on_jar_consent: JarConsentCallback | None = None,
    approved_jar_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run V4 pipeline; returns legacy solve_lab-shaped dict + pipeline_meta."""
    del format_spec  # reserved for V4-1 format injection
    question = dict(question or {})
    tier_norm = resolve_solve_quality_tier({"solveQualityTier": tier})
    limits = tier_limits(tier_norm)
    if limits["include_diagrams"] and include_uml:
        question["include_uml"] = True
    elif not limits["include_diagrams"]:
        question["include_uml"] = False

    constraints = normalize_user_constraints(user_constraints)
    skip_run = should_skip_validation(constraints) or limits["force_skip_validation"]

    language = (
        question.get("preferred_lang")
        or question.get("language")
        or (settings.get("profile") or {}).get("default_language")
        or "python"
    )

    session = SolveSession(
        session_id=f"sess_{uuid.uuid4().hex[:12]}",
        pipeline_version="v4",
        language=language,
        constraints_applied=constraints,
    )
    session.quality_tier = tier_norm

    ctx = phase_ctx(
        settings,
        question,
        session,
        limits=limits,
        constraints=constraints,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
    )
    run_brief_phase(ctx)

    if not session.brief.get("needs_code"):
        session.code_status = "skipped"
        data = finish_pipeline(
            settings,
            session,
            question,
            limits,
            constraints=constraints,
            skip_run=skip_run,
            on_phase=on_phase,
            on_jar_consent=on_jar_consent,
            approved_jar_ids=approved_jar_ids,
            report_detail="纯理论题，撰写报告",
        )
        logi("pipeline", f"theory-only session={session.session_id} llm={session.total_llm_calls}")
        return data

    emit(on_phase, "solve_code", "running", "生成代码")
    run_code_phase(ctx)
    emit(on_phase, "solve_code", "ok")

    run_validation_loop(
        settings,
        session,
        question,
        limits=limits,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
    )

    data = finish_pipeline(
        settings,
        session,
        question,
        limits,
        constraints=constraints,
        skip_run=skip_run,
        on_phase=on_phase,
        on_jar_consent=on_jar_consent,
        approved_jar_ids=approved_jar_ids,
    )
    logi(
        "pipeline",
        f"session={session.session_id} code_status={session.code_status} llm={session.total_llm_calls}",
    )
    return data
