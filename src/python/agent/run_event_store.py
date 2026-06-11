"""Append-only JSONL persistence for agent run events (IR-16a)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TERMINAL_TYPES = frozenset({"done", "error", "cancelled"})


def _events_dir() -> Path:
    from config import RUN_EVENTS_DIR

    return RUN_EVENTS_DIR


def _safe_run_id(run_id: str) -> str:
    return "".join(c for c in (run_id or "") if c.isalnum() or c in "-_")


def event_path(run_id: str) -> Path:
    return _events_dir() / f"{_safe_run_id(run_id)}.jsonl"


def ensure_dir() -> None:
    _events_dir().mkdir(parents=True, exist_ok=True)


def has_events(run_id: str) -> bool:
    return event_path(run_id).is_file()


def append_event(run_id: str, event: dict[str, Any], *, thread_name: str = "") -> None:
    """Write one event line; does not mutate the in-memory event dict."""
    ensure_dir()
    record = dict(event)
    record.setdefault("ts", datetime.now(timezone.utc).isoformat())
    if thread_name:
        record["_trace"] = {"thread": thread_name}
    path = event_path(run_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events(run_id: str, since: int = 0) -> list[dict[str, Any]]:
    path = event_path(run_id)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    start = max(0, int(since))
    return events[start:]


def infer_status(run_id: str) -> str:
    """Derive terminal status from persisted events after process restart."""
    events = read_events(run_id, 0)
    if not events:
        return "missing"
    for ev in reversed(events):
        ev_type = ev.get("type")
        if ev_type == "cancelled":
            return "cancelled"
        if ev_type == "error":
            return "error"
        if ev_type == "done":
            return "completed" if ev.get("ok", True) else "error"
    return "orphaned"


def prune_old_files(*, max_files: int = 30, max_age_days: int = 7) -> int:
    """Delete oldest jsonl files beyond retention limits. Returns files removed."""
    ensure_dir()
    files = sorted(_events_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return 0
    cutoff = time.time() - max(1, max_age_days) * 86400
    removed = 0
    for idx, path in enumerate(files):
        too_old = path.stat().st_mtime < cutoff
        over_count = idx >= max(1, max_files)
        if too_old or over_count:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
    return removed
