"""Parse answer template docx → format_spec (Phase 2b B4)."""

from __future__ import annotations

from typing import Any, Optional

from agent.template_analyzer import (
    analyze_template_bytes,
    prepare_format_spec_for_session,
)


def parse_answer_template(
    file_bytes: bytes,
    file_name: str,
    *,
    template_type: str = "user_sample",
    assignment_metadata: Optional[dict] = None,
    assignment_text: str = "",
) -> dict[str, Any]:
    spec = analyze_template_bytes(
        file_bytes,
        file_name,
        template_type=template_type,
    )
    return prepare_format_spec_for_session(
        spec,
        assignment_metadata=assignment_metadata,
        assignment_text=assignment_text,
    )
