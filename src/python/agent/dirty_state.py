"""
Table-driven dirty / rerun transitions for verify and revise paths (IR-23).

Public callers should use executor_dirty wrappers; this module holds the
transition tables and context-derived predicates only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

FillSectionsFn = Callable[[set[str], dict[str, Any] | None], Optional[list[str]]]


@dataclass(frozen=True)
class VerifyContext:
    verified: bool
    code_cloze: bool


@dataclass(frozen=True)
class VerifyResolution:
    """Modules to rerun plus optional dirty metadata from one verify action."""

    modules: tuple[str, ...]
    dirty_fields: dict[str, list[str]] | None = None
    fill_sections: list[str] | None = None
    touch_fill_sections: bool = False
    fill_from_section: bool = False
    owns_dirty_metadata: bool = False


def _norm_action(action: str) -> str:
    return (action or "").strip().lower()


def is_code_cloze_ctx(ctx: dict[str, Any] | None) -> bool:
    if not ctx:
        return False
    from agent.cloze_run import is_code_cloze_run

    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    if is_code_cloze_run(ctx, steps):
        return True
    solve = ((ctx.get("module_results") or {}).get("solve_code_cloze") or {}).get("data") or {}
    return solve.get("type") == "code_cloze"


def verify_context_from_ctx(ctx: dict[str, Any] | None, *, verified: bool) -> VerifyContext:
    return VerifyContext(verified=verified, code_cloze=is_code_cloze_ctx(ctx))


def _resolve_fix_code(vc: VerifyContext) -> VerifyResolution:
    if vc.verified:
        return VerifyResolution(modules=())
    return VerifyResolution(
        modules=("fix_code", "run_code"),
        dirty_fields={"solve_lab": ["code"]},
        owns_dirty_metadata=True,
    )


def _resolve_fix_diagrams(_vc: VerifyContext) -> VerifyResolution:
    return VerifyResolution(
        modules=("fix_diagrams", "render_uml"),
        dirty_fields={"solve_lab": ["diagrams"]},
        owns_dirty_metadata=True,
    )


def _resolve_render_uml(_vc: VerifyContext) -> VerifyResolution:
    return VerifyResolution(modules=("render_uml",))


def _resolve_revise_section(vc: VerifyContext, section: str) -> VerifyResolution:
    if vc.verified:
        return VerifyResolution(
            modules=("revise_answer",),
            dirty_fields={"solve_lab": [section]} if section else None,
            owns_dirty_metadata=True,
        )
    return VerifyResolution(
        modules=("fill_report",),
        fill_from_section=True,
        owns_dirty_metadata=True,
    )


def _resolve_revise_full(vc: VerifyContext) -> VerifyResolution:
    if vc.verified:
        if vc.code_cloze:
            dirty = {"solve_code_cloze": ["blanks"]}
        else:
            dirty = {
                "solve_lab": ["steps_analysis", "result_description", "summary", "expected_output"],
            }
        return VerifyResolution(
            modules=("revise_answer",),
            dirty_fields=dirty,
            fill_sections=None,
            touch_fill_sections=True,
            owns_dirty_metadata=True,
        )
    if vc.code_cloze:
        return VerifyResolution(
            modules=("solve_code_cloze",),
            dirty_fields={"solve_code_cloze": ["full"]},
            fill_sections=None,
            touch_fill_sections=True,
            owns_dirty_metadata=True,
        )
    return VerifyResolution(
        modules=("solve_lab",),
        dirty_fields={"solve_lab": ["full"]},
        fill_sections=None,
        touch_fill_sections=True,
        owns_dirty_metadata=True,
    )


_VERIFY_RESOLVERS: dict[str, Callable[[VerifyContext, str], VerifyResolution]] = {
    "fix_code": lambda vc, _s: _resolve_fix_code(vc),
    "fix_diagrams": lambda vc, _s: _resolve_fix_diagrams(vc),
    "render_uml": lambda vc, _s: _resolve_render_uml(vc),
    "revise_full": lambda vc, _s: _resolve_revise_full(vc),
}


def resolve_verify_action(action: str, vc: VerifyContext) -> VerifyResolution | None:
    a = _norm_action(action)
    if a.startswith("revise_section:"):
        section = a.split(":", 1)[-1].strip()
        return _resolve_revise_section(vc, section)
    resolver = _VERIFY_RESOLVERS.get(a)
    if resolver is None:
        return None
    return resolver(vc, "")


def modules_for_verify_actions(
    suggested_actions: list[str],
    ctx: dict[str, Any] | None,
    *,
    verified: bool,
) -> list[str]:
    """Map verify_answer suggested_actions to executor module ids (deduped, order preserved)."""
    vc = verify_context_from_ctx(ctx, verified=verified)
    out: list[str] = []
    for action in suggested_actions or []:
        resolution = resolve_verify_action(action, vc)
        if resolution is None:
            continue
        out.extend(resolution.modules)
    return list(dict.fromkeys(out))


def apply_verify_dirty_metadata(
    ctx: dict[str, Any],
    suggested_actions: list[str],
    *,
    verified: bool,
    fill_sections_for_groups: FillSectionsFn,
) -> None:
    """Set dirty_fields / fill_sections from the first action that owns dirty metadata."""
    vc = verify_context_from_ctx(ctx, verified=verified)
    for action in suggested_actions or []:
        resolution = resolve_verify_action(action, vc)
        if resolution is None or not resolution.owns_dirty_metadata:
            continue
        if resolution.dirty_fields is not None:
            ctx["dirty_fields"] = resolution.dirty_fields
        if resolution.touch_fill_sections:
            ctx["fill_sections"] = resolution.fill_sections
        elif resolution.fill_from_section:
            section = _norm_action(action).split(":", 1)[-1].strip()
            if section:
                ctx["fill_sections"] = fill_sections_for_groups({section}, ctx=ctx) or [section]
        break
