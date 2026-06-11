"""IR-19/21: V4 solve pipeline phase package."""

from modules.solve_phases.brief import run_brief_phase
from modules.solve_phases.code import run_code_phase
from modules.solve_phases.diagrams import run_diagrams_phase
from modules.solve_phases.fix import run_fix_narrow_phase
from modules.solve_phases.orchestrate import retry_pipeline_validation, run_solve_pipeline
from modules.solve_phases.report import run_report_phase
from modules.solve_phases.sandbox import run_sandbox_phase
from modules.solve_phases.session import SolveSession, session_from_dict
from modules.solve_phases.tier import (
    is_light_question,
    pipeline_version,
    resolve_solve_quality_tier,
    should_use_pipeline,
    tier_limits,
)
from modules.solve_phases.types import SolvePhaseContext, SolvePhaseResult

__all__ = [
    "SolvePhaseContext",
    "SolvePhaseResult",
    "SolveSession",
    "is_light_question",
    "pipeline_version",
    "resolve_solve_quality_tier",
    "retry_pipeline_validation",
    "run_brief_phase",
    "run_code_phase",
    "run_diagrams_phase",
    "run_fix_narrow_phase",
    "run_report_phase",
    "run_sandbox_phase",
    "run_solve_pipeline",
    "session_from_dict",
    "should_use_pipeline",
    "tier_limits",
]
