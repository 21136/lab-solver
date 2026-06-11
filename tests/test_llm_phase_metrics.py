"""IR-10: llm_calls_by_phase bucket metrics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

import llm_client  # noqa: E402


def test_llm_calls_by_phase_records_unknown_and_named():
    llm_client.reset_llm_call_count()
    llm_client._record_llm_call("planner")
    llm_client._record_llm_call("")
    llm_client._record_llm_call("planner")

    assert llm_client.get_llm_call_count() == 3
    assert llm_client.get_llm_calls_by_phase() == {"planner": 2, "unknown": 1}

