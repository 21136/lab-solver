"""Model registry: aliases, catalog, API resolution."""

from model_registry import (
    get_model_catalog,
    normalize_saved_model,
    resolve_model_for_api,
    select_model_for_run_mode,
)


def test_normalize_deepseek_legacy():
    assert normalize_saved_model("deepseek", "deepseek-chat") == "deepseek-v4-flash"
    assert normalize_saved_model("deepseek", "deepseek-reasoner") == "deepseek-v4-flash"


def test_resolve_flash_standard_disables_thinking():
    r = resolve_model_for_api("deepseek", "deepseek-v4-flash", run_mode="standard")
    assert r["api_model"] == "deepseek-v4-flash"
    assert r["payload_fields"]["thinking"] == {"type": "disabled"}


def test_resolve_flash_deep_enables_thinking():
    r = resolve_model_for_api("deepseek", "deepseek-v4-flash", run_mode="deep")
    assert r["payload_fields"]["thinking"] == {"type": "enabled"}
    assert r["payload_fields"]["reasoning_effort"] == "high"


def test_legacy_reasoner_alias_enables_thinking_even_in_standard():
    r = resolve_model_for_api("deepseek", "deepseek-reasoner", run_mode="standard")
    assert r["api_model"] == "deepseek-v4-flash"
    assert r["payload_fields"]["thinking"] == {"type": "enabled"}


def test_select_model_for_run_mode_keeps_saved_id():
    settings = {"provider": "deepseek", "model": "deepseek-chat"}
    assert select_model_for_run_mode(settings, "deep") == "deepseek-v4-flash"


def test_catalog_has_v4_defaults():
    cat = get_model_catalog()
    assert cat["defaults"]["deepseek"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in {m["id"] for m in cat["providers"]["deepseek"]}
