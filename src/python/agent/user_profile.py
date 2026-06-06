"""
User profile v1 (Phase 2b B4) + C2 behavior learning (V3-4).

Behavior stats are local-only, gated by ``optimize_plan_from_usage`` (default off).
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Optional

from config import APP_DATA

PROFILE_SCHEMA_VERSION = 2
PROFILE_PATH = APP_DATA / "profile.json"

BEHAVIOR_MIN_SAMPLES = 3
_BEHAVIOR_LIST_MAX = 50

DEFAULT_BEHAVIOR: dict[str, Any] = {
    "module_cancel_count": {},
    "revise_tags": [],
    "replan_reasons": [],
    "failure_modules": [],
}

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": PROFILE_SCHEMA_VERSION,
    "default_language": "java",
    "screenshot_style": "ide",
    "prefer_uml": False,
    "optimize_plan_from_usage": False,
    "behavior": deepcopy(DEFAULT_BEHAVIOR),
}

V1_KEYS = frozenset(
    {
        "default_language",
        "screenshot_style",
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
        f"- 默认截图风格: {p.get('screenshot_style', 'ide')}（ide 或 terminal）",
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


def apply_behavior_to_steps(steps: list[dict], profile: dict) -> list[dict]:
    """Weak planner hint: default-uncheck modules cancelled often in the past."""
    p = normalize_profile(profile)
    if not p.get("optimize_plan_from_usage"):
        return steps
    counts = (p.get("behavior") or {}).get("module_cancel_count") or {}
    hint = "（根据历史习惯默认不勾选）"
    out: list[dict] = []
    for step in steps:
        s = dict(step)
        mod = s.get("module") or ""
        if int(counts.get(mod) or 0) >= BEHAVIOR_MIN_SAMPLES and s.get("default_checked", True):
            s["default_checked"] = False
            reason = (s.get("reason") or "").strip()
            if hint not in reason:
                s["reason"] = f"{reason}{hint}".strip() if reason else hint.strip("（）")
        out.append(s)
    return out


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
