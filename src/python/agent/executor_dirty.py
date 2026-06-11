"""
Dirty-module tracking + sub_fingerprints for incremental rerun (Phase 2b B2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from agent.types import ModuleResult

# Parsed / solve_lab field keys tracked at sub-fingerprint level.
SUB_FIELD_KEYS = (
    "steps_analysis",
    "result_description",
    "expected_output",
    "summary",
    "code",
    "language",
    "diagrams",
)

FIELD_TO_GROUP: dict[str, str] = {
    "steps_analysis": "steps",
    "result_description": "result",
    "expected_output": "result",
    "summary": "summary",
    "code": "code",
    "language": "code",
    "diagrams": "diagrams",
    "steps": "steps",
    "result": "result",
}

# Downstream modules invalidated when a logical group changes.
GROUP_TO_MODULES: dict[str, frozenset[str]] = {
    "steps": frozenset({"fill_report"}),
    "result": frozenset({"fill_report"}),
    "summary": frozenset({"fill_report"}),
    "code": frozenset({"run_code", "fix_code", "fill_report"}),
    "diagrams": frozenset({"render_uml", "fill_report"}),
}

SCOPE_TO_GROUPS: dict[str, str] = {
    "steps": "steps",
    "result": "result",
    "summary": "summary",
    "code": "code",
    "full": "full",
}


_CORE_SEMANTICS = frozenset({"steps", "result", "summary"})


def fingerprint_value(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:24]}"


def compute_sub_fingerprints(solve_data: dict[str, Any]) -> dict[str, str]:
    """Field-level hashes for solve_lab output (parsed + top-level code/lang)."""
    parsed = solve_data.get("parsed") or {}
    subs: dict[str, str] = {}
    for key in SUB_FIELD_KEYS:
        if key in ("code", "language"):
            val = parsed.get(key) or solve_data.get(key)
        else:
            val = parsed.get(key)
        subs[key] = fingerprint_value(val if val is not None else "")
    subs["steps"] = subs["steps_analysis"]
    subs["result"] = fingerprint_value(
        {
            "result_description": parsed.get("result_description") or "",
            "expected_output": parsed.get("expected_output") or "",
        }
    )
    return subs


def groups_for_changed_fields(changed_fields: list[str], scope: list[str] | str | None = None) -> set[str]:
    groups: set[str] = set()
    for raw in changed_fields or []:
        key = (raw or "").strip().lower()
        groups.add(FIELD_TO_GROUP.get(key, key))
    if not groups and scope:
        if isinstance(scope, str):
            scope = [scope]
        for s in scope:
            g = SCOPE_TO_GROUPS.get((s or "").strip().lower())
            if g == "full":
                return {"steps", "result", "summary", "code", "diagrams"}
            if g:
                groups.add(g)
    return groups


def downstream_modules_for_groups(groups: set[str]) -> list[str]:
    """Modules that must rerun after solve_lab fields change (excludes solve_lab itself)."""
    if "full" in groups or not groups:
        return [
            "run_code",
            "fix_code",
            "render_uml",
            "fill_report",
        ]
    dirty: set[str] = set()
    for g in groups:
        dirty.update(GROUP_TO_MODULES.get(g, frozenset()))
    dirty.discard("solve_lab")
    return sorted(dirty)


def fill_sections_for_groups(groups: set[str], ctx: dict[str, Any] | None = None) -> Optional[list[str]]:
    """Subset of fill_lab section keys; None = fill all sections.

    When ctx includes sections_detected, non-core sections with mode=auto are
    also included so that fill_report writes them.
    """
    if "full" in groups or not groups:
        return None
    sections: list[str] = []
    if "steps" in groups or "code" in groups:
        sections.append("steps")
    if "result" in groups:
        sections.append("result")
    if "summary" in groups:
        sections.append("summary")
    # Extend with non-core auto-mode sections from context
    if ctx:
        sd = ctx.get("sections_detected") or []
        fill_scope = (ctx.get("fill_scope") or {}).get("sections") or {}
        for sec in sd:
            semantic = sec.get("semantic")
            if semantic in _CORE_SEMANTICS:
                continue
            key = semantic or f"sec_{sec.get('index')}"
            if fill_scope.get(key) == "auto":
                sections.append(key)
    return sections or None


def mark_dirty_from_revise(
    ctx: dict[str, Any],
    *,
    changed_fields: list[str],
    scope: list[str] | str | None = None,
) -> list[str]:
    """Update dirty_modules / dirty_fields after revise_answer."""
    groups = groups_for_changed_fields(changed_fields, scope)
    modules = downstream_modules_for_groups(groups)
    ctx["dirty_fields"] = {k: list(groups) for k in ("solve_lab",) if groups}
    existing = set(ctx.get("dirty_modules") or [])
    existing.update(modules)
    ctx["dirty_modules"] = sorted(existing)
    ctx["fill_sections"] = fill_sections_for_groups(groups, ctx=ctx)
    return list(ctx["dirty_modules"])


def apply_revise_to_module_results(
    ctx: dict[str, Any],
    solve_data: dict[str, Any],
    *,
    changed_fields: list[str],
) -> ModuleResult:
    """Merge revised parsed into solve_lab module_results and refresh sub_fingerprints."""
    mr = dict((ctx.get("module_results") or {}).get("solve_lab") or {})
    merged = dict(solve_data)
    parsed = dict(merged.get("parsed") or {})
    if merged.get("code"):
        parsed["code"] = merged["code"]
    if merged.get("language"):
        parsed["language"] = merged["language"]
    merged["parsed"] = parsed
    merged["type"] = merged.get("type") or "lab_report"

    old_subs = mr.get("sub_fingerprints") or {}
    new_subs = compute_sub_fingerprints(merged)
    actually_changed = [
        f
        for f in changed_fields
        if old_subs.get(f) != new_subs.get(f) or old_subs.get(FIELD_TO_GROUP.get(f, "")) != new_subs.get(FIELD_TO_GROUP.get(f, ""))
    ]
    if not actually_changed and changed_fields:
        actually_changed = list(changed_fields)

    result = ModuleResult(
        ok=True,
        data=merged,
        logs=mr.get("logs") or [],
        fingerprint=mr.get("fingerprint") or fingerprint_value({"module": "solve_lab", "rev": len(changed_fields)}),
        sub_fingerprints=new_subs,
        cacheable=True,
    )
    ctx.setdefault("module_results", {})["solve_lab"] = result
    return result


def should_rerun_module(ctx: dict[str, Any], module: str, *, force: bool = False) -> bool:
    """
    Return True if the module must execute again.
    Checks dirty_modules first, then whether a cached ok result exists.
    """
    if force:
        return True
    dirty = set(ctx.get("dirty_modules") or [])
    if module in dirty:
        return True
    prior = (ctx.get("module_results") or {}).get(module)
    if not prior or not prior.get("ok"):
        return True
    # solve_lab draft skip handled separately; if dirty not set and ok, reuse
    return False


def note_module_reused(ctx: dict[str, Any], module: str) -> None:
    """Remove module from dirty set after successful reuse."""
    dirty = [m for m in (ctx.get("dirty_modules") or []) if m != module]
    ctx["dirty_modules"] = dirty


def note_module_completed(ctx: dict[str, Any], module: str) -> None:
    note_module_reused(ctx, module)


def sub_fingerprints_unchanged(
    ctx: dict[str, Any],
    module: str,
    required_groups: set[str],
) -> bool:
    """True if solve_lab sub_fingerprints for required_groups match cached module input."""
    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    subs = solve_mr.get("sub_fingerprints") or {}
    if not subs:
        return False
    for g in required_groups:
        if g == "steps" and subs.get("steps") != subs.get("steps_analysis"):
            return False
        if g == "code" and not subs.get("code"):
            return False
    return module not in set(ctx.get("dirty_modules") or [])


def code_status_from_ctx(ctx: dict[str, Any] | None) -> str:
    """Read V4 code_status from orchestrator context."""
    if not ctx:
        return ""
    pipeline_meta = ctx.get("pipeline_meta") or {}
    if pipeline_meta.get("code_status"):
        return str(pipeline_meta["code_status"])
    solve_session = ctx.get("solve_session") or {}
    if solve_session.get("code_status"):
        return str(solve_session["code_status"])
    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    data = solve_mr.get("data") or {}
    meta = data.get("pipeline_meta") or {}
    return str(meta.get("code_status") or "")


def _is_code_cloze_verify_ctx(ctx: dict[str, Any] | None) -> bool:
    if not ctx:
        return False
    from agent.cloze_run import is_code_cloze_run

    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    if is_code_cloze_run(ctx, steps):
        return True
    solve = ((ctx.get("module_results") or {}).get("solve_code_cloze") or {}).get("data") or {}
    return solve.get("type") == "code_cloze"


def modules_to_rerun_from_verify(
    suggested_actions: list[str],
    ctx: dict[str, Any] | None = None,
) -> list[str]:
    """Map verify_answer suggested_actions to executor module ids."""
    verified = code_status_from_ctx(ctx) == "verified"
    code_cloze_run = _is_code_cloze_verify_ctx(ctx)
    out: list[str] = []
    for action in suggested_actions or []:
        a = (action or "").strip().lower()
        if a == "fix_code":
            if verified:
                continue
            out.extend(["fix_code", "run_code"])
        elif a == "fix_diagrams":
            out.extend(["fix_diagrams", "render_uml"])
        elif a == "render_uml":
            out.append("render_uml")
        elif a.startswith("revise_section:"):
            if verified:
                out.append("revise_answer")
            else:
                out.append("fill_report")
        elif a == "revise_full":
            if verified:
                out.append("revise_answer")
            elif code_cloze_run:
                out.append("solve_code_cloze")
            else:
                out.append("solve_lab")
    return list(dict.fromkeys(out))


def mark_dirty_from_verify(ctx: dict[str, Any], suggested_actions: list[str]) -> list[str]:
    """Mark modules dirty from verify suggested_actions so remediate reruns them."""
    modules = modules_to_rerun_from_verify(suggested_actions, ctx)
    existing = set(ctx.get("dirty_modules") or [])
    existing.update(modules)
    ctx["dirty_modules"] = sorted(existing)
    verified = code_status_from_ctx(ctx) == "verified"

    for action in suggested_actions or []:
        a = (action or "").strip().lower()
        if a == "revise_full":
            if verified:
                if _is_code_cloze_verify_ctx(ctx):
                    ctx["dirty_fields"] = {"solve_code_cloze": ["blanks"]}
                else:
                    ctx["dirty_fields"] = {
                        "solve_lab": ["steps_analysis", "result_description", "summary", "expected_output"]
                    }
            elif _is_code_cloze_verify_ctx(ctx):
                ctx["dirty_fields"] = {"solve_code_cloze": ["full"]}
            else:
                ctx["dirty_fields"] = {"solve_lab": ["full"]}
            ctx["fill_sections"] = None
            break
        if a == "fix_diagrams":
            ctx["dirty_fields"] = {"solve_lab": ["diagrams"]}
            break
        if a.startswith("revise_section:"):
            section = a.split(":", 1)[-1].strip()
            if verified:
                ctx["dirty_fields"] = {"solve_lab": [section]}
            elif section:
                ctx["fill_sections"] = fill_sections_for_groups({section}, ctx=ctx) or [section]
            break
        if a == "fix_code" and not verified:
            ctx["dirty_fields"] = {"solve_lab": ["code"]}
            break

    return list(ctx["dirty_modules"])
