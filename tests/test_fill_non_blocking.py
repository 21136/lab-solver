"""V5-4 — fill_report failure must not block pipeline or count as hard failure."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.executor import (
    module_failure_blocks_pipeline,
    progress_payload_for_module_result,
)
from agent.types import is_non_blocking_module


def test_fill_report_is_non_blocking_module():
    assert is_non_blocking_module("fill_report")
    assert not is_non_blocking_module("solve_lab")


def test_progress_payload_degraded_for_fill_failure():
    result = {"ok": False, "data": {"error": "核心节未匹配"}}
    payload = progress_payload_for_module_result("fill_report", result, index=3)
    assert payload["status"] == "degraded"
    assert payload["error"] == "核心节未匹配"
    assert payload["error_meta"]["degraded"] is True
    assert not module_failure_blocks_pipeline("fill_report", result)


def test_solve_failure_still_blocks():
    result = {"ok": False, "data": {"error": "API 错误"}}
    payload = progress_payload_for_module_result("solve_lab", result)
    assert payload["status"] == "failed"
    assert module_failure_blocks_pipeline("solve_lab", result)
