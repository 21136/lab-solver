"""Shared helpers for agent module runners."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.executor_dirty import compute_sub_fingerprints
from agent.types import ModuleResult, is_non_blocking_module


def _module_fingerprint(module: str, params: dict, data: dict) -> str:
    payload = {"module": module, "params": params, "keys": sorted(data.keys())[:20]}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest[:24]}"


def _ok_result(module: str, data: dict, params: dict | None = None) -> ModuleResult:
    subs: dict[str, str] = {}
    if module == "solve_lab":
        subs = compute_sub_fingerprints(data)
    return ModuleResult(
        ok=True,
        data=data,
        logs=[],
        fingerprint=_module_fingerprint(module, params or {}, data),
        sub_fingerprints=subs,
        cacheable=True,
    )


def _fail_result(module: str, message: str, params: dict | None = None) -> ModuleResult:
    return ModuleResult(
        ok=False,
        data={"error": message},
        logs=[message],
        fingerprint=_module_fingerprint(module, params or {}, {"error": message}),
        cacheable=False,
    )


def _get_solve_data(ctx: dict) -> dict:
    mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    if mr.get("ok"):
        return mr.get("data") or {}
    return {}


def _build_error_meta(result_data: dict, module: str) -> dict | None:
    """Build error_meta for SSE progress events from module result data."""
    if module != "run_code":
        return None
    degraded = result_data.get("degraded") or result_data.get("degraded_reason")
    meta = {
        "degraded": bool(degraded),
        "degraded_reason": result_data.get("degraded_reason", ""),
    }
    if result_data.get("error_category"):
        meta["category"] = result_data["error_category"]
    return meta if (meta["degraded"] or meta.get("category")) else None


def progress_payload_for_module_result(
    module: str,
    result: ModuleResult,
    *,
    index: int | None = None,
) -> dict[str, Any]:
    """Map a module result to an SSE progress event (failed vs degraded for fill_report)."""
    ok = bool(result.get("ok"))
    payload: dict[str, Any] = {"type": "progress", "module": module}
    if index is not None:
        payload["index"] = index
    if ok:
        payload["status"] = "done"
        if module == "present_deliverable":
            dlv = (result.get("data") or {}).get("deliverable")
            if dlv is not None:
                payload["deliverable"] = dlv
        return payload
    result_data = result.get("data") or {}
    err_msg = result_data.get("error", "失败")
    payload["error"] = err_msg
    if is_non_blocking_module(module):
        payload["status"] = "degraded"
        payload["error_meta"] = {
            "degraded": True,
            "degraded_reason": f"填表未成功（不影响答案工作区）：{err_msg}",
        }
        return payload
    payload["status"] = "failed"
    error_meta = _build_error_meta(result_data, module)
    if error_meta:
        payload["error_meta"] = error_meta
    return payload


def module_failure_blocks_pipeline(module: str, result: ModuleResult) -> bool:
    """True when a failed module should increment consecutive_failures / trigger replan."""
    return not result.get("ok") and not is_non_blocking_module(module)
