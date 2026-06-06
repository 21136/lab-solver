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
