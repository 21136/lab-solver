"""
Deep mode: merged understand + plan (Phase 2b B1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from agent.decision_log import append_decision
from agent.planner import compute_plan_fingerprint, normalize_plan
from agent.user_profile import normalize_profile
from agent.template_analyzer import to_format_constraints
from agent.prompt_budget import fit_budget
from agent.prompts import PROMPTS
from agent.types import DecisionLogEntry, PlanResult
from llm_client import chat, select_model_for_run_mode
from log_util import loge, logi
from modules.lab_parse import parse_lab_json


def understand_and_plan(
    report_text: str,
    *,
    settings: dict,
    profile: Optional[dict] = None,
    metadata: Optional[dict] = None,
    planner_input_text: Optional[str] = None,
    sections_config: Optional[dict] = None,
    document_ids: Optional[list[str]] = None,
    split_idx: Optional[int] = None,
    assignment_text: str = "",
    format_spec: Optional[dict] = None,
) -> tuple[dict[str, Any], PlanResult]:
    """
    Single LLM call → understand dict + PlanResult.
    """
    api_key = (settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未填写 API Key")

    profile_norm = normalize_profile(profile)
    text = (planner_input_text or report_text or "").strip()
    if not text:
        raise ValueError("报告正文为空")

    sections_block = ""
    if sections_config:
        from agent.sections_config import normalize, sections_summary_for_prompt

        norm = normalize(sections_config)
        sections_block = sections_summary_for_prompt(norm)

    assign = (assignment_text or text)[:3000]
    budgeted = fit_budget(
        text,
        budget_tokens=2800,
        preserve_sections=["步骤", "结果", "要求"],
        section_map=(metadata or {}).get("section_map") if metadata else None,
    )

    from agent.planner import _THIN_PLANNER_MODULES

    fmt_block = to_format_constraints(format_spec) or "（无）"
    prompt = PROMPTS["understand_plan"].render(
        report_text=budgeted,
        assignment_excerpt=assign[:2500],
        module_catalog=", ".join(sorted(_THIN_PLANNER_MODULES)),
        default_language=profile_norm.get("default_language", "java"),
        screenshot_style=profile_norm.get("screenshot_style", "ide"),
        prefer_uml="是" if profile_norm.get("prefer_uml") else "否",
        sections_block=sections_block or "（无）",
        format_block=fmt_block,
    )

    model = select_model_for_run_mode(settings, "deep")
    provider = settings.get("provider", "deepseek")
    custom_url = settings.get("custom_url") or settings.get("customUrl") or ""

    try:
        chat_result = chat(
            api_key,
            provider,
            model,
            prompt,
            custom_url=custom_url,
            max_tokens=4500,
            phase="understand_plan",
        )
        raw = parse_lab_json(chat_result.get("content") or "")
        understand = raw.get("understand") or {}
        if isinstance(understand, str):
            understand = {"summary": understand}
        plan_raw = raw.get("plan") or raw
        if isinstance(plan_raw, dict) and "steps" not in plan_raw and raw.get("steps"):
            plan_raw = {"steps": raw.get("steps"), "clarifications": raw.get("clarifications")}
        steps, clarifications = normalize_plan(plan_raw if isinstance(plan_raw, dict) else raw, profile_norm)
        reasoning = chat_result.get("reasoning_content") or ""
    except Exception as e:
        loge("understand_plan", str(e))
        from agent.planner import _fallback_plan, plan_from_report

        fallback = plan_from_report(
            report_text,
            settings=settings,
            profile=profile,
            metadata=metadata,
            planner_input_text=planner_input_text,
            sections_config=sections_config,
            document_ids=document_ids,
            split_idx=split_idx,
        )
        understand = {
            "summary": "理解阶段失败，已回退标准计划",
            "grading_points": [],
            "degraded": True,
        }
        steps = fallback.get("steps") or []
        clarifications = fallback.get("clarifications") or []
        reasoning = ""

    if not steps:
        from agent.planner import _fallback_plan

        steps = _fallback_plan(text, profile_norm, False)

    fingerprint = compute_plan_fingerprint(
        text,
        steps,
        document_ids=document_ids,
        sections_config=sections_config,
        split_idx=split_idx,
    )
    decision: DecisionLogEntry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "understand_plan",
        "decision": "deep_plan_generated",
        "target": "plan",
        "reason": f"{len(steps)} steps",
        "fingerprint": fingerprint,
    }
    logi("understand_plan", f"steps={len(steps)} fp={fingerprint[:16]}")

    plan: PlanResult = {
        "steps": steps,
        "plan_fingerprint": fingerprint,
        "clarifications": clarifications,
        "prompt_version": PROMPTS["understand_plan"].version,
        "decision_log": [decision],
    }
    understand["reasoning_excerpt"] = (reasoning or "")[:2000]
    return understand, plan
