"""Multi-provider LLM chat completions."""

import json
import re
import urllib.error
import urllib.request

from agent.prompts import render_lab_report_prompt, render_theory_prompt
from log_util import logi
from modules.lab_parse import complete_lab_parsed, parse_lab_json

_llm_call_count = 0


def reset_llm_call_count():
    global _llm_call_count
    _llm_call_count = 0


def get_llm_call_count():
    return _llm_call_count


def select_model_for_run_mode(settings: dict, run_mode: str = "standard") -> str:
    """Prefer reasoning model when run_mode=deep (Phase 2b)."""
    model = (settings.get("model") or "deepseek-chat").strip()
    provider = (settings.get("provider") or "deepseek").strip().lower()
    if (run_mode or "standard").lower() != "deep":
        return model
    if provider == "deepseek" and model in ("", "deepseek-chat", "auto"):
        return "deepseek-reasoner"
    lowered = model.lower()
    if any(x in lowered for x in ("reasoner", "o1", "thinking")):
        return model
    return model


PROVIDER_URLS = {
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
}

# Substrings that indicate a model likely accepts image content parts (IM5).
_VISION_MODEL_HINTS = (
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision",
    "gpt-4.1",
    "o1",
    "o3",
    "glm-4v",
    "glm4v",
    "qwen-vl",
    "qwen2-vl",
    "qwen3-vl",
    "deepseek-vl",
    "deepseek-v2",
    "claude-3",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "vision",
    "vl-",
    "-vl",
)

VISION_ASSIGNMENT_PROMPT = (
    "这是一道实验/作业题目页的截图。请逐字提取图中的文字内容"
    "（实验目的、步骤、要求、表格文字等）。不要解读电路图或流程图结构，"
    "只输出提取到的文字。若图中无文字，回复「（无文字）」。"
)


def supports_vision(settings: dict) -> bool:
    """Return True when the configured provider/model likely accepts image input."""
    provider = (settings.get("provider") or "deepseek").strip().lower()
    model = (settings.get("model") or "deepseek-chat").strip().lower()
    if provider == "claude":
        return any(x in model for x in ("claude-3", "claude-sonnet", "claude-opus", "claude-haiku"))
    return any(h in model for h in _VISION_MODEL_HINTS)


def _vision_data_url(mime: str, b64: str) -> str:
    mt = (mime or "image/png").split(";")[0].strip() or "image/png"
    return f"data:{mt};base64,{b64}"


def build_vision_user_content(
    prompt: str,
    *,
    image_b64: str,
    mime: str = "image/png",
) -> list[dict]:
    """OpenAI-compatible multimodal user content parts."""
    return [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": _vision_data_url(mime, image_b64)},
        },
    ]


def _build_claude_vision_content(prompt: str, *, image_b64: str, mime: str) -> list[dict]:
    mt = (mime or "image/png").split(";")[0].strip() or "image/png"
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": image_b64},
        },
        {"type": "text", "text": prompt},
    ]


def chat_vision(
    settings: dict,
    *,
    image_b64: str,
    prompt: str = VISION_ASSIGNMENT_PROMPT,
    mime: str = "image/png",
    phase: str = "vision_read",
    max_tokens: int = 2000,
) -> dict:
    """
    Single-image vision completion (IM5).
    Returns ChatResult-shaped dict with content / usage.
    """
    global _llm_call_count
    _llm_call_count += 1

    api_key = settings.get("api_key") or settings.get("apiKey") or ""
    provider = (settings.get("provider") or "deepseek").strip().lower()
    model = settings.get("model") or "deepseek-chat"
    custom_url = (settings.get("custom_url") or settings.get("customUrl") or "").strip()

    if provider == "claude":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{
                "role": "user",
                "content": _build_claude_vision_content(prompt, image_b64=image_b64, mime=mime),
            }],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
        answer = resp["content"][0]["text"].strip()
        return {
            "content": answer,
            "reasoning_content": "",
            "phase": phase,
            "finish_reason": resp.get("stop_reason") or "",
            "usage": {},
        }

    if provider == "custom" and custom_url:
        api_url = custom_url.rstrip("/") + "/chat/completions"
    else:
        api_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["deepseek"])

    messages = [{
        "role": "user",
        "content": build_vision_user_content(prompt, image_b64=image_b64, mime=mime),
    }]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        api_url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"Vision API HTTP {e.code}: {body[:300]}") from e

    msg = resp["choices"][0]["message"]
    choice = resp["choices"][0]
    usage = resp.get("usage") or {}
    return {
        "content": (msg.get("content") or "").strip(),
        "reasoning_content": (msg.get("reasoning_content") or "").strip(),
        "phase": phase,
        "finish_reason": choice.get("finish_reason") or "",
        "usage": usage,
    }


def detect_lang_from_code(code):
    if not code:
        return None
    if re.search(r"public\s+class\s+\w+", code):
        return "java"
    if re.search(r"def\s+\w+\s*\(|import\s+\w+|print\s*\(", code):
        return "python"
    if re.search(r"#include\s*<", code):
        return "cpp" if re.search(r"cout|cin|endl|vector", code) else "c"
    if re.search(r"function\s+\w+|const\s+\w+\s*=|console\.log", code):
        return "javascript"
    return None


def extract_code_block(text, lang="java"):
    for pat in [
        rf"```{lang}\n([\s\S]*?)```",
        r"```\w*\n([\s\S]*?)```",
        r"```([\s\S]*?)```",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def chat_messages(
    settings: dict,
    messages: list[dict],
    *,
    phase: str = "",
    max_tokens: int = 2000,
) -> dict:
    """
    Messages-array chat completion (ReAct and future multi-turn agents).
    Returns ChatResult-shaped dict.
    """
    global _llm_call_count
    _llm_call_count += 1

    api_key = settings.get("api_key", "")
    provider = (settings.get("provider") or "deepseek").strip().lower()
    model = settings.get("model", "deepseek-chat")
    custom_url = (settings.get("custom_url") or settings.get("customUrl") or "").strip()

    if provider == "claude":
        return _chat_messages_claude(api_key, model, messages, max_tokens, phase)

    if provider == "custom" and custom_url:
        api_url = custom_url.rstrip("/") + "/chat/completions"
    else:
        api_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["deepseek"])

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    req = urllib.request.Request(
        api_url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"API HTTP {e.code}: {body[:300]}") from e

    msg = resp["choices"][0]["message"]
    choice = resp["choices"][0]
    usage = resp.get("usage") or {}
    return {
        "content": (msg.get("content") or "").strip(),
        "reasoning_content": (msg.get("reasoning_content") or "").strip(),
        "phase": phase,
        "finish_reason": choice.get("finish_reason") or "",
        "usage": usage,
    }


def _chat_messages_claude(api_key, model, messages, max_tokens, phase):
    """Claude Messages API — merge system messages into the first user turn."""
    system_text = ""
    rest: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system_text += (m.get("content") or "") + "\n"
        else:
            rest.append(dict(m))
    if system_text and rest:
        rest[0]["content"] = system_text.strip() + "\n\n" + (rest[0].get("content") or "")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "max_tokens": max_tokens, "messages": rest}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode())
    answer = resp["content"][0]["text"].strip()
    return {
        "content": answer,
        "reasoning_content": "",
        "phase": phase,
        "finish_reason": resp.get("stop_reason") or "",
        "usage": {},
    }


def chat(
    api_key,
    provider,
    model,
    prompt,
    custom_url="",
    max_tokens=4000,
    system="",
    phase="",
):
    """
    Generic chat completion for planner and future agent modules.
    Returns ChatResult-shaped dict (content, reasoning_content, phase, finish_reason, usage).
    """
    global _llm_call_count
    _llm_call_count += 1

    if provider == "custom" and custom_url:
        api_url = custom_url.rstrip("/") + "/chat/completions"
    elif provider == "claude":
        return _chat_claude(api_key, model, prompt, max_tokens, phase)
    else:
        api_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["deepseek"])

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    req = urllib.request.Request(
        api_url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"API HTTP {e.code}: {body[:300]}") from e

    msg = resp["choices"][0]["message"]
    choice = resp["choices"][0]
    usage = resp.get("usage") or {}
    return {
        "content": (msg.get("content") or msg.get("reasoning_content") or "").strip(),
        "reasoning_content": (msg.get("reasoning_content") or "").strip(),
        "phase": phase,
        "finish_reason": choice.get("finish_reason") or "",
        "usage": usage,
    }


def _chat_claude(api_key, model, prompt, max_tokens, phase):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode())
    answer = resp["content"][0]["text"].strip()
    return {
        "content": answer,
        "reasoning_content": "",
        "phase": phase,
        "finish_reason": resp.get("stop_reason") or "",
        "usage": {},
    }


def call_ai(
    api_key,
    provider,
    model,
    question,
    custom_url="",
    include_uml=False,
    format_spec=None,
):
    global _llm_call_count
    _llm_call_count += 1

    q_type = question.get("type", "theory")
    full_text = question.get("full_text", question.get("content", ""))

    if q_type == "lab_report":
        user_lang = question.get("preferred_lang", "")
        lang_hint = (
            f"\n\n注意：编程语言必须使用 **{user_lang}**，所有代码都用{user_lang}编写。"
            if user_lang
            else ""
        )
        fmt = question.get("format_constraints")
        if not fmt and format_spec:
            from agent.template_analyzer import to_format_constraints

            fmt = to_format_constraints(format_spec)
        prompt = render_lab_report_prompt(
            full_text,
            include_uml=include_uml,
            lang_hint=lang_hint,
            section_map=question.get("section_map"),
            format_constraints=fmt or "",
            language=user_lang or "",
        )
    else:
        lang = question.get("preferred_lang", "python")
        prompt = render_theory_prompt(full_text, lang=lang)

    if provider == "custom" and custom_url:
        api_url = custom_url.rstrip("/") + "/chat/completions"
    elif provider == "claude":
        return call_claude(api_key, model, prompt, q_type)
    else:
        api_url = PROVIDER_URLS.get(provider, PROVIDER_URLS["deepseek"])

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    max_tokens = 8000 if q_type == "lab_report" else 4000
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    req = urllib.request.Request(
        api_url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"API HTTP {e.code}: {body[:300]}") from e

    msg = resp["choices"][0]["message"]
    answer_text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    logi(
        "ai",
        f'content_len={len(msg.get("content") or "")} '
        f'reasoning_len={len(msg.get("reasoning_content") or "")}',
    )

    parsed = {}
    if q_type == "lab_report":
        parsed = parse_lab_json(answer_text)
        parsed = complete_lab_parsed(parsed, answer_text)

    code = parsed.get("code") or extract_code_block(answer_text, "java")
    code_files = parsed.get("code_files") or []
    main_file = parsed.get("main_file") or ""
    if q_type == "lab_report":
        lang = parsed.get("language", "java")
    else:
        lang = detect_lang_from_code(code) or "python"
    return {
        "answer": answer_text,
        "code": code,
        "code_files": code_files,
        "main_file": main_file,
        "type": q_type,
        "parsed": parsed,
        "language": lang,
    }


def call_claude(api_key, model, prompt, q_type):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode())
    answer = resp["content"][0]["text"]
    parsed = parse_lab_json(answer) if q_type == "lab_report" else {}
    if q_type == "lab_report":
        parsed = complete_lab_parsed(parsed, answer)
    return {
        "answer": answer,
        "code": parsed.get("code", extract_code_block(answer, "java")),
        "code_files": parsed.get("code_files") or [],
        "main_file": parsed.get("main_file") or "",
        "type": q_type,
        "parsed": parsed,
        "language": parsed.get("language", "java"),
    }
