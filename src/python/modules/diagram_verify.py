"""Unified diagram validation: schema, render result, code consistency."""
from __future__ import annotations

from typing import Any

from modules.preflight import _check_uml, _check_uml_consistency, _normalize_diagrams_list
from modules.uml import extract_diagrams


def _infra_render_error(errors: list[str]) -> bool:
    """True when re-render alone may help (engine missing), not LLM fix."""
    text = " ".join(errors or []).lower()
    markers = (
        "assets/graphviz",
        "assets\\graphviz",
        "便携 graphviz",
        "plantuml.jar",
        "未找到 java",
        "uml 渲染模块不可用",
    )
    return any(m in text for m in markers)


def verify_diagrams(
    solve_data: dict,
    *,
    render_result: dict | None = None,
    include_consistency: bool = True,
) -> dict[str, Any]:
    """
    Validate diagram definitions and optional render output.

    Returns:
        ok, checks[], failed_ids[], issues[], suggested_actions[]
    """
    parsed = solve_data.get("parsed") if "parsed" in (solve_data or {}) else solve_data
    parsed = parsed or {}
    raw_diagrams = _normalize_diagrams_list(parsed)
    renderable = extract_diagrams(parsed)

    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    if not raw_diagrams and not renderable:
        return {
            "ok": True,
            "checks": [{"id": "diagrams_present", "ok": True, "message": "无 diagrams"}],
            "failed_ids": [],
            "issues": [],
            "suggested_actions": [],
        }

    schema = _check_uml(raw_diagrams)
    checks.append(schema)
    if not schema.get("ok"):
        for part in (schema.get("message") or "").split(";"):
            part = part.strip()
            if part:
                issues.append({"type": "schema", "message": part})

    if include_consistency and renderable:
        consistency = _check_uml_consistency(solve_data, renderable)
        checks.append(consistency)
        if not consistency.get("ok"):
            issues.append({
                "type": "consistency",
                "message": consistency.get("message") or "UML 与代码不一致",
                "missing_in_uml": consistency.get("missing_in_uml") or [],
            })

    render_errors = list((render_result or {}).get("errors") or [])
    validation = (render_result or {}).get("validation") or {}
    if validation.get("issues"):
        for item in validation["issues"]:
            if isinstance(item, dict) and item.get("message"):
                issues.append(item)

    if render_result is not None:
        images = render_result.get("images_b64") or []
        expected = len(renderable) or len(raw_diagrams)
        partial = bool(images) and bool(render_errors)
        render_ok = expected == 0 or (
            not render_errors and len(images) >= min(expected, 1)
        )
        if expected and not images and not render_errors:
            render_ok = False
            render_errors.append("未生成任何图片")
        msg_parts = []
        if render_ok:
            msg_parts.append(f"已渲染 {len(images)}/{expected} 张")
        else:
            if render_errors:
                msg_parts.append("; ".join(render_errors[:4]))
            else:
                msg_parts.append(f"仅渲染 {len(images)}/{expected} 张")
        checks.append({
            "id": "diagram_render",
            "ok": render_ok and not partial,
            "message": msg_parts[0] if msg_parts else "渲染未执行",
            "rendered": len(images),
            "expected": expected,
            "partial": partial,
        })
        for err in render_errors:
            if not any(i.get("message") == err for i in issues):
                issues.append({"type": "render", "message": err})

    failed_ids = [c["id"] for c in checks if not c.get("ok")]
    suggested: list[str] = []

    if "uml_schema" in failed_ids or any(i.get("type") == "schema" for i in issues):
        suggested.append("fix_diagrams")
    if "uml_code_consistency" in failed_ids:
        if "fix_diagrams" not in suggested:
            suggested.append("fix_diagrams")
    if "diagram_render" in failed_ids or render_errors:
        if _infra_render_error(render_errors):
            if "render_uml" not in suggested:
                suggested.append("render_uml")
        else:
            if "fix_diagrams" not in suggested:
                suggested.append("fix_diagrams")
            if "render_uml" not in suggested:
                suggested.append("render_uml")

    return {
        "ok": len(failed_ids) == 0,
        "checks": checks,
        "failed_ids": failed_ids,
        "issues": issues,
        "suggested_actions": list(dict.fromkeys(suggested)),
    }


def format_issues_for_feedback(issues: list[dict]) -> str:
    """Human/LLM-readable issue list."""
    if not issues:
        return "请修正 diagrams 中的语法或结构问题，确保可渲染。"
    lines = []
    for i, item in enumerate(issues[:12], 1):
        msg = item.get("message") or str(item)
        lines.append(f"{i}. [{item.get('type', 'issue')}] {msg}")
    return "\n".join(lines)
