"""V4 solve pipeline quality tier resolution (IR-21)."""

from __future__ import annotations

import os
from typing import Any

_TIER_LIMITS = {
    "fast": {"max_fix": 1, "max_regen": 0, "force_skip_validation": True, "include_diagrams": False},
    "standard": {"max_fix": 2, "max_regen": 1, "force_skip_validation": False, "include_diagrams": False},
    "thorough": {"max_fix": 3, "max_regen": 1, "force_skip_validation": False, "include_diagrams": True},
}

_LIGHT_QUESTION_TYPES = frozenset({"code_cloze", "theory"})


def pipeline_version(settings: dict | None) -> str:
    env = (os.environ.get("SOLVE_PIPELINE") or "").strip().lower()
    if env in ("v1", "v4"):
        return env
    ver = (settings or {}).get("solvePipelineVersion") or (settings or {}).get(
        "solve_pipeline_version"
    )
    return (ver or "v4").strip().lower()


def should_use_pipeline(settings: dict | None) -> bool:
    return pipeline_version(settings) != "v1"


def _auto_fast_tier_enabled(settings: dict | None) -> bool:
    settings = settings or {}
    val = settings.get("autoFastTierForLightQuestions")
    if val is None:
        val = settings.get("auto_fast_tier_for_light_questions")
    if val is None:
        return True
    return bool(val)


def is_light_question(ctx: dict | None) -> bool:
    """True when V4 deep fix/regen is unlikely to help (IR-13a)."""
    if not ctx:
        return False
    qtype = ((ctx.get("question") or {}).get("type") or "").strip().lower()
    if qtype in _LIGHT_QUESTION_TYPES:
        return True
    if qtype in ("mixed_assignment", "lab_report"):
        steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
        checked = [
            (s.get("module") or "").strip()
            for s in steps
            if s.get("default_checked", True) is not False
        ]
        mods = set(checked)
        if "solve_code_cloze" in mods and "solve_lab" not in mods and "run_code" not in mods:
            return True
        if mods and mods <= {"solve_theory", "present_deliverable", "fill_report"}:
            return True
        if "solve_lab" in mods and "run_code" not in mods and "render_uml" not in mods:
            import re

            report = ctx.get("planner_input_text") or ctx.get("report_text") or ""
            if report and not re.search(r"代码|程序|编程|运行|编译", report):
                return True
    return False


def resolve_solve_quality_tier(settings: dict | None, ctx: dict | None = None) -> str:
    """Normalize tier; apply auto-fast for light questions when not explicit (IR-13a)."""
    settings = settings or {}
    explicit = settings.get("solveQualityTierExplicit")
    if explicit is None:
        explicit = settings.get("solve_quality_tier_explicit")
    tier = settings.get("solveQualityTier") or settings.get("solve_quality_tier") or "standard"
    tier = str(tier).strip().lower()
    if tier not in _TIER_LIMITS:
        tier = "standard"
    if explicit:
        return tier
    run_mode = (
        settings.get("run_mode") or (ctx or {}).get("run_mode") or "standard"
    ).strip().lower()
    if run_mode in ("deep", "react"):
        return tier
    if _auto_fast_tier_enabled(settings) and is_light_question(ctx):
        return "fast"
    return tier


def tier_limits(tier: str) -> dict[str, Any]:
    return dict(_TIER_LIMITS.get((tier or "standard").lower(), _TIER_LIMITS["standard"]))
