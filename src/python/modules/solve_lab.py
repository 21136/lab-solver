"""Lab report solve entry — v1 single-shot or v4 pipeline."""

from modules.lab_parse import complete_lab_parsed, parse_lab_json

__all__ = ["solve_lab", "parse_lab_json", "complete_lab_parsed"]


def solve_lab(
    api_key,
    provider,
    model,
    question,
    custom_url="",
    include_uml=False,
    format_spec=None,
    *,
    settings=None,
    user_constraints=None,
    on_phase=None,
    on_jar_consent=None,
    approved_jar_ids=None,
    tier="standard",
):
    """Solve lab report; dispatches to V4 pipeline when enabled."""
    settings_dict = dict(settings or {})
    settings_dict.setdefault("api_key", api_key)
    settings_dict.setdefault("provider", provider)
    settings_dict.setdefault("model", model)
    settings_dict.setdefault("custom_url", custom_url)

    from modules.solve_pipeline import run_solve_pipeline, should_use_pipeline

    if should_use_pipeline(settings_dict):
        return run_solve_pipeline(
            settings_dict,
            question,
            include_uml=include_uml,
            format_spec=format_spec,
            tier=tier,
            user_constraints=user_constraints,
            on_phase=on_phase,
            on_jar_consent=on_jar_consent,
            approved_jar_ids=approved_jar_ids,
        )

    from log_util import logi

    logi(
        "solve_lab",
        "DEPRECATED: solve_pipeline v1 (LAB_REPORT_USER 单轮) — 默认已 v4；"
        "请移除 solvePipelineVersion=v1 或 SOLVE_PIPELINE=v1",
    )
    from llm_client import call_ai

    return call_ai(
        api_key,
        provider,
        model,
        question,
        custom_url=custom_url,
        include_uml=include_uml,
        format_spec=format_spec,
    )
