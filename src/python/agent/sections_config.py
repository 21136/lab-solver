"""
sections_config → fill_scope / user_content / teacher_constraints (Phase 2a.2).
"""

from __future__ import annotations

from typing import Any, Optional

from agent.prompts import PROMPTS
from modules.lab_parse import parse_lab_json

_LEGACY_SECTION_IDS = ("cover", "steps", "result", "summary", "images", "code_in_steps")

_MODE_ALIASES: dict[str, str] = {
    "auto": "auto",
    "ai": "auto",
    "ai_fill": "auto",
    "ai填写": "auto",
    "ai 填写": "auto",
    "user_provided": "user_provided",
    "user": "user_provided",
    "mine": "user_provided",
    "用我的内容": "user_provided",
    "skip": "skip",
    "不填": "skip",
    "preserve": "preserve",
    "有内容不覆盖": "preserve",
    "generate_only": "generate_only",
    "只生成不写入": "generate_only",
}


def _normalize_mode(raw: str) -> str:
    key = (raw or "auto").strip().lower()
    return _MODE_ALIASES.get(key, _MODE_ALIASES.get(raw.strip(), "auto") if raw else "auto")


def _default_fill_scope(global_cfg: dict, sections_detected=None) -> dict[str, Any]:
    if sections_detected:
        sections = {}
        for sec in sections_detected:
            sid = (sec.get("semantic") or "").strip()
            role = sid if sid in ("steps", "result", "summary") else "other"
            key = sid if sid else f"sec_{sec.get('index', len(sections))}"
            if role in ("steps", "result", "summary"):
                sections[key] = "auto"
            else:
                sections[key] = "skip"
        return {
            "sections": sections,
            "code_in_steps": bool(global_cfg.get("include_code", True)),
            "user_content": {},
        }
    return {
        "sections": {
            "cover": "skip",
            "steps": "auto",
            "result": "auto",
            "summary": "auto",
            "images": "auto",
        },
        "code_in_steps": bool(global_cfg.get("include_code", True)),
        "user_content": {},
    }


def normalize(sections_config: Optional[dict], sections_detected=None) -> dict[str, Any]:
    """
    Convert UI sections_config to legacy AgentContext structures.

    Args:
        sections_config: UI sections config dict
        sections_detected: Optional list of {index, heading, semantic} from detect_sections()

    Returns:
        fill_scope, user_content, teacher_constraints, global (merged profile hints)
    """
    cfg = sections_config or {}
    global_cfg = dict(cfg.get("global") or {})
    sections_list = sections_detected or cfg.get("sections_detected") or None
    fill_scope = _default_fill_scope(global_cfg, sections_list)
    user_content: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    raw_notes: list[str] = []

    for sec in cfg.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        sid = (sec.get("id") or "").strip()
        if not sid:
            continue
        mode = _normalize_mode(sec.get("mode") or "auto")
        fill_scope["sections"][sid] = mode

        text = (sec.get("input") or "").strip()
        attachments = sec.get("attachments") or {}
        if mode == "user_provided" and text:
            user_content[sid] = {
                "text": text,
                "images_b64": attachments.get("images_b64") or [],
                "code": attachments.get("code") or "",
            }
        elif text:
            for rule in sec.get("constraints") or []:
                if isinstance(rule, dict) and rule.get("text"):
                    rules.append(
                        {
                            "id": rule.get("id") or f"{sid}_{len(rules)}",
                            "text": rule["text"],
                            "section": rule.get("section") or sid,
                            "position": rule.get("position") or "end",
                            "exact": bool(rule.get("exact", True)),
                            "source": rule.get("source") or "user",
                        }
                    )
            if not sec.get("constraints") and mode in ("auto", "preserve", "generate_only"):
                rules.append(
                    {
                        "id": f"{sid}_note_{len(rules)}",
                        "text": text,
                        "section": sid,
                        "position": "end",
                        "exact": False,
                        "source": "sections_config",
                    }
                )
            raw_notes.append(f"[{sid}] {text[:200]}")

    fill_scope["user_content"] = user_content
    teacher_constraints = {
        "raw_note": "\n".join(raw_notes),
        "rules": rules,
    }
    return {
        "fill_scope": fill_scope,
        "user_content": user_content,
        "teacher_constraints": teacher_constraints,
        "global": global_cfg,
    }


def sections_summary_for_prompt(normalized: dict, sections_detected=None) -> str:
    """Short block for planner prompt.

    When sections_detected is provided, includes heading names for richer context.
    """
    fs = normalized.get("fill_scope") or {}
    sections = fs.get("sections") or {}

    if sections_detected:
        lines = []
        for sec in sections_detected:
            semantic = sec.get("semantic") or ""
            heading = sec.get("heading", "")
            key = semantic or f"sec_{sec.get('index')}"
            mode = sections.get(key, sections.get(semantic, "skip"))
            label = f"{heading} ({semantic})" if heading and semantic else (heading or key)
            lines.append(f"- {label}: {mode}")
    else:
        lines = [f"- {k}: {v}" for k, v in sections.items()]

    uc = normalized.get("user_content") or {}
    if uc:
        lines.append(f"- 用户提供内容的节: {', '.join(uc.keys())}")
    tc = normalized.get("teacher_constraints") or {}
    n_rules = len(tc.get("rules") or [])
    if n_rules:
        lines.append(f"- 老师/格式约束条数: {n_rules}")
    return "\n".join(lines) if lines else ""


def parse_section_brief(
    input_text: str,
    *,
    settings: dict,
    section_id: str = "",
) -> dict[str, Any]:
    """
    Lightweight LLM classification only (user-triggered).
    Returns draft { types, user_content?, constraints[], note? }.
    """
    api_key = (settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未填写 API Key")

    text = (input_text or "").strip()
    if not text:
        raise ValueError("输入为空")

    prompt = PROMPTS["section_brief"].render(
        section_id=section_id or "（未指定）",
        input_text=text[:4000],
    )
    from llm_client import chat

    result = chat(
        api_key=api_key,
        provider=settings.get("provider", "deepseek"),
        model=settings.get("model", "deepseek-chat"),
        prompt=prompt,
        custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
        max_tokens=400,
        phase="section_brief",
    )
    raw = parse_lab_json(result.get("content") or "")
    if not isinstance(raw, dict):
        raw = {}
    types = raw.get("types") or []
    if isinstance(types, str):
        types = [types]
    constraints = raw.get("constraints") or []
    if not isinstance(constraints, list):
        constraints = []
    out: dict[str, Any] = {
        "types": types,
        "constraints": constraints,
        "note": raw.get("note") or "",
    }
    if raw.get("user_content"):
        out["user_content"] = raw["user_content"]
    suggested_mode = raw.get("suggested_mode") or raw.get("fill_mode")
    if suggested_mode:
        out["suggested_mode"] = _normalize_mode(str(suggested_mode))
    return out
