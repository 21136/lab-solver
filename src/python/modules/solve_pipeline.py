"""V4/V5 multi-phase solve pipeline — public facade (IR-21)."""

from __future__ import annotations

from modules.solve_phases._patch_surface import (  # noqa: F401
    REGEN_THRESHOLD,
    JarConsentCallback,
    _call_llm,
    _check_code_syntax,
    _check_execution_pattern,
    _code_structure_summary,
    _combined_code,
    _emit,
    _fix_code_narrow,
    _record_phase,
    _regen_code_full,
    _run_sandbox,
    _run_validation_loop,
    _runtime_available_for,
    _solve_code,
    _solve_diagrams,
    _track_prompt,
    _understand_brief,
    _write_report_text,
    apply_fix_to_solve_data,
    classify_run_error,
    execute_code,
    execute_multi_file,
    fix_code_from_error,
    prepare_validation_jars,
)
from modules.solve_phases.orchestrate import retry_pipeline_validation, run_solve_pipeline
from modules.solve_phases.session import PhaseCallback, SolveSession, session_from_dict
from modules.solve_phases.tier import (
    is_light_question,
    pipeline_version,
    resolve_solve_quality_tier,
    should_use_pipeline,
    tier_limits,
)

__all__ = [
    "JarConsentCallback",
    "PhaseCallback",
    "REGEN_THRESHOLD",
    "SolveSession",
    "is_light_question",
    "pipeline_version",
    "resolve_solve_quality_tier",
    "retry_pipeline_validation",
    "run_solve_pipeline",
    "session_from_dict",
    "should_use_pipeline",
    "tier_limits",
]
