"""Shared helpers for V4 solve phases."""

from __future__ import annotations

from typing import Any, Callable

PhaseCallback = Callable[[dict[str, Any]], None]

REGEN_THRESHOLD = 2


def emit(on_phase: PhaseCallback | None, phase_id: str, status: str, detail: str = "") -> None:
    if on_phase:
        on_phase({"phase": phase_id, "status": status, "detail": detail})


def record_phase(
    session: Any,
    phase_id: str,
    status: str,
    *,
    llm_calls: int = 0,
    ms: int = 0,
) -> None:
    session.phases.append(
        {
            "id": phase_id,
            "status": status,
            "llm_calls": llm_calls,
            "duration_ms": ms,
        }
    )
    session.total_llm_calls += llm_calls


def combined_code(session: Any) -> str:
    return "\n\n".join(
        (f.get("code") or f.get("content") or "")
        for f in session.code_files
        if (f.get("code") or f.get("content") or "").strip()
    )
