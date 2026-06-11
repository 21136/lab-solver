"""
IR-13b: Declarative parallel-safe module groups for RunOrchestrator.

Steps in the same group may run concurrently after shared prerequisites are met.
"""

from __future__ import annotations

from agent.types import PlanStep

# Order of groups matters only for documentation; matching is by set equality.
PARALLEL_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"run_code", "render_uml"}),
    frozenset({"solve_theory", "solve_code_cloze"}),
)

_PREREQS: dict[frozenset[str], frozenset[str]] = {
    frozenset({"run_code", "render_uml"}): frozenset({"solve_lab"}),
    frozenset({"solve_theory", "solve_code_cloze"}): frozenset(),
}


def parallel_prereqs_met(group: frozenset[str], completed_modules: set[str] | frozenset[str]) -> bool:
    needed = _PREREQS.get(group, frozenset())
    return needed <= set(completed_modules)


def scan_parallel_batch(
    steps: list[PlanStep],
    start: int,
    *,
    completed_modules: set[str] | frozenset[str],
    exclude_modules: frozenset[str],
) -> list[tuple[int, PlanStep]] | None:
    """Return consecutive plan steps that form a full parallel group, or None."""
    if start >= len(steps):
        return None
    first_mod = (steps[start].get("module") or "").strip()
    if not first_mod:
        return None

    matched_group: frozenset[str] | None = None
    for group in PARALLEL_GROUPS:
        if first_mod in group:
            matched_group = group
            break
    if not matched_group:
        return None

    batch: list[tuple[int, PlanStep]] = []
    for j in range(start, len(steps)):
        step = steps[j]
        mod = (step.get("module") or "").strip()
        if mod in exclude_modules or mod in completed_modules:
            break
        if not step.get("default_checked", True):
            break
        if mod not in matched_group:
            break
        batch.append((j, step))

    batch_mods = {(s.get("module") or "").strip() for _, s in batch}
    if batch_mods != matched_group or len(batch) < 2:
        return None
    if not parallel_prereqs_met(matched_group, completed_modules):
        return None
    return batch
