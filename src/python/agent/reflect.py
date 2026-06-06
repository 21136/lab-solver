"""
Deep reflect — anchored on assignment_raw (Phase 2b B1).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from agent.prompts import PROMPTS
from llm_client import chat, select_model_for_run_mode
from modules.lab_parse import parse_lab_json


def _issues_fingerprint(issues: list) -> str:
    payload = json.dumps(issues, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_reflect(
    ctx: dict,
    *,
    understand: dict,
    draft_parsed: dict,
    assignment_raw: str = "",
) -> dict[str, Any]:
    """
    Returns { pass, issues[], fix_hints[], misunderstood?, issues_fingerprint }.
    """
    settings = ctx["settings"]
    assign = (assignment_raw or ctx.get("assignment_text") or ctx.get("planner_input_text") or ctx.get("report_text") or "")[:3000]
    parsed_summary = {
        k: (draft_parsed.get(k) or "")[:800]
        for k in (
            "steps_analysis",
            "result_description",
            "expected_output",
            "summary",
            "code",
        )
    }
    tc = ctx.get("teacher_constraints") or {}
    rules = tc.get("rules") or []
    rules_txt = "\n".join(f"- {r.get('text')}" for r in rules[:8] if r.get("text"))

    prompt = PROMPTS["reflect"].render(
        assignment_raw=assign,
        understand_json=json.dumps(understand, ensure_ascii=False)[:2500],
        draft_json=json.dumps(parsed_summary, ensure_ascii=False)[:3500],
        teacher_rules=rules_txt or "（无）",
        fill_scope=json.dumps(ctx.get("fill_scope") or {}, ensure_ascii=False)[:800],
    )

    model = select_model_for_run_mode(settings, "deep")
    try:
        result = chat(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            model,
            prompt,
            custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
            max_tokens=2000,
            phase="reflect",
            run_mode="deep",
        )
        raw = parse_lab_json(result.get("content") or "")
        if "pass" not in raw and "issues" in raw:
            raw["pass"] = len(raw.get("issues") or []) == 0
        issues = raw.get("issues") or []
        if not isinstance(issues, list):
            issues = []
        out = {
            "pass": bool(raw.get("pass")) or len(issues) == 0,
            "issues": issues,
            "fix_hints": raw.get("fix_hints") or [],
            "misunderstood": bool(raw.get("misunderstood")),
            "issues_fingerprint": _issues_fingerprint(issues),
            "reasoning_content": result.get("reasoning_content") or "",
            "skipped": False,
        }
        return out
    except Exception as e:
        return {
            "pass": True,
            "issues": [],
            "fix_hints": [],
            "misunderstood": False,
            "issues_fingerprint": "",
            "skipped": True,
            "skip_reason": str(e)[:200],
        }
