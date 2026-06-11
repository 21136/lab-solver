"""Re-exported on modules.solve_pipeline for tests and deps.py (IR-21)."""

from config import _runtime_available_for
from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
from modules.java_jars import JarConsentCallback, prepare_validation_jars
from modules.preflight import _check_code_syntax, _check_execution_pattern
from modules.run_code import classify_run_error, execute_code, execute_multi_file
from modules.solve_phases._common import (
    REGEN_THRESHOLD,
    combined_code as _combined_code,
    emit as _emit,
    record_phase as _record_phase,
)
from modules.solve_phases._llm import call_llm as _call_llm, track_prompt as _track_prompt
from modules.solve_phases.brief import understand_brief as _understand_brief
from modules.solve_phases.code import regen_code_full as _regen_code_full, solve_code as _solve_code
from modules.solve_phases.diagrams import (
    code_structure_summary as _code_structure_summary,
    solve_diagrams as _solve_diagrams,
)
from modules.solve_phases.fix import fix_code_narrow as _fix_code_narrow
from modules.solve_phases.loop import run_validation_loop as _run_validation_loop
from modules.solve_phases.report import write_report_text as _write_report_text
from modules.solve_phases.sandbox import run_sandbox as _run_sandbox

__all__ = [
    "JarConsentCallback",
    "REGEN_THRESHOLD",
    "_call_llm",
    "_check_code_syntax",
    "_check_execution_pattern",
    "_code_structure_summary",
    "_combined_code",
    "_emit",
    "_fix_code_narrow",
    "_record_phase",
    "_regen_code_full",
    "_run_sandbox",
    "_run_validation_loop",
    "_runtime_available_for",
    "_solve_code",
    "_solve_diagrams",
    "_track_prompt",
    "_understand_brief",
    "_write_report_text",
    "apply_fix_to_solve_data",
    "classify_run_error",
    "execute_code",
    "execute_multi_file",
    "fix_code_from_error",
    "prepare_validation_jars",
]
