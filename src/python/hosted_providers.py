"""Hosted LLM providers — developer-supplied keys (e.g. Agnes free tier)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from config import APP_DATA

HOSTED_PROVIDERS = frozenset({"agnes"})

_DEFAULT_MODELS = {
    "agnes": "agnes-2.0-flash",
}


def _hosted_key_path(provider: str) -> Path:
    return APP_DATA / f"hosted_{provider.strip().lower()}.key"


def is_hosted_provider(provider: str) -> bool:
    return (provider or "").strip().lower() in HOSTED_PROVIDERS


def _normalize_api_key(raw: str) -> str:
    """Strip whitespace and UTF-8 BOM (PowerShell Set-Content -Encoding utf8 adds BOM)."""
    if not raw:
        return ""
    text = raw.strip()
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff").strip()
    return text


def get_hosted_api_key(provider: str) -> str:
    provider = (provider or "").strip().lower()
    if provider not in HOSTED_PROVIDERS:
        return ""
    env_key = _normalize_api_key(os.environ.get(f"{provider.upper()}_API_KEY") or "")
    if env_key:
        return env_key
    path = _hosted_key_path(provider)
    if path.is_file():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return _normalize_api_key(raw.decode("utf-8"))
    return ""


def is_hosted_configured(provider: str) -> bool:
    return bool(get_hosted_api_key(provider)) if is_hosted_provider(provider) else False


def save_hosted_api_key(provider: str, api_key: str) -> None:
    provider = (provider or "").strip().lower()
    if provider not in HOSTED_PROVIDERS:
        raise ValueError(f"unsupported hosted provider: {provider}")
    key = _normalize_api_key(api_key or "")
    if not key:
        raise ValueError("API Key 不能为空")
    APP_DATA.mkdir(parents=True, exist_ok=True)
    path = _hosted_key_path(provider)
    path.write_bytes(key.encode("utf-8"))
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def hosted_providers_status() -> dict:
    return {
        provider: {"configured": is_hosted_configured(provider), "hosted": True}
        for provider in sorted(HOSTED_PROVIDERS)
    }


def resolve_llm_settings(data: dict) -> dict:
    provider = str(data.get("provider") or "deepseek").strip().lower()
    model = str(data.get("model") or "").strip()
    custom_url = str(data.get("custom_url") or data.get("customUrl") or "").strip()
    user_key = _normalize_api_key(str(data.get("api_key") or data.get("apiKey") or ""))

    if is_hosted_provider(provider):
        default_model = _DEFAULT_MODELS.get(provider, "")
        if not model or model in ("deepseek-chat", "deepseek-reasoner", "custom-model"):
            model = default_model
        return {
            "provider": provider,
            "model": model or default_model,
            "custom_url": custom_url,
            "api_key": get_hosted_api_key(provider),
            "hosted": True,
        }

    return {
        "provider": provider,
        "model": model or "deepseek-v4-flash",
        "custom_url": custom_url,
        "api_key": user_key,
        "hosted": False,
    }


def llm_settings_error(settings: dict) -> str | None:
    if settings.get("hosted"):
        if not settings.get("api_key"):
            return "内置 Agnes 免费 Key 尚未配置，请稍后重试或更换其他 AI 提供商"
        return None
    if not settings.get("api_key"):
        return "未填写API Key"
    return None
