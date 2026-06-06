"""LLM model catalog, deprecation aliases, and API request resolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Catalog version — bump when presets/aliases change (frontend may refetch).
MODEL_CATALOG_VERSION = 1

# saved model id → api model + thinking mode
_DEPRECATED_ALIASES: dict[str, dict[str, str]] = {
    "deepseek-chat": {"api_model": "deepseek-v4-flash", "thinking": "disabled"},
    "deepseek-reasoner": {"api_model": "deepseek-v4-flash", "thinking": "enabled"},
}

# Provider presets shown in settings UI (single source of truth).
_PROVIDER_MODELS: dict[str, list[dict[str, Any]]] = {
    "deepseek": [
        {
            "id": "deepseek-v4-flash",
            "label": "deepseek-v4-flash（推荐）",
            "default": True,
            "supports_thinking": True,
        },
        {
            "id": "deepseek-v4-pro",
            "label": "deepseek-v4-pro（高质量）",
            "supports_thinking": True,
        },
    ],
    "agnes": [
        {
            "id": "agnes-2.0-flash",
            "label": "agnes-2.0-flash",
            "default": True,
        },
    ],
    "openai": [
        {"id": "gpt-4o", "label": "gpt-4o", "default": True},
        {"id": "gpt-4o-mini", "label": "gpt-4o-mini"},
        {"id": "gpt-4-turbo", "label": "gpt-4-turbo"},
    ],
    "claude": [
        {"id": "claude-3-5-sonnet-20241022", "label": "claude-3-5-sonnet-20241022", "default": True},
        {"id": "claude-3-haiku-20240307", "label": "claude-3-haiku-20240307"},
    ],
    "zhipu": [
        {"id": "glm-4-flash", "label": "glm-4-flash", "default": True},
        {"id": "glm-4", "label": "glm-4"},
    ],
    "custom": [
        {"id": "custom-model", "label": "custom-model", "default": True, "custom": True},
    ],
}

_DEFAULT_MODEL: dict[str, str] = {
    provider: next(m["id"] for m in models if m.get("default"))
    for provider, models in _PROVIDER_MODELS.items()
}


def get_model_catalog() -> dict[str, Any]:
    return {
        "catalog_version": MODEL_CATALOG_VERSION,
        "providers": deepcopy(_PROVIDER_MODELS),
        "defaults": dict(_DEFAULT_MODEL),
        "deprecated_aliases": dict(_DEPRECATED_ALIASES),
    }


def normalize_saved_model(provider: str, model: str) -> str:
    """Map legacy/unknown saved ids to a current catalog id for persistence."""
    provider = (provider or "deepseek").strip().lower()
    model = (model or "").strip()
    if not model:
        return _DEFAULT_MODEL.get(provider, "deepseek-v4-flash")

    alias = _DEPRECATED_ALIASES.get(model)
    if alias:
        return alias["api_model"]

    known = {m["id"] for m in _PROVIDER_MODELS.get(provider, [])}
    if known and model not in known:
        if provider == "custom":
            return model or "custom-model"
        return _DEFAULT_MODEL.get(provider, model)
    return model


def select_model_for_run_mode(settings: dict, run_mode: str = "standard") -> str:
    """Return saved model id (thinking is applied at API layer via run_mode)."""
    provider = (settings.get("provider") or "deepseek").strip().lower()
    model = normalize_saved_model(provider, settings.get("model") or "")
    _ = run_mode  # thinking toggled in resolve_model_for_api
    return model


def resolve_model_for_api(
    provider: str,
    model: str,
    *,
    run_mode: str = "standard",
) -> dict[str, Any]:
    """
    Resolve UI/saved model + run_mode to API payload fields.

    Returns:
        saved_model: canonical id to store in settings
        api_model: model field sent to the provider
        payload_fields: extra JSON fields (thinking, reasoning_effort, ...)
    """
    provider = (provider or "deepseek").strip().lower()
    saved_model = normalize_saved_model(provider, model)
    run_mode = (run_mode or "standard").strip().lower()

    api_model = saved_model
    payload_fields: dict[str, Any] = {}
    thinking: str | None = None

    alias = _DEPRECATED_ALIASES.get((model or "").strip())
    if alias:
        api_model = alias["api_model"]
        thinking = alias["thinking"]
    elif provider == "deepseek" and saved_model in ("deepseek-v4-flash", "deepseek-v4-pro"):
        thinking = "enabled" if run_mode == "deep" else "disabled"

    if thinking == "enabled":
        payload_fields["thinking"] = {"type": "enabled"}
        payload_fields.setdefault("reasoning_effort", "high")
    elif thinking == "disabled":
        payload_fields["thinking"] = {"type": "disabled"}

    return {
        "saved_model": saved_model,
        "api_model": api_model,
        "payload_fields": payload_fields,
    }


def merge_openai_payload(base: dict[str, Any], payload_fields: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (payload_fields or {}).items():
        if key == "extra_body" and isinstance(value, dict):
            merged.update(value)
        else:
            merged[key] = value
    return merged
