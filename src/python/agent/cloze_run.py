"""Shared code-cloze run detection for executor modes (ReAct, deep, etc.)."""

from __future__ import annotations


def step_checked(steps: list, module: str) -> bool:
    for step in steps:
        if step.get("module") == module:
            return step.get("default_checked", True) is not False
    return False


def is_mixed_assignment_run(ctx: dict, steps: list) -> bool:
    if (ctx.get("metadata") or {}).get("mixed_assignment"):
        return True
    return step_checked(steps, "solve_theory") and step_checked(steps, "solve_code_cloze")


def is_code_cloze_run(ctx: dict, steps: list) -> bool:
    if is_mixed_assignment_run(ctx, steps):
        return False
    if step_checked(steps, "solve_code_cloze"):
        return True
    question = ctx.get("question") or {}
    if question.get("type") == "code_cloze":
        return True
    meta = ctx.get("metadata") or {}
    if meta.get("question_type") == "code_cloze":
        return True
    return bool((meta.get("code_cloze") or {}).get("is_code_cloze"))
