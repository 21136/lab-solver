"""Record user edits to the agent plan (checkbox / order) without LLM or profile learning."""

from __future__ import annotations

import json
from typing import Any

from agent.decision_log import append_decision, summarize_for_history


def _norm_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "module": str(step.get("module") or ""),
        "checked": step.get("default_checked", True) is not False,
    }


def compute_plan_diff(
    baseline_steps: list[dict[str, Any]] | None,
    confirmed_steps: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Diff planner output vs user-confirmed steps before run."""
    baseline = [s for s in (baseline_steps or []) if isinstance(s, dict)]
    confirmed = [s for s in (confirmed_steps or []) if isinstance(s, dict)]
    base = [_norm_step(s, i) for i, s in enumerate(baseline)]
    conf = [_norm_step(s, i) for i, s in enumerate(confirmed)]

    order_before = [s["module"] for s in base]
    order_after = [s["module"] for s in conf]
    reordered = order_before != order_after

    toggles: list[dict[str, Any]] = []
    pair_len = min(len(base), len(conf))
    for i in range(pair_len):
        b, c = base[i], conf[i]
        if b["module"] == c["module"] and b["checked"] != c["checked"]:
            toggles.append(
                {
                    "module": b["module"],
                    "index": i,
                    "from_checked": b["checked"],
                    "to_checked": c["checked"],
                }
            )

    changed = reordered or bool(toggles) or len(base) != len(conf)
    return {
        "changed": changed,
        "reordered": reordered,
        "order_before": order_before,
        "order_after": order_after,
        "toggles": toggles,
        "step_count_before": len(base),
        "step_count_after": len(conf),
    }


def _diff_reason(diff: dict[str, Any]) -> str:
    if not diff.get("changed"):
        return "用户未修改计划步骤"
    parts: list[str] = []
    toggles = diff.get("toggles") or []
    if toggles:
        off = sum(1 for t in toggles if not t.get("to_checked"))
        on = sum(1 for t in toggles if t.get("to_checked"))
        if off:
            parts.append(f"取消勾选 {off} 步")
        if on:
            parts.append(f"勾选 {on} 步")
    if diff.get("reordered"):
        parts.append("调整步骤顺序")
    if diff.get("step_count_before") != diff.get("step_count_after"):
        parts.append("步骤数量变化")
    return "；".join(parts) if parts else "用户修改了计划"


def record_plan_feedback(
    baseline_steps: list[dict[str, Any]] | None,
    confirmed_steps: list[dict[str, Any]] | None,
    *,
    plan_fingerprint: str = "",
    document_ids: list[str] | None = None,
    apply_to_profile: bool = False,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Append a decision_log entry and return payload for Electron history.

    When ``apply_to_profile`` is true and ``optimize_plan_from_usage`` is on,
    checkbox toggles update ``profile.behavior.module_cancel_count``.
    """
    diff = compute_plan_diff(baseline_steps, confirmed_steps)
    ctx: dict[str, Any] = {"plan": {"plan_fingerprint": plan_fingerprint}}
    if document_ids:
        ctx["document_ids"] = list(document_ids)

    evidence = json.dumps(diff, ensure_ascii=False)[:500]
    entry = append_decision(
        ctx,
        agent="user",
        decision="plan_feedback",
        target="plan_steps",
        reason=_diff_reason(diff),
        evidence=evidence,
        fingerprint=plan_fingerprint,
        overridden=bool(diff.get("changed")),
    )

    profile_updated = False
    if apply_to_profile and diff.get("changed"):
        from agent.user_profile import (
            apply_plan_feedback_to_profile,
            load_profile,
            merge_profile,
            save_profile,
        )

        base = merge_profile(load_profile(), profile)
        updated = apply_plan_feedback_to_profile(base, diff)
        if updated.get("optimize_plan_from_usage"):
            save_profile(updated)
            profile_updated = True

    history_feedback = {
        "changed": diff["changed"],
        "reordered": diff["reordered"],
        "toggles": diff["toggles"],
        "plan_fingerprint": plan_fingerprint,
    }
    decision_summary = summarize_for_history(ctx.get("decision_log") or [])

    return {
        "recorded": True,
        "profile_updated": profile_updated,
        "diff": diff,
        "decision_log_entry": entry,
        "history": {
            "plan_feedback": history_feedback,
            "decision_summary": decision_summary,
        },
    }
