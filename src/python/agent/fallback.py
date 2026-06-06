"""
Agent failure fallback to legacy solve_lab (/api/solve equivalent).
"""

from __future__ import annotations

from typing import Any

from agent.decision_log import append_decision
from log_util import loge, logi
from modules.solve_lab import solve_lab


def fallback_to_solve(ctx: dict[str, Any], *, emit=None) -> dict[str, Any]:
    """
    Run single-shot solve_lab when agent plan execution fails catastrophically.
    Returns solve result dict or raises.
    """
    settings = ctx.get("settings") or {}
    api_key = (settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未填写 API Key")

    question = dict(ctx.get("question") or {})
    question.setdefault("type", "lab_report")
    question["full_text"] = ctx.get("planner_input_text") or ctx.get("report_text") or question.get("full_text") or ""
    profile = ctx.get("user_profile") or {}
    include_uml = bool(profile.get("prefer_uml"))
    for step in (ctx.get("confirmed_steps") or ctx.get("plan", {}).get("steps") or []):
        if step.get("module") == "solve_lab":
            include_uml = bool((step.get("params") or {}).get("include_uml", include_uml))
            break

    append_decision(
        ctx,
        agent="executor",
        decision="fallback_solve",
        target="solve_lab",
        reason="Agent 执行失败，降级为 /api/solve",
        emit=emit,
    )
    logi("fallback", "降级 /api/solve 路径")

    try:
        result = solve_lab(
            api_key,
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
            include_uml=include_uml,
            format_spec=ctx.get("format_spec"),
        )
        ctx.setdefault("module_results", {})["solve_lab"] = {
            "ok": True,
            "data": result,
            "logs": ["fallback:solve_lab"],
            "fingerprint": "fallback",
            "cacheable": False,
        }
        return result
    except Exception as e:
        loge("fallback", str(e))
        raise


# TEMP cleanup policy (Phase 2a.1): document_store keeps parsed files for TTL;
# run-scoped artifacts use run_{id}_ prefix and are removed in executor finally.
