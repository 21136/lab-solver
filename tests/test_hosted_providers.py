"""Hosted LLM provider key resolution."""

from __future__ import annotations

import pytest

import hosted_providers as hp


@pytest.fixture(autouse=True)
def _isolate_hosted_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(hp, "APP_DATA", tmp_path)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)


def test_resolve_agnes_uses_hosted_key():
    hp.save_hosted_api_key("agnes", "sk-hosted")
    settings = hp.resolve_llm_settings({"provider": "agnes", "model": ""})
    assert settings["hosted"] is True
    assert settings["api_key"] == "sk-hosted"
    assert settings["model"] == "agnes-2.0-flash"


def test_resolve_deepseek_uses_user_key():
    settings = hp.resolve_llm_settings(
        {"provider": "deepseek", "api_key": "sk-user", "model": "deepseek-chat"}
    )
    assert settings["hosted"] is False
    assert settings["api_key"] == "sk-user"


def test_llm_settings_error_hosted_missing():
    settings = hp.resolve_llm_settings({"provider": "agnes"})
    assert hp.llm_settings_error(settings) == (
        "内置 Agnes 免费 Key 尚未配置，请稍后重试或更换其他 AI 提供商"
    )


def test_env_overrides_file(monkeypatch):
    hp.save_hosted_api_key("agnes", "sk-file")
    monkeypatch.setenv("AGNES_API_KEY", "sk-env")
    assert hp.get_hosted_api_key("agnes") == "sk-env"


def test_strips_utf8_bom_from_file(monkeypatch, tmp_path):
    monkeypatch.setattr(hp, "APP_DATA", tmp_path)
    path = tmp_path / "hosted_agnes.key"
    path.write_bytes(b"\xef\xbb\xbfsk-bom-key")
    assert hp.get_hosted_api_key("agnes") == "sk-bom-key"
