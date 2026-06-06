"""
Run lifecycle: single active run lock, cancel, SSE queue, API error mapping.
"""

from __future__ import annotations

import queue
import re
import threading
import uuid
from typing import Any, Callable, Optional

from log_util import logi

_active_run_id: Optional[str] = None
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


class RunBusyError(Exception):
    def __init__(self, active_run_id: str):
        self.active_run_id = active_run_id
        super().__init__(f"已有任务执行中 (run_id={active_run_id})")


def map_api_error(exc: Exception) -> dict[str, Any]:
    """Normalize LLM / network errors for API responses."""
    msg = str(exc) or "未知错误"
    code = "api_error"
    retryable = False
    status = 500

    if "HTTP 401" in msg or "HTTP 403" in msg:
        code = "auth_error"
        status = 401
    elif "HTTP 429" in msg or "rate" in msg.lower():
        code = "rate_limit"
        retryable = True
        status = 429
    elif "HTTP 402" in msg or "余额" in msg or "insufficient" in msg.lower():
        code = "balance_error"
        status = 402
    elif "timed out" in msg.lower() or "timeout" in msg.lower():
        code = "timeout"
        retryable = True
        status = 504
    elif "HTTP 400" in msg:
        code = "bad_request"
        status = 400

    return {
        "error": msg,
        "error_code": code,
        "retryable": retryable,
        "http_status": status,
    }


def acquire_run(run_id: Optional[str] = None) -> str:
    global _active_run_id
    with _lock:
        if _active_run_id and _active_run_id in _runs:
            state = _runs[_active_run_id]
            if state.get("status") == "running":
                raise RunBusyError(_active_run_id)

        rid = run_id or str(uuid.uuid4())
        _active_run_id = rid
        _runs[rid] = {
            "run_id": rid,
            "status": "running",
            "cancel_event": threading.Event(),
            "events": queue.Queue(),
            "retry_module": None,
            "last_error": None,
        }
        logi("run_control", f"acquired run_id={rid}")
        return rid


def release_run(run_id: str, status: str = "completed") -> None:
    global _active_run_id
    with _lock:
        state = _runs.get(run_id)
        if state:
            state["status"] = status
        if _active_run_id == run_id:
            _active_run_id = None
        logi("run_control", f"released run_id={run_id} status={status}")


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    return _runs.get(run_id)


def is_cancelled(run_id: str) -> bool:
    state = _runs.get(run_id)
    if not state:
        return True
    return state["cancel_event"].is_set()


def cancel_run(run_id: str) -> bool:
    state = _runs.get(run_id)
    if not state:
        return False
    state["cancel_event"].set()
    state["status"] = "cancelled"
    emit_event(run_id, {"type": "cancelled", "run_id": run_id})
    logi("run_control", f"cancelled run_id={run_id}")
    return True


def emit_event(run_id: str, event: dict[str, Any]) -> None:
    state = _runs.get(run_id)
    if not state:
        return
    event.setdefault("run_id", run_id)
    try:
        state["events"].put_nowait(event)
    except queue.Full:
        pass


def iter_events(run_id: str, timeout: float = 30.0):
    """SSE generator: yield events until done/cancelled/timeout heartbeat."""
    state = _runs.get(run_id)
    if not state:
        yield {"type": "error", "message": "run_id 不存在"}
        return

    q: queue.Queue = state["events"]
    while True:
        try:
            ev = q.get(timeout=timeout)
            yield ev
            if ev.get("type") in ("done", "error", "cancelled"):
                break
        except queue.Empty:
            if state.get("status") != "running":
                break
            yield {"type": "heartbeat", "run_id": run_id}


def set_retry_module(run_id: str, module_id: str) -> None:
    state = _runs.get(run_id)
    if state:
        state["retry_module"] = module_id
        state["status"] = "running"
        state["cancel_event"].clear()


def pop_retry_module(run_id: str) -> Optional[str]:
    state = _runs.get(run_id)
    if not state:
        return None
    mod = state.get("retry_module")
    state["retry_module"] = None
    return mod


def set_last_error(run_id: str, module_id: str, error: str) -> None:
    state = _runs.get(run_id)
    if state:
        state["last_error"] = {"module": module_id, "error": error}
