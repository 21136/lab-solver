"""LLM repair for diagrams[] based on validation / render errors."""
from __future__ import annotations

from typing import Any, Optional

from modules.diagram_verify import format_issues_for_feedback
from modules.revise_answer import revise_answer


def fix_diagrams(
    settings: dict,
    *,
    parsed: dict,
    report_excerpt: str = "",
    feedback: str = "",
    issues: Optional[list[dict]] = None,
    verification_report: Optional[dict] = None,
    format_spec: Optional[dict] = None,
) -> dict[str, Any]:
    """Revise only diagrams field using structured error feedback."""
    issue_text = format_issues_for_feedback(issues or [])
    combined = (feedback or "").strip()
    if issue_text:
        combined = (
            f"{combined}\n\n【图表验错结果】\n{issue_text}".strip()
            if combined
            else f"【图表验错结果】\n{issue_text}"
        )
    combined = (
        combined
        + "\n\n请只修正 diagrams 数组："
        "kind=dfd 用 dfd_json（含 externals/processes/stores/flows）；"
        "其余 kind 用完整 PlantUML（@startuml/@enduml）。"
        "保留正确条目，仅修复报错图。"
    )

    result = revise_answer(
        settings,
        parsed=parsed,
        report_excerpt=report_excerpt,
        scope=["diagrams"],
        feedback=combined[:4000],
        verification_report=verification_report,
        format_spec=format_spec,
    )
    result["scope"] = "diagrams"
    result["issue_count"] = len(issues or [])
    return result
