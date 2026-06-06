"""revise_answer — scoped regeneration (Phase 2b B3)."""

from __future__ import annotations

from typing import Any, Optional

from agent.prompt_budget import fit_budget
from agent.prompts import PROMPTS
from llm_client import chat
from modules.lab_parse import complete_lab_parsed, parse_lab_json


_SCOPE_FIELDS = {
    "steps": ["steps_analysis"],
    "result": ["result_description", "expected_output"],
    "summary": ["summary"],
    "code": ["code", "code_files", "main_file", "language"],
    "diagrams": ["diagrams"],
    "full": [
        "steps_analysis",
        "result_description",
        "expected_output",
        "summary",
        "code",
        "code_files",
        "main_file",
        "language",
        "diagrams",
    ],
}


def _scope_to_fields(scope: list[str] | str) -> list[str]:
    if isinstance(scope, str):
        scope = [scope]
    fields: list[str] = []
    for s in scope:
        key = (s or "").strip().lower()
        if key in _SCOPE_FIELDS:
            fields.extend(_SCOPE_FIELDS[key])
        elif key in (
            "steps_analysis",
            "result_description",
            "summary",
            "code",
            "expected_output",
            "diagrams",
        ):
            fields.append(key)
    return list(dict.fromkeys(fields)) or _SCOPE_FIELDS["full"]


def revise_answer(
    settings: dict,
    *,
    parsed: dict,
    report_excerpt: str,
    scope: list[str] | str,
    feedback: str,
    verification_report: Optional[dict] = None,
    format_spec: Optional[dict] = None,
) -> dict[str, Any]:
    """Return merged parsed + revision metadata."""
    fields = _scope_to_fields(scope)
    budgeted = fit_budget(
        report_excerpt,
        budget_tokens=2000,
        preserve_sections=["步骤", "结果", "要求"],
    )
    vr_hint = ""
    if verification_report:
        failed = [c for c in verification_report.get("checks", []) if not c.get("ok")]
        if failed:
            vr_hint = "\n【校验未通过项】\n" + "\n".join(
                f"- {c.get('id')}: {c.get('message')}" for c in failed[:6]
            )

    prompt = PROMPTS["revise_answer"].render(
        scope_fields=", ".join(fields),
        current_json=_parsed_summary(parsed, fields),
        report_excerpt=budgeted,
        feedback=(feedback or "请改进质量").strip()[:2000],
        verification_hint=vr_hint,
        format_hint=(format_spec or {}).get("summary") or "",
    )

    result = chat(
        settings["api_key"],
        settings.get("provider", "deepseek"),
        settings.get("model", "deepseek-chat"),
        prompt,
        custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
        max_tokens=6000,
        phase="revise",
    )
    raw = parse_lab_json(result.get("content") or "")
    merged = dict(parsed)
    changed = []
    for f in fields:
        if f in raw and raw[f]:
            merged[f] = raw[f]
            changed.append(f)
    # If code was changed but code_files was not, update main file's code in code_files
    if "code" in changed and "code_files" not in changed:
        cfs = merged.get("code_files") or []
        main = merged.get("main_file") or ""
        if cfs:
            main_idx = next((i for i, cf in enumerate(cfs) if (cf.get("name") or cf.get("filename")) == main), 0)
            cfs[main_idx]["code"] = merged["code"]
        else:
            merged["code_files"] = [{"name": merged.get("main_file", "main.py"), "code": merged["code"]}]
    merged = complete_lab_parsed(merged, result.get("content") or "")
    return {
        "parsed": merged,
        "changed_fields": changed,
        "reasoning_content": result.get("reasoning_content") or "",
    }


def _parsed_summary(parsed: dict, fields: list[str]) -> str:
    import json

    subset = {k: parsed.get(k, "") for k in fields if k in parsed}
    return json.dumps(subset, ensure_ascii=False, indent=2)[:4000]
