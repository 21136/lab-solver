"""
Phase 3 compliance-ux: decision log history summary.

Usage:
  python tests/test_phase3_compliance.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.decision_log import append_decision, summarize_for_history  # noqa: E402


def test_summarize_for_history_truncates_reason():
    ctx: dict = {}
    append_decision(
        ctx,
        agent="planner",
        decision="include_module",
        target="run_code",
        reason="x" * 200,
    )
    summary = summarize_for_history(ctx["decision_log"], max_entries=5)
    assert len(summary) == 1
    assert summary[0]["agent"] == "planner"
    assert len(summary[0]["reason"]) <= 120


def test_summarize_for_history_max_entries():
    ctx: dict = {}
    for i in range(10):
        append_decision(
            ctx,
            agent="executor",
            decision="skip",
            target=f"step_{i}",
            reason=f"r{i}",
        )
    summary = summarize_for_history(ctx["decision_log"], max_entries=3)
    assert len(summary) == 3
    assert summary[-1]["target"] == "step_9"


if __name__ == "__main__":
    test_summarize_for_history_truncates_reason()
    test_summarize_for_history_max_entries()
    print("test_phase3_compliance: OK")
