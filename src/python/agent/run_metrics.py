"""
IR-25: Local aggregation of persisted agent run events (no upload).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import RUN_EVENTS_DIR


def _parse_iso(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _iter_run_event_files() -> list[Path]:
    if not RUN_EVENTS_DIR.is_dir():
        return []
    return sorted(RUN_EVENTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def aggregate_run_events(
    *,
    max_files: int = 30,
    max_age_days: int = 7,
) -> dict[str, Any]:
    """Summarize local run_events/*.jsonl for harness / settings debug."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, max_age_days))
    files = _iter_run_event_files()[: max(1, max_files)]

    runs_seen: set[str] = set()
    mode_counts: dict[str, int] = {}
    verify_pass = 0
    verify_fail = 0
    done_ok = 0
    done_fail = 0
    llm_calls_total = 0
    replan_total = 0
    files_read = 0

    for path in files:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            continue
        files_read += 1
        run_id = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            etype = str(ev.get("type") or ev.get("event") or "")
            if etype == "done":
                runs_seen.add(run_id)
                summary = ev.get("run_summary") or {}
                if isinstance(summary, dict):
                    mode = str(summary.get("mode") or "unknown")
                    mode_counts[mode] = int(mode_counts.get(mode) or 0) + 1
                    if summary.get("verify_pass") is True:
                        verify_pass += 1
                    elif summary.get("verify_pass") is False:
                        verify_fail += 1
                    llm_calls_total += int(summary.get("llm_calls") or 0)
                    replan_total += int(summary.get("replan_count") or 0)
                if ev.get("ok") is True:
                    done_ok += 1
                else:
                    done_fail += 1

    return {
        "files_scanned": files_read,
        "runs_with_done": len(runs_seen),
        "done_ok": done_ok,
        "done_fail": done_fail,
        "verify_pass": verify_pass,
        "verify_fail": verify_fail,
        "mode_counts": mode_counts,
        "llm_calls_total": llm_calls_total,
        "replan_total": replan_total,
    }
