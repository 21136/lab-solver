"""
Run lifecycle: single active run lock, optional FIFO queue, cancel, SSE queue, API error mapping.
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections import deque
from typing import Any, Callable, Optional

from log_util import logi

_active_run_id: Optional[str] = None
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}
_run_queue: deque[dict[str, Any]] = deque()
_run_starter: Optional[Callable[[str, dict[str, Any]], None]] = None
_persist_events = True
_prune_max_files = 30
_prune_max_age_days = 7


class RunBusyError(Exception):
    def __init__(self, active_run_id: str):
        self.active_run_id = active_run_id
        super().__init__(f"已有任务执行中 (run_id={active_run_id})")


class RunQueueFullError(Exception):
    def __init__(self, active_run_id: str):
        self.active_run_id = active_run_id
        super().__init__(f"运行队列已满 (active_run_id={active_run_id})")


def configure_run_events(
    *,
    persist: bool = True,
    max_files: int = 30,
    max_age_days: int = 7,
) -> None:
    global _persist_events, _prune_max_files, _prune_max_age_days
    _persist_events = bool(persist)
    _prune_max_files = max(1, int(max_files))
    _prune_max_age_days = max(1, int(max_age_days))


def register_run_starter(fn: Callable[[str, dict[str, Any]], None]) -> None:
    global _run_starter
    _run_starter = fn


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


def _new_run_state(
    rid: str,
    *,
    status: str = "running",
    queue_payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "run_id": rid,
        "status": status,
        "cancel_event": threading.Event(),
        "events": queue.Queue(),
        "event_log": [],
        "retry_module": None,
        "last_error": None,
        "jar_consent_event": None,
        "jar_consent_result": None,
    }
    if queue_payload is not None:
        state["queue_payload"] = queue_payload
    return state


def _remove_from_queue_locked(run_id: str) -> None:
    global _run_queue
    _run_queue = deque(item for item in _run_queue if item.get("run_id") != run_id)


def _pop_next_queued_locked() -> Optional[dict[str, Any]]:
    global _active_run_id
    if _active_run_id:
        return None
    while _run_queue:
        item = _run_queue.popleft()
        rid = str(item.get("run_id") or "")
        state = _runs.get(rid)
        if not state or state.get("status") != "queued":
            continue
        state["status"] = "running"
        state.pop("queue_payload", None)
        _active_run_id = rid
        return item
    return None


def _start_queued_run(item: dict[str, Any]) -> None:
    rid = str(item.get("run_id") or "")
    emit_event(rid, {"type": "queue_started", "run_id": rid})
    starter = _run_starter
    if starter:
        starter(rid, item.get("payload") or {})


def _maybe_prune_events() -> None:
    if not _persist_events:
        return
    try:
        from agent.run_event_store import prune_old_files

        prune_old_files(max_files=_prune_max_files, max_age_days=_prune_max_age_days)
    except Exception:
        pass


def try_acquire_or_queue(
    run_id: Optional[str] = None,
    *,
    queue_mode: str = "reject",
    queue_max_depth: int = 1,
    queue_payload: Optional[dict[str, Any]] = None,
) -> tuple[str, str, int]:
    """Return (run_id, status, queue_position). position 0 = active, 1+ = queued."""
    global _active_run_id
    mode = (queue_mode or "reject").lower()
    max_depth = max(1, int(queue_max_depth or 1))

    with _lock:
        if _active_run_id and _active_run_id in _runs:
            active = _runs[_active_run_id]
            if active.get("status") == "running":
                if mode != "fifo" or queue_payload is None:
                    raise RunBusyError(_active_run_id)
                if len(_run_queue) >= max_depth:
                    raise RunQueueFullError(_active_run_id)
                rid = run_id or str(uuid.uuid4())
                _runs[rid] = _new_run_state(rid, status="queued", queue_payload=queue_payload)
                _run_queue.append({"run_id": rid, "payload": queue_payload})
                pos = len(_run_queue)
                logi("run_control", f"queued run_id={rid} position={pos}")
                emit_event(rid, {"type": "queued", "queue_position": pos})
                return rid, "queued", pos

        rid = run_id or str(uuid.uuid4())
        _active_run_id = rid
        _runs[rid] = _new_run_state(rid, status="running")
        logi("run_control", f"acquired run_id={rid}")
        return rid, "running", 0


def acquire_run(run_id: Optional[str] = None) -> str:
    rid, _status, _pos = try_acquire_or_queue(run_id, queue_mode="reject")
    return rid


def release_run(run_id: str, status: str = "completed") -> None:
    global _active_run_id
    next_item: Optional[dict[str, Any]] = None
    with _lock:
        state = _runs.get(run_id)
        if state:
            state["status"] = status
        if _active_run_id == run_id:
            _active_run_id = None
        next_item = _pop_next_queued_locked()
        logi("run_control", f"released run_id={run_id} status={status}")
    if next_item:
        _start_queued_run(next_item)
    _maybe_prune_events()


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    return _runs.get(run_id)


def run_exists(run_id: str) -> bool:
    if get_run(run_id):
        return True
    if not _persist_events:
        return False
    try:
        from agent.run_event_store import has_events

        return has_events(run_id)
    except Exception:
        return False


def get_active_run_id() -> Optional[str]:
    """Return run_id of the in-flight task, if any (RL10 refresh recovery)."""
    with _lock:
        rid = _active_run_id
        if not rid:
            return None
        state = _runs.get(rid)
        if state and state.get("status") == "running":
            return rid
        return None


def is_cancelled(run_id: str) -> bool:
    state = _runs.get(run_id)
    if not state:
        return True
    return state["cancel_event"].is_set()


def cancel_run(run_id: str) -> bool:
    state = _runs.get(run_id)
    if not state:
        return False
    status = state.get("status")
    if status == "queued":
        with _lock:
            _remove_from_queue_locked(run_id)
        state["status"] = "cancelled"
        emit_event(run_id, {"type": "cancelled", "run_id": run_id})
        logi("run_control", f"cancelled queued run_id={run_id}")
        return True
    state["cancel_event"].set()
    state["status"] = "cancelled"
    emit_event(run_id, {"type": "cancelled", "run_id": run_id})
    logi("run_control", f"cancelled run_id={run_id}")
    return True


def _persist_event(run_id: str, event: dict[str, Any]) -> None:
    if not _persist_events:
        return
    try:
        from agent.run_event_store import append_event

        thread_name = threading.current_thread().name or ""
        append_event(run_id, event, thread_name=thread_name)
    except Exception:
        pass


def emit_event(run_id: str, event: dict[str, Any]) -> None:
    state = _runs.get(run_id)
    if not state:
        return
    event.setdefault("run_id", run_id)
    log = state.setdefault("event_log", [])
    event["seq"] = len(log)
    log.append(event)
    _persist_event(run_id, event)
    ev_type = event.get("type", "")
    logi(
        "run_control",
        f"event run_id={run_id} seq={event['seq']} type={ev_type}",
    )
    try:
        state["events"].put_nowait(event)
    except queue.Full:
        pass


def _events_from_disk(run_id: str, since: int) -> tuple[str, list[dict[str, Any]]]:
    from agent.run_event_store import infer_status, read_events

    events = read_events(run_id, since)
    if not events and since == 0:
        return "missing", []
    return infer_status(run_id), events


def get_run_events(run_id: str, since: int = 0) -> tuple[str, list[dict[str, Any]]]:
    """Return (status, events[since:]) for SSE reconnect / polling (RL10)."""
    state = _runs.get(run_id)
    start = max(0, int(since))
    if state:
        log = state.get("event_log") or []
        return str(state.get("status") or "unknown"), list(log[start:])
    return _events_from_disk(run_id, start)


def wait_for_jar_consent(
    run_id: str,
    missing_jars: list[dict[str, Any]],
    *,
    timeout: float = 300.0,
) -> bool:
    """Block solve_lab until UI responds to jar_consent_required (RL8)."""
    state = _runs.get(run_id)
    if not state:
        return False
    consent_ev = threading.Event()
    state["jar_consent_event"] = consent_ev
    state["jar_consent_result"] = None
    emit_event(
        run_id,
        {"type": "jar_consent_required", "missing_jars": missing_jars},
    )
    timed_out = not consent_ev.wait(timeout=timeout)
    approved = bool(state.get("jar_consent_result"))
    state["jar_consent_event"] = None
    state["jar_consent_result"] = None
    if timed_out:
        logi("run_control", f"jar consent timeout run_id={run_id}")
        return False
    return approved


def respond_jar_consent(run_id: str, approved: bool, jar_ids: list[str] | None = None) -> bool:
    state = _runs.get(run_id)
    if not state:
        return False
    if approved and jar_ids:
        state["approved_jar_ids"] = [str(i).strip() for i in jar_ids if str(i).strip()]
    state["jar_consent_result"] = bool(approved)
    consent_ev = state.get("jar_consent_event")
    if consent_ev:
        consent_ev.set()
        return True
    emit_event(run_id, {"type": "jar_consent_resolved", "approved": bool(approved)})
    return True


def iter_events(run_id: str, timeout: float = 30.0, since: int = 0):
    """SSE generator: replay event_log[since:], then live queue (RL10)."""
    state = _runs.get(run_id)
    start = max(0, int(since))

    if not state:
        status, disk_events = _events_from_disk(run_id, start)
        if status == "missing":
            yield {"type": "error", "message": "run_id 不存在"}
            return
        for ev in disk_events:
            yield ev
            if ev.get("type") in ("done", "error", "cancelled"):
                return
        return

    log = state.get("event_log") or []
    for ev in log[start:]:
        yield ev
        if ev.get("type") in ("done", "error", "cancelled"):
            return

    if state.get("status") not in ("running",):
        return

    q: queue.Queue = state["events"]
    seen = len(log)
    while True:
        try:
            ev = q.get(timeout=timeout)
            if int(ev.get("seq", -1)) < seen:
                continue
            yield ev
            seen = max(seen, int(ev.get("seq", seen)) + 1)
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


def reset_run_control_for_tests() -> None:
    """Clear in-memory run state (tests only)."""
    global _active_run_id, _runs, _run_queue
    with _lock:
        _active_run_id = None
        _runs.clear()
        _run_queue.clear()
