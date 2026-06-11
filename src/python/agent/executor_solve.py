"""Solve-related module runners (solve_lab, solve_theory, solve_code_cloze)."""

from __future__ import annotations

from agent.executor_common import _fail_result, _ok_result
from agent.run_control import emit_event
from agent.types import ModuleResult
from modules.solve_lab import solve_lab


def _run_solve_lab(ctx: dict, params: dict) -> ModuleResult:
    settings = ctx["settings"]
    question = dict(ctx.get("question") or {})
    question["type"] = "lab_report"
    # Use planner_input_text when available — it includes assignment + fill_target
    # for combined documents, while report_text is only the template half.
    full_text = ctx.get("planner_input_text") or ctx.get("report_text") or question.get("full_text") or ""
    question["full_text"] = full_text
    lang = params.get("language") or (ctx.get("user_profile") or {}).get("default_language", "java")
    question["preferred_lang"] = lang
    include_uml = bool(params.get("include_uml"))
    from agent.skill_store import match_skills

    matched = match_skills(
        {"language": lang, "full_text": full_text, "report_text": full_text},
        agent_ctx=ctx,
        audit_source="solve_lab",
    )
    fired = ctx.setdefault("skills_fired", [])
    for skill in matched:
        sid = skill.get("id")
        if sid and sid not in fired:
            fired.append(sid)
    fmt_spec = ctx.get("format_spec")
    if fmt_spec:
        from agent.template_analyzer import to_format_constraints

        question["format_constraints"] = to_format_constraints(fmt_spec)
    try:
        from modules.user_constraints import constraints_from_ctx

        user_constraints = constraints_from_ctx(ctx)
        if user_constraints:
            ctx["user_constraints"] = user_constraints

        def _on_pipeline_phase(event: dict) -> None:
            ctx.setdefault("pipeline_phases", []).append(event)
            run_id = ctx.get("run_id") or ""
            if run_id:
                emit_event(
                    run_id,
                    {"type": "pipeline_phase", "module": "solve_lab", **event},
                )

        approved_jar_ids = list(ctx.get("approved_jar_ids") or [])
        run_id = ctx.get("run_id") or ""
        on_jar_consent = None
        constraints = user_constraints or []
        if run_id and "allow_curated_jars" in constraints:
            from agent.run_control import wait_for_jar_consent

            on_jar_consent = lambda missing: wait_for_jar_consent(run_id, missing)

        from modules.solve_pipeline import resolve_solve_quality_tier

        tier = resolve_solve_quality_tier(settings, ctx)
        result = solve_lab(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
            include_uml=include_uml,
            format_spec=fmt_spec,
            settings=settings,
            user_constraints=user_constraints,
            on_phase=_on_pipeline_phase,
            on_jar_consent=on_jar_consent,
            approved_jar_ids=approved_jar_ids or None,
            tier=tier,
        )
        if result.get("solve_session"):
            ctx["solve_session"] = result["solve_session"]
        if result.get("pipeline_meta"):
            ctx["pipeline_meta"] = result["pipeline_meta"]
            from agent.prompts import merge_prompt_versions

            merge_prompt_versions(
                ctx, (result["pipeline_meta"] or {}).get("prompt_versions")
            )
        return _ok_result("solve_lab", result, params)
    except Exception as e:
        return _fail_result("solve_lab", str(e), params)


def _solve_input_text(ctx: dict, params: dict) -> str:
    """Segment focus + full paper context for mixed assignments (O10/R8)."""
    segment = (params.get("segment_text") or "").strip()
    full = (ctx.get("planner_input_text") or ctx.get("report_text") or "").strip()
    if segment and full and segment != full and params.get("include_full_context", True):
        return f"【关联题面】\n{full}\n\n【本段作答】\n{segment}"
    return segment or full


def _record_segment_solve_result(
    ctx: dict, module: str, params: dict, result: dict
) -> None:
    seg_id = params.get("segment_id")
    if seg_id is None:
        return
    ctx.setdefault("segment_solve_results", []).append(
        {
            "segment_id": seg_id,
            "module": module,
            "title": params.get("segment_title") or "",
            "type": "code_cloze" if module == "solve_code_cloze" else "theory",
            "data": result,
        }
    )


def _run_solve_short_answer(ctx: dict, params: dict) -> ModuleResult:
    from llm_client import call_ai

    settings = ctx["settings"]
    txt = _solve_input_text(ctx, params)
    question = {
        "type": "short_answer",
        "content": txt,
        "full_text": txt,
    }
    try:
        from agent.prompts import record_prompt_version

        record_prompt_version(ctx, "short_answer")
        result = call_ai(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or "",
        )
        result["type"] = "short_answer"
        out = _ok_result("solve_short_answer", result, params)
        return out
    except Exception as e:
        return _fail_result("solve_short_answer", str(e), params)


def _run_solve_theory(ctx: dict, params: dict) -> ModuleResult:
    from llm_client import call_ai

    settings = ctx["settings"]
    txt = _solve_input_text(ctx, params)
    question = {
        "type": "theory",
        "content": txt,
        "full_text": txt,
        "preferred_lang": params.get("language", "python"),
    }
    try:
        from agent.prompts import record_prompt_version

        record_prompt_version(ctx, "theory")
        result = call_ai(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or "",
        )
        out = _ok_result("solve_theory", result, params)
        if out.get("ok"):
            _record_segment_solve_result(ctx, "solve_theory", params, result)
        return out
    except Exception as e:
        return _fail_result("solve_theory", str(e), params)


def _run_solve_code_cloze(ctx: dict, params: dict) -> ModuleResult:
    from llm_client import call_ai

    settings = ctx["settings"]
    txt = _solve_input_text(ctx, params)
    qmeta = dict((ctx.get("question") or {}).get("metadata") or {})
    seg_meta = {}
    seg_id = params.get("segment_id")
    if seg_id is not None:
        for q in (ctx.get("metadata") or {}).get("assignment_questions") or []:
            if q.get("id") == seg_id:
                seg_meta = q.get("metadata") or {}
                break
    if seg_meta.get("code_cloze"):
        qmeta["code_cloze"] = seg_meta["code_cloze"]
    elif (ctx.get("metadata") or {}).get("code_cloze"):
        qmeta["code_cloze"] = (ctx.get("metadata") or {}).get("code_cloze")
    question = {
        "type": "code_cloze",
        "content": txt,
        "full_text": txt,
        "metadata": qmeta,
        "preferred_lang": params.get("language") or "",
    }
    try:
        from agent.prompts import record_prompt_version

        record_prompt_version(ctx, "code_cloze")
        result = call_ai(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or "",
        )
        result["type"] = "code_cloze"
        out = _ok_result("solve_code_cloze", result, params)
        if out.get("ok"):
            _record_segment_solve_result(ctx, "solve_code_cloze", params, result)
        return out
    except Exception as e:
        try:
            # Fallback: degrade to existing theory path to keep run stable.
            theory_q = {
                "type": "theory",
                "content": txt,
                "full_text": txt,
                "preferred_lang": params.get("language", "java"),
            }
            fallback = call_ai(
                settings["api_key"],
                settings.get("provider", "deepseek"),
                settings.get("model", "deepseek-chat"),
                theory_q,
                custom_url=settings.get("custom_url") or "",
            )
            fallback["type"] = "theory"
            out = _ok_result("solve_code_cloze", fallback, params)
            if out.get("ok"):
                _record_segment_solve_result(ctx, "solve_code_cloze", params, fallback)
            return out
        except Exception:
            return _fail_result("solve_code_cloze", str(e), params)
