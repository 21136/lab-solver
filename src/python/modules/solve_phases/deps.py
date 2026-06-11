"""Lazy delegation to solve_pipeline for test patch compatibility (IR-20)."""

from __future__ import annotations

from typing import Any


def runtime_available_for(language: str) -> bool:
    from modules.solve_pipeline import _runtime_available_for

    return _runtime_available_for(language)


def check_code_syntax(combined: str, language: str) -> dict[str, Any]:
    from modules.solve_pipeline import _check_code_syntax

    return _check_code_syntax(combined, language)


def check_execution_pattern(combined: str, language: str) -> dict[str, Any]:
    from modules.solve_pipeline import _check_execution_pattern

    return _check_execution_pattern(combined, language)


def prepare_validation_jars(*args: Any, **kwargs: Any) -> tuple[list[str], dict | None]:
    from modules.solve_pipeline import prepare_validation_jars

    return prepare_validation_jars(*args, **kwargs)


def execute_code(*args: Any, **kwargs: Any) -> tuple[str, bool]:
    from modules.solve_pipeline import execute_code

    return execute_code(*args, **kwargs)


def execute_multi_file(*args: Any, **kwargs: Any) -> tuple[str, bool]:
    from modules.solve_pipeline import execute_multi_file

    return execute_multi_file(*args, **kwargs)


def classify_run_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from modules.solve_pipeline import classify_run_error

    return classify_run_error(*args, **kwargs)


def fix_code_from_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from modules.solve_pipeline import fix_code_from_error

    return fix_code_from_error(*args, **kwargs)


def apply_fix_to_solve_data(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from modules.solve_pipeline import apply_fix_to_solve_data

    return apply_fix_to_solve_data(*args, **kwargs)
