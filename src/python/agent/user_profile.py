"""
User profile v1 (Phase 2b B4) + C2 behavior learning (V3-4).

Behavior stats are local-only, gated by ``optimize_plan_from_usage`` (default on).
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from typing import Any, Optional

from config import APP_DATA

PROFILE_SCHEMA_VERSION = 2
PROFILE_PATH = APP_DATA / "profile.json"

BEHAVIOR_MIN_SAMPLES = 3
_BEHAVIOR_LIST_MAX = 50
_OUTCOMES_MAX = 200

DEFAULT_BEHAVIOR: dict[str, Any] = {
    "module_cancel_count": {},
    "revise_tags": [],
    "replan_reasons": [],
    "failure_modules": [],
    "outcomes": [],
}

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": PROFILE_SCHEMA_VERSION,
    "default_language": "java",
    "prefer_uml": False,
    "optimize_plan_from_usage": True,
    "behavior": deepcopy(DEFAULT_BEHAVIOR),
}

V1_KEYS = frozenset(
    {
        "default_language",
        "prefer_uml",
        "major",
        "experiment_bias",
        "course_hints",
        "optimize_plan_from_usage",
        "behavior",
    }
)


def normalize_behavior(behavior: Optional[dict] = None) -> dict[str, Any]:
    """Ensure behavior sub-object has expected keys."""
    merged = deepcopy(DEFAULT_BEHAVIOR)
    if not behavior or not isinstance(behavior, dict):
        return merged
    cancel = behavior.get("module_cancel_count")
    if isinstance(cancel, dict):
        merged["module_cancel_count"] = {
            str(k): int(v) for k, v in cancel.items() if v is not None
        }
    for key in ("revise_tags", "replan_reasons", "failure_modules"):
        val = behavior.get(key)
        if isinstance(val, list):
            merged[key] = [str(x) for x in val if x is not None][-_BEHAVIOR_LIST_MAX:]
    outcomes = behavior.get("outcomes")
    if isinstance(outcomes, list):
        cleaned: list[dict[str, Any]] = []
        for item in outcomes[-_OUTCOMES_MAX:]:
            if isinstance(item, dict) and item.get("event"):
                cleaned.append(
                    {
                        "event": str(item.get("event")),
                        "at": str(item.get("at") or ""),
                        "section": str(item.get("section") or ""),
                        "run_id": str(item.get("run_id") or ""),
                        "format": str(item.get("format") or ""),
                    }
                )
        merged["outcomes"] = cleaned
    return merged


def normalize_profile(profile: Optional[dict] = None) -> dict[str, Any]:
    """Merge overlay onto defaults; ignore unknown keys for forward compat."""
    merged = deepcopy(DEFAULT_PROFILE)
    if not profile:
        return merged
    for key in V1_KEYS:
        if key in profile and profile[key] is not None:
            if key == "behavior":
                merged["behavior"] = normalize_behavior(profile.get("behavior"))
            else:
                merged[key] = profile[key]
    if profile.get("schema_version"):
        merged["schema_version"] = profile["schema_version"]
    merged["optimize_plan_from_usage"] = bool(merged.get("optimize_plan_from_usage"))
    merged["behavior"] = normalize_behavior(merged.get("behavior"))
    return merged


def merge_profile(base: Optional[dict], overlay: Optional[dict]) -> dict[str, Any]:
    """Shallow merge: overlay wins for v1 keys."""
    return normalize_profile({**(base or {}), **(overlay or {})})


def to_prompt_block(profile: dict) -> str:
    """Short block for planner / understand_plan prompts."""
    p = normalize_profile(profile)
    lines = [
        f"- 默认编程语言: {p.get('default_language', 'java')}",
        f"- 倾向 UML: {'是' if p.get('prefer_uml') else '否'}",
    ]
    if p.get("major"):
        lines.append(f"- 专业方向: {p['major']}")
    if p.get("experiment_bias"):
        lines.append(f"- 实验类型偏好: {p['experiment_bias']}")
    return "\n".join(lines)


def metadata_hints(metadata: Optional[dict]) -> str:
    """Course metadata for prompt (session-only, not persisted)."""
    meta = metadata or {}
    lines = []
    for key, label in (
        ("course", "课程"),
        ("experiment_title", "实验"),
        ("major", "专业"),
    ):
        val = meta.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else ""


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        return dict(DEFAULT_PROFILE)
    try:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return normalize_profile(raw)
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_PROFILE)


def save_profile(profile: dict) -> dict[str, Any]:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    normalized = normalize_profile(profile)
    normalized["schema_version"] = PROFILE_SCHEMA_VERSION
    PROFILE_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _behavior_enabled(profile: dict) -> bool:
    return bool(normalize_profile(profile).get("optimize_plan_from_usage"))


def _append_limited(items: list[str], value: str, *, max_items: int = _BEHAVIOR_LIST_MAX) -> None:
    val = (value or "").strip()
    if not val:
        return
    if val in items:
        items.remove(val)
    items.append(val)
    if len(items) > max_items:
        del items[: len(items) - max_items]


def record_module_cancel(profile: dict, module_id: str) -> dict[str, Any]:
    """Increment cancel count for a module (when user unchecks in plan UI)."""
    p = normalize_profile(profile)
    if not _behavior_enabled(p):
        return p
    mod = (module_id or "").strip()
    if not mod:
        return p
    behavior = p["behavior"]
    counts = behavior.setdefault("module_cancel_count", {})
    counts[mod] = int(counts.get(mod) or 0) + 1
    return p


def record_revise_tags(profile: dict, tags: list[str]) -> dict[str, Any]:
    p = normalize_profile(profile)
    if not _behavior_enabled(p):
        return p
    behavior = p["behavior"]
    for tag in tags or []:
        _append_limited(behavior.setdefault("revise_tags", []), str(tag).strip())
    return p


def record_replan_reason(profile: dict, reason: str) -> dict[str, Any]:
    p = normalize_profile(profile)
    if not _behavior_enabled(p):
        return p
    _append_limited(p["behavior"].setdefault("replan_reasons", []), reason)
    return p


def record_failure_module(profile: dict, module_id: str) -> dict[str, Any]:
    p = normalize_profile(profile)
    if not _behavior_enabled(p):
        return p
    mod = (module_id or "").strip()
    if mod:
        _append_limited(p["behavior"].setdefault("failure_modules", []), mod)
    return p


def apply_plan_feedback_to_profile(profile: dict, diff: dict) -> dict[str, Any]:
    """Apply plan checkbox toggles to behavior.module_cancel_count."""
    p = normalize_profile(profile)
    if not _behavior_enabled(p) or not diff.get("changed"):
        return p
    for toggle in diff.get("toggles") or []:
        if toggle.get("to_checked") is False:
            p = record_module_cancel(p, toggle.get("module") or "")
    return p


_FAILURE_HINT = "（历史上此步骤曾失败，请谨慎勾选）"
_CANCEL_HINT = "（根据历史习惯默认不勾选）"

_MODULE_FAILURE_LABELS = {
    "run_code": "run_code 常失败",
    "render_uml": "render_uml 常失败",
    "fill_report": "fill_report 常失败",
    "solve_lab": "solve_lab 常失败",
}


def _failure_module_counts(behavior: dict) -> Counter[str]:
    items = behavior.get("failure_modules") or []
    if not isinstance(items, list):
        return Counter()
    return Counter(str(x) for x in items if x)


def behavior_hints_block(profile: dict) -> str:
    """Weak C2 hints for planner prompt (failure_modules, no new steps)."""
    p = normalize_profile(profile)
    if not p.get("optimize_plan_from_usage"):
        return ""
    behavior = p.get("behavior") or {}
    failures = _failure_module_counts(behavior)
    lines: list[str] = []
    for mod, count in failures.most_common(6):
        if count < BEHAVIOR_MIN_SAMPLES:
            continue
        label = _MODULE_FAILURE_LABELS.get(mod, f"{mod} 曾失败")
        lines.append(f"- 上次运行中 {label}（近 {count} 次记录），计划时谨慎插入该步")
    if not lines:
        return ""
    return "【历史行为弱提示】（勿单独新增无报告依据的步骤）\n" + "\n".join(lines) + "\n"


def apply_behavior_to_steps(steps: list[dict], profile: dict) -> list[dict]:
    """Weak planner hint: default-uncheck modules cancelled often in the past."""
    p = normalize_profile(profile)
    if not p.get("optimize_plan_from_usage"):
        return steps
    behavior = p.get("behavior") or {}
    counts = behavior.get("module_cancel_count") or {}
    failures = _failure_module_counts(behavior)
    out: list[dict] = []
    for step in steps:
        s = dict(step)
        mod = s.get("module") or ""
        reason = (s.get("reason") or "").strip()
        if int(counts.get(mod) or 0) >= BEHAVIOR_MIN_SAMPLES and s.get("default_checked", True):
            s["default_checked"] = False
            if _CANCEL_HINT not in reason:
                s["reason"] = f"{reason}{_CANCEL_HINT}".strip() if reason else _CANCEL_HINT.strip("（）")
        elif failures.get(mod, 0) >= BEHAVIOR_MIN_SAMPLES:
            if _FAILURE_HINT not in reason:
                s["reason"] = f"{reason}{_FAILURE_HINT}".strip() if reason else _FAILURE_HINT.strip("（）")
        out.append(s)
    return out


def record_behavior_outcome(
    profile: dict,
    event: str,
    *,
    section: str = "",
    run_id: str = "",
    format: str = "",
) -> dict[str, Any]:
    """Record user adoption signal (copy / export / revise) for Keep rate."""
    from datetime import datetime, timezone

    p = normalize_profile(profile)
    if not _behavior_enabled(p):
        return p
    ev = (event or "").strip()
    if not ev:
        return p
    behavior = p["behavior"]
    outcomes = behavior.setdefault("outcomes", [])
    if not isinstance(outcomes, list):
        outcomes = []
        behavior["outcomes"] = outcomes
    outcomes.append(
        {
            "event": ev,
            "at": datetime.now(timezone.utc).isoformat(),
            "section": (section or "").strip(),
            "run_id": (run_id or "").strip(),
            "format": (format or "").strip(),
        }
    )
    if len(outcomes) > _OUTCOMES_MAX:
        del outcomes[: len(outcomes) - _OUTCOMES_MAX]
    return p


def compute_keep_rate_summary(profile: dict | None = None) -> dict[str, Any]:
    """Aggregate local outcome events into keep-rate style counters."""
    p = normalize_profile(profile)
    outcomes = (p.get("behavior") or {}).get("outcomes") or []
    if not isinstance(outcomes, list):
        outcomes = []
    counts: dict[str, int] = {}
    for item in outcomes:
        if not isinstance(item, dict):
            continue
        ev = str(item.get("event") or "")
        if ev:
            counts[ev] = int(counts.get(ev) or 0) + 1
    copy_events = int(counts.get("copy_section") or 0)
    export_events = sum(
        int(counts.get(k) or 0) for k in ("export_markdown", "export_docx", "export_deliverable")
    )
    revise_events = int(counts.get("revise_submit") or 0)
    total_positive = copy_events + export_events
    return {
        "outcome_counts": counts,
        "copy_section": copy_events,
        "export_events": export_events,
        "revise_submit": revise_events,
        "keep_signals": total_positive,
        "outcome_total": len(outcomes),
    }


def persist_run_behavior_from_ctx(ctx: dict) -> None:
    """At run end, record failure modules and replan reasons to on-disk profile."""
    merged = normalize_profile(merge_profile(load_profile(), ctx.get("user_profile")))
    if not merged.get("optimize_plan_from_usage"):
        return

    for mod, mr in (ctx.get("module_results") or {}).items():
        if isinstance(mr, dict) and not mr.get("ok"):
            merged = record_failure_module(merged, str(mod))

    for entry in ctx.get("decision_log") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("decision") == "replan_incremental":
            target = entry.get("target") or "plan"
            reason = (entry.get("reason") or "").strip()
            merged = record_replan_reason(merged, f"{target}: {reason}".strip())

    saved = save_profile(merged)
    ctx["user_profile"] = saved
