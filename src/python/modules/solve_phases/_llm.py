"""LLM helpers for solve phases."""

from __future__ import annotations

from typing import Any

from llm_client import chat


def track_prompt(session: Any, key: str) -> None:
    from agent.prompts import PROMPTS

    tpl = PROMPTS.get(key)
    if tpl:
        session.prompt_versions[key] = tpl.version


def call_llm(settings: dict, prompt: str, *, phase: str, max_tokens: int = 4000) -> str:
    result = chat(
        settings.get("api_key", ""),
        settings.get("provider", "deepseek"),
        settings.get("model", "deepseek-chat"),
        prompt,
        custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
        phase=phase,
        max_tokens=max_tokens,
    )
    return (result.get("content") or "").strip()
