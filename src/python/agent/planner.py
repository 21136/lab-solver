"""
Planner: report / multi-doc → module step list (Phase 2a.2).

Supports sections_config, clarifications, planner_input_text; no DeepPipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from agent.decision_log import append_decision
from agent.prompt_budget import fit_budget
from agent.prompts import PROMPTS, render_plan_prompt
from agent.user_profile import normalize_profile
from agent.types import (
    AGENT_SCHEMA_VERSION,
    DecisionLogEntry,
    PlanResult,
    PlanStep,
)

MAX_CONSECUTIVE_FAILURES = 3
MAX_REPLAN_ROUNDS = 1
from config import _any_runtime_available, _runtime_available_for
from log_util import loge, logi
from modules.lab_parse import parse_lab_json

from agent.registry import planner_module_catalog
from modules.solve_pipeline import _CODE_KEYWORDS
from modules.user_constraints import normalize_user_constraints, should_skip_validation

# Phase 1.3: planner may only emit steps the legacy pipeline can approximate.
_THIN_PLANNER_MODULES = planner_module_catalog()

_DEFAULT_PROFILE = normalize_profile(None)


def parse_plan_json(text: str) -> dict[str, Any]:
    """Extract planner JSON from LLM output (reuses lab JSON repair)."""
    raw = parse_lab_json(text)
    if raw.get("steps") is not None:
        return raw
    # Fallback: top-level array mistaken as root
    m = re.search(r"\{[\s\S]*\"steps\"[\s\S]*\}", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return raw


def compute_plan_fingerprint(
    report_text: str,
    steps: list[PlanStep],
    *,
    document_ids: Optional[list[str]] = None,
    sections_config: Optional[dict] = None,
    split_idx: Optional[int] = None,
) -> str:
    """Stable fingerprint; run rejects mismatch with 409 stale_plan."""
    canonical_steps = [
        {
            "module": s.get("module"),
            "params": s.get("params") or {},
            "default_checked": s.get("default_checked", True),
        }
        for s in steps
    ]
    payload = {
        "schema": AGENT_SCHEMA_VERSION,
        "report_len": len(report_text),
        "steps": canonical_steps,
        "document_ids": sorted(document_ids or []),
        "sections_config": sections_config or {},
        "split_idx": split_idx,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest[:32]}"


def _normalize_step(step: dict, profile: dict, index: int) -> Optional[PlanStep]:
    module = (step.get("module") or step.get("module_id") or "").strip()
    if not module:
        return None
    if module not in _THIN_PLANNER_MODULES:
        logi("planner", f"跳过未知或非首期模块 step[{index}]={module}")
        return None

    params = dict(step.get("params") or {})
    if module == "solve_lab" and "language" not in params:
        params.setdefault("language", profile.get("default_language", "java"))

    confidence = (step.get("confidence") or "high").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    source = step.get("source") or "report"
    default_checked = step.get("default_checked", confidence == "high")

    return PlanStep(
        module=module,
        params=params,
        reason=(step.get("reason") or "").strip() or f"计划步骤：{module}",
        evidence=(step.get("evidence") or "").strip(),
        source=source,
        confidence=confidence,
        default_checked=bool(default_checked),
    )


def normalize_plan(raw: dict, profile: dict) -> tuple[list[PlanStep], list[dict]]:
    steps_in = raw.get("steps") or []
    if not isinstance(steps_in, list):
        steps_in = []

    steps: list[PlanStep] = []
    for i, item in enumerate(steps_in):
        if not isinstance(item, dict):
            continue
        norm = _normalize_step(item, profile, i)
        if norm:
            steps.append(norm)

    clarifications = _normalize_clarifications(raw.get("clarifications") or [])
    if not clarifications:
        clarifications = _clarifications_from_steps(steps)

    return steps, clarifications


def report_needs_code(report_text: str) -> bool:
    """True when report text suggests programming / runnable code."""
    text = (report_text or "").strip()
    if not text:
        return False
    text_lower = text.lower()
    return any(k in text or k in text_lower for k in _CODE_KEYWORDS)


def adjust_plan_for_skip_validation(
    steps: list[PlanStep],
    constraints: list[str] | None,
) -> list[PlanStep]:
    """User chose skip_validation — drop standalone run_code steps."""
    if not should_skip_validation(constraints or []):
        return steps
    return [s for s in steps if (s.get("module") or "") != "run_code"]


def adjust_plan_theory_only(steps: list[PlanStep], report_text: str) -> list[PlanStep]:
    """Pure theory reports should not include run_code / render_uml."""
    if report_needs_code(report_text):
        return steps
    drop = {"run_code", "fix_code"}
    out: list[PlanStep] = []
    for step in steps:
        mod = step.get("module") or ""
        if mod in drop or mod == "render_uml":
            continue
        out.append(step)
    return out


def enrich_low_confidence_steps(steps: list[PlanStep]) -> list[PlanStep]:
    """Low-confidence steps default off with an explicit reason for Step2 UI."""
    out: list[PlanStep] = []
    for step in steps:
        s = dict(step)
        if (s.get("confidence") or "").lower() == "low":
            reason = (s.get("reason") or "").strip()
            hint = "置信度较低，请确认是否执行"
            if reason and hint not in reason:
                s["reason"] = f"{reason}（{hint}）"
            elif not reason:
                s["reason"] = f"计划步骤：{s.get('module')}（{hint}）"
            s["default_checked"] = False
        out.append(s)  # type: ignore[arg-type]
    return out


def adjust_plan_v4_aware(
    steps: list[PlanStep],
    settings: dict | None,
    report_text: str,
    constraints: list[str] | None = None,
) -> list[PlanStep]:
    """Post-process planner output for V4 pipeline + user constraints (AO-4)."""
    steps = adjust_plan_for_v4_pipeline(steps, settings)
    steps = adjust_plan_for_skip_validation(steps, constraints)
    steps = adjust_plan_theory_only(steps, report_text)
    steps = enrich_low_confidence_steps(steps)
    return steps


def adjust_plan_for_v4_pipeline(
    steps: list[PlanStep],
    settings: dict | None = None,
) -> list[PlanStep]:
    """V4 solve_lab already runs sandbox validation — demote redundant run_code steps."""
    from modules.solve_pipeline import should_use_pipeline

    if not should_use_pipeline(settings):
        return steps
    if not any(s.get("module") == "solve_lab" for s in steps):
        return steps

    note = "solve_lab（V4）已含内化验证"
    out: list[PlanStep] = []
    for step in steps:
        if step.get("module") != "run_code":
            out.append(step)
            continue
        adjusted = dict(step)
        adjusted["default_checked"] = False
        reason = (adjusted.get("reason") or "").strip()
        if note not in reason:
            adjusted["reason"] = f"{reason}（{note}，此步可选）" if reason else f"{note}，此步可选"
        out.append(adjusted)
    return out


def _normalize_clarifications(items: list) -> list[dict]:
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        q = (item.get("question") or "").strip()
        if not q:
            continue
        options = item.get("options") or []
        if not isinstance(options, list):
            options = []
        out.append(
            {
                "id": item.get("id") or f"q{i + 1}",
                "question": q,
                "options": options,
                "default": item.get("default") or "",
                "default_reason": item.get("default_reason") or "",
            }
        )
    return out


def _clarifications_from_steps(steps: list[PlanStep]) -> list[dict]:
    """Generate clarification cards for medium/low confidence steps."""
    by_topic: dict[str, list[str]] = {}
    low_reasons: dict[str, str] = {}
    for step in steps:
        conf = (step.get("confidence") or "high").lower()
        if conf not in ("medium", "low"):
            continue
        mod = step.get("module") or ""
        reason = (step.get("reason") or "").strip()
        if mod == "render_uml":
            by_topic.setdefault("uml", []).append(mod)
            if reason:
                low_reasons["uml"] = reason
        elif mod == "run_code":
            by_topic.setdefault("code", []).append(mod)
            if reason:
                low_reasons["code"] = reason

    clarifications: list[dict] = []
    if by_topic.get("uml"):
        clarifications.append(
            {
                "id": "q_uml",
                "question": "是否需要生成 UML 设计图？",
                "options": [
                    {"label": "需要 UML", "affects": ["render_uml"]},
                    {"label": "不需要", "affects": []},
                ],
                "default": "需要 UML",
                "default_reason": low_reasons.get("uml")
                or "报告或步骤置信度为 medium/low",
            }
        )
    if by_topic.get("code"):
        clarifications.append(
            {
                "id": "q_code",
                "question": "是否需要单独运行/复验代码？",
                "options": [
                    {"label": "需要复验", "affects": ["run_code"]},
                    {"label": "不需要", "affects": []},
                ],
                "default": "不需要",
                "default_reason": low_reasons.get("code")
                or "V4 solve_lab 已含内化验证",
            }
        )
    return clarifications


def _infer_diagram_needs(report_text: str) -> dict:
    try:
        from uml_render import detect_diagram_needs
        return detect_diagram_needs(report_text)
    except ImportError:
        return {"needs_uml": False, "needs_dfd": False, "kinds": [], "evidence": ""}


def _render_uml_reason_evidence(diagram_needs: dict) -> tuple[str, str]:
    kinds = diagram_needs.get("kinds") or []
    evidence = (diagram_needs.get("evidence") or "").strip()
    if kinds:
        combo = "、".join(kinds)
        reason = f"报告需要 {combo}（默认每张图独立，最多 12 张）"
    elif diagram_needs.get("needs_dfd"):
        reason = "报告需要标准数据流图 DFD（分层多张独立）"
    else:
        reason = "报告或设置需要 UML 设计图"
    return reason, evidence


def _fallback_plan(
    report_text: str,
    profile: dict,
    needs_uml: bool,
    diagram_needs: dict | None = None,
) -> list[PlanStep]:
    """Minimal plan when LLM JSON is empty or unusable.

    When the target language runtime is not available, run_code
    steps are still included but default_checked=False with a clear reason.
    """
    steps: list[PlanStep] = []
    dneeds = diagram_needs if diagram_needs is not None else _infer_diagram_needs(report_text)
    any_rt = _any_runtime_available()
    target_lang = profile.get("default_language", "java")
    lang_available = _runtime_available_for(target_lang) if any_rt else False

    is_lab = any(
        k in report_text
        for k in ("实验步骤", "实验结果", "实验总结", "三、", "四、", "五、")
    )
    if is_lab or len(report_text) > 200:
        steps.append(
            PlanStep(
                module="solve_lab",
                params={
                    "language": target_lang,
                    "include_uml": needs_uml or profile.get("prefer_uml", False),
                },
                reason="报告形如实验报告，默认生成解题内容",
                evidence="",
                source="fallback",
                confidence="medium",
                default_checked=True,
            )
        )
        if re.search(r"代码|程序|编程|运行|编译", report_text):
            from modules.solve_pipeline import should_use_pipeline

            v4_pipeline = should_use_pipeline(None)
            run_reason = "报告提及程序/运行"
            run_checked = not v4_pipeline
            if v4_pipeline:
                run_reason = "报告提及程序/运行（solve_lab V4 已含内化验证，此步可选）"
            if not any_rt:
                run_reason = "报告提及程序/运行，但本地无编程环境（未安装 Python/Java/C/Node），代码仅生成不执行"
                run_checked = False
            elif not lang_available:
                run_reason = (
                    f"报告提及程序/运行，但 {target_lang} 运行时不可用，代码仅生成不执行"
                )
                run_checked = False
            steps.append(
                PlanStep(
                    module="run_code",
                    params={},
                    reason=run_reason,
                    evidence="",
                    source="fallback",
                    confidence="medium",
                    default_checked=run_checked,
                )
            )
        if re.search(r"截图|界面|运行结果", report_text):
            pass  # 运行截图已移除；结果说明由 solve_lab 文字 + 可选内化验证 stdout 覆盖
        if needs_uml or profile.get("prefer_uml") or dneeds.get("needs_uml"):
            uml_reason, uml_evidence = _render_uml_reason_evidence(dneeds)
            steps.append(
                PlanStep(
                    module="render_uml",
                    params={
                        "diagram_kinds": dneeds.get("kinds") or [],
                        "needs_dfd": bool(dneeds.get("needs_dfd")),
                    },
                    reason=uml_reason,
                    evidence=uml_evidence,
                    source="fallback",
                    confidence="low",
                    default_checked=bool(needs_uml or dneeds.get("needs_uml")),
                )
            )
        steps.append(
            PlanStep(
                module="present_deliverable",
                params={},
                reason="汇编答案交付物，在答案工作区审阅与复制",
                evidence="",
                source="fallback",
                confidence="high",
                default_checked=True,
            )
        )
    else:
        steps.append(
            PlanStep(
                module="solve_theory",
                params={"language": profile.get("default_language", "python")},
                reason="短文本/理论题默认解答",
                evidence="",
                source="fallback",
                confidence="medium",
                default_checked=True,
            )
        )
    return steps


def plan_from_report(
    report_text: str,
    *,
    settings: dict,
    profile: Optional[dict] = None,
    metadata: Optional[dict] = None,
    needs_uml: bool = False,
    diagram_needs: Optional[dict] = None,
    planner_input_text: Optional[str] = None,
    sections_config: Optional[dict] = None,
    document_ids: Optional[list[str]] = None,
    split_idx: Optional[int] = None,
    format_spec: Optional[dict] = None,
) -> PlanResult:
    """
    Generate an execution plan from a single report full_text.

    settings must include api_key, provider, model (and optional custom_url).
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
        g = norm.get("global") or {}
        if g.get("language"):
            profile_norm["default_language"] = g["language"]
        if "include_uml" in g:
            needs_uml = needs_uml or bool(g.get("include_uml"))
        if g.get("include_code") is False:
            profile_norm["include_code_in_steps"] = False

    provider = settings.get("provider", "deepseek")
    model = settings.get("model", "deepseek-chat")
    custom_url = settings.get("custom_url") or settings.get("customUrl") or ""

    from modules.solve_pipeline import should_use_pipeline

    user_constraints = normalize_user_constraints(
        (settings or {}).get("user_constraints") or (settings or {}).get("userConstraints")
    )
    v4_pipeline = should_use_pipeline(settings)

    budgeted_text = fit_budget(
        text,
        budget_tokens=2500,
        preserve_sections=["步骤", "结果", "要求"],
        section_map=(metadata or {}).get("section_map") if metadata else None,
    )
    prompt = render_plan_prompt(
        report_text=budgeted_text,
        profile=profile_norm,
        metadata=metadata or {},
        module_catalog=sorted(_THIN_PLANNER_MODULES),
        sections_block=sections_block,
        format_spec=format_spec,
        v4_pipeline=v4_pipeline,
        skip_validation=should_skip_validation(user_constraints),
    )
    prompt_version = PROMPTS["planner"].version

    from llm_client import chat

    try:
        chat_result = chat(
            api_key=api_key,
            provider=provider,
            model=model,
            prompt=prompt,
            custom_url=custom_url,
            max_tokens=4000,
            phase="planner",
        )
        raw = parse_plan_json(chat_result.get("content") or "")
        steps, clarifications = normalize_plan(raw, profile_norm)
        dneeds = diagram_needs if diagram_needs is not None else _infer_diagram_needs(text)
        if not steps:
            steps = _fallback_plan(text, profile_norm, needs_uml, dneeds)
            logi("planner", "LLM 计划为空，使用 fallback 步骤")
    except Exception as e:
        loge("planner", str(e))
        dneeds = diagram_needs if diagram_needs is not None else _infer_diagram_needs(text)
        steps = _fallback_plan(text, profile_norm, needs_uml, dneeds)
        clarifications = []

    from agent.user_profile import apply_behavior_to_steps

    steps = apply_behavior_to_steps(steps, profile_norm)
    steps = adjust_plan_v4_aware(steps, settings, text, user_constraints)

    doc_ids = document_ids
    if doc_ids is None and metadata:
        raw_ids = metadata.get("document_ids")
        if isinstance(raw_ids, list):
            doc_ids = raw_ids
    fingerprint = compute_plan_fingerprint(
        text,
        steps,
        document_ids=doc_ids,
        sections_config=sections_config,
        split_idx=split_idx,
    )
    decision: DecisionLogEntry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "planner",
        "decision": "plan_generated",
        "target": "plan",
        "reason": f"{len(steps)} steps, modules={[s['module'] for s in steps]}",
        "evidence": "",
        "fingerprint": fingerprint,
    }

    logi(
        "planner",
        f"steps={len(steps)} fingerprint={fingerprint[:20]}… prompt={prompt_version}",
    )

    return PlanResult(
        steps=steps,
        plan_fingerprint=fingerprint,
        clarifications=clarifications,
        prompt_version=prompt_version,
        decision_log=[decision],
    )


def make_agent_context(
    report_text: str,
    settings: dict,
    *,
    profile: Optional[dict] = None,
    metadata: Optional[dict] = None,
    question: Optional[dict] = None,
    plan: Optional[PlanResult] = None,
    format_spec: Optional[dict] = None,
) -> dict:
    """Build a minimal AgentContext dict for Phase 2a handoff."""
    ctx: dict[str, Any] = {
        "schema_version": AGENT_SCHEMA_VERSION,
        "report_text": report_text,
        "metadata": metadata or {},
        "question": question or {},
        "settings": settings,
        "user_profile": normalize_profile(profile),
        "prompt_versions": {"planner": PROMPTS["planner"].version},
        "module_results": {},
        "dirty_modules": [],
        "dirty_fields": {},
        "fill_sections": [],
        "decision_log": list((plan or {}).get("decision_log") or []),
        "consecutive_failures": 0,
    }
    if plan:
        ctx["plan"] = plan
    if format_spec:
        ctx["format_spec"] = format_spec
    return ctx


def replan_incremental(
    ctx: dict,
    replan_context: dict,
    *,
    emit=None,
) -> PlanResult:
    """
    Replace only steps not yet completed after consecutive module failures.
    max_replan_rounds=1 per run.
    """
    rounds = int(ctx.get("replan_rounds") or 0)
    if rounds >= MAX_REPLAN_ROUNDS:
        append_decision(
            ctx,
            agent="planner",
            decision="replan_skipped",
            target="plan",
            reason=f"已达 max_replan_rounds={MAX_REPLAN_ROUNDS}",
            emit=emit,
        )
        return ctx.get("plan") or PlanResult(steps=[], plan_fingerprint="")

    failed = replan_context.get("failed_module") or ""
    error_summary = (replan_context.get("error_summary") or "")[:200]
    completed = set(replan_context.get("completed_modules") or [])

    old_steps = list(
        (ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or [])
    )
    new_steps: list[PlanStep] = []
    for step in old_steps:
        mod = step.get("module") or ""
        if mod in completed:
            new_steps.append(step)
            continue
        if mod == failed:
            continue
        new_steps.append(step)

    if failed == "run_code" and "fix_code" not in {s.get("module") for s in new_steps}:
        new_steps.append(
            PlanStep(
                module="fix_code",
                params={},
                reason=f"run_code 连续失败，插入修代码步骤: {error_summary}",
                evidence="",
                source="replan",
                confidence="medium",
                default_checked=True,
            )
        )
    elif failed == "solve_lab" and not any(s.get("module") == "solve_lab" for s in new_steps):
        profile = ctx.get("user_profile") or _DEFAULT_PROFILE
        new_steps.append(
            PlanStep(
                module="solve_lab",
                params={"language": profile.get("default_language", "java")},
                reason=f"solve_lab 失败，重试: {error_summary}",
                evidence="",
                source="replan",
                confidence="low",
                default_checked=True,
            )
        )

    if not new_steps:
        new_steps = _fallback_plan(
            ctx.get("planner_input_text") or ctx.get("report_text") or "",
            ctx.get("user_profile") or _DEFAULT_PROFILE,
            False,
        )

    text = ctx.get("planner_input_text") or ctx.get("report_text") or ""
    doc_ids = ctx.get("document_ids") or []
    fingerprint = compute_plan_fingerprint(
        text,
        new_steps,
        document_ids=doc_ids,
        sections_config=ctx.get("sections_config"),
        split_idx=ctx.get("split_idx"),
    )
    plan: PlanResult = {
        "steps": new_steps,
        "plan_fingerprint": fingerprint,
        "clarifications": [],
        "prompt_version": PROMPTS["planner"].version,
        "decision_log": list(ctx.get("decision_log") or []),
    }
    ctx["plan"] = plan
    ctx["confirmed_steps"] = new_steps
    ctx["replan_rounds"] = rounds + 1
    ctx["consecutive_failures"] = 0

    append_decision(
        ctx,
        agent="planner",
        decision="replan_incremental",
        target=failed or "plan",
        reason=f"替换未执行步骤，剩余 {len(new_steps)} 步",
        fingerprint=fingerprint,
        emit=emit,
    )
    return plan


def replan_with_answers(
    ctx: dict,
    clarification_answers: dict[str, str],
    *,
    settings: Optional[dict] = None,
) -> PlanResult:
    """
    Lightweight replan after user answers clarification cards.
    Adjusts affected steps/params without re-reading full report via LLM.
    """
    plan = ctx.get("plan") or {}
    steps: list[PlanStep] = list(plan.get("steps") or ctx.get("confirmed_steps") or [])
    answers = clarification_answers or {}
    profile = ctx.get("user_profile") or _DEFAULT_PROFILE

    def _answer_label(qid: str, default: str = "") -> str:
        val = answers.get(qid) or answers.get(qid.replace("q_", "")) or default
        return str(val).strip()

    new_steps: list[PlanStep] = []
    for step in steps:
        mod = step.get("module") or ""
        params = dict(step.get("params") or {})
        keep = True

        if mod == "render_uml":
            choice = _answer_label("q_uml", "")
            if "不需要" in choice:
                keep = False
            elif "需要" in choice:
                params["include_uml"] = True

        if keep:
            new_steps.append(
                PlanStep(
                    module=mod,
                    params=params,
                    reason=step.get("reason") or "",
                    evidence=step.get("evidence") or "",
                    source=step.get("source") or "clarify",
                    confidence=step.get("confidence") or "high",
                    default_checked=bool(step.get("default_checked", True)),
                )
            )

    if not new_steps:
        new_steps = _fallback_plan(ctx.get("planner_input_text") or ctx.get("report_text") or "", profile, False)

    clarifications = _clarifications_from_steps(new_steps)
    text = ctx.get("planner_input_text") or ctx.get("report_text") or ""
    fingerprint = compute_plan_fingerprint(
        text,
        new_steps,
        document_ids=ctx.get("document_ids"),
        sections_config=ctx.get("sections_config"),
        split_idx=ctx.get("split_idx"),
    )
    result: PlanResult = {
        "steps": new_steps,
        "plan_fingerprint": fingerprint,
        "clarifications": clarifications,
        "prompt_version": PROMPTS["planner"].version,
        "decision_log": list(ctx.get("decision_log") or []),
    }
    ctx["plan"] = result
    ctx["confirmed_steps"] = new_steps

    append_decision(
        ctx,
        agent="planner",
        decision="replan_clarify",
        target="plan",
        reason=f"clarify answers={list(answers.keys())}",
        fingerprint=fingerprint,
    )
    return result


def verify_plan_fingerprint(
    ctx: dict,
    plan_fingerprint: str,
    steps: list[PlanStep],
) -> tuple[bool, str]:
    """Recompute fingerprint from ctx; return (ok, expected)."""
    fp_text = ctx.get("planner_input_text") or ctx.get("report_text") or ""
    expected = compute_plan_fingerprint(
        fp_text,
        steps,
        document_ids=ctx.get("document_ids"),
        sections_config=ctx.get("sections_config"),
        split_idx=ctx.get("split_idx"),
    )
    return (plan_fingerprint == expected, expected)
