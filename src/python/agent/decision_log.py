"""Append-only decision log for AgentContext (no LLM)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from agent.types import DecisionLogEntry


def append_decision(
    ctx: dict[str, Any],
    *,
    agent: str,
    decision: str,
    target: str,
    reason: str,
    source: str = "",
    evidence: str = "",
    fingerprint: str = "",
    overridden: bool = False,
    emit: Optional[Callable[[DecisionLogEntry], None]] = None,
) -> DecisionLogEntry:
    entry: DecisionLogEntry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "decision": decision,
        "source": source,
        "target": target,
        "reason": reason,
        "evidence": evidence,
        "fingerprint": fingerprint or (ctx.get("plan") or {}).get("plan_fingerprint", ""),
        "overridden": overridden,
    }
    log = ctx.setdefault("decision_log", [])
    if not isinstance(log, list):
        log = []
        ctx["decision_log"] = log
    log.append(entry)
    if emit:
        emit(entry)
    return entry


def summarize_for_history(
    log: list[DecisionLogEntry] | None,
    *,
    max_entries: int = 8,
) -> list[dict[str, str]]:
    """Compact decision log for Electron localStorage history."""
    out: list[dict[str, str]] = []
    for entry in (log or [])[-max_entries:]:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "agent": str(entry.get("agent") or ""),
                "decision": str(entry.get("decision") or ""),
                "target": str(entry.get("target") or ""),
                "reason": str(entry.get("reason") or "")[:120],
            }
        )
    return out
