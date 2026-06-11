"""
Phase 2a.1 unit tests (no LLM).

Usage:
  python tests/test_phase2a.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.document_store import store_from_text, get_document, resolve_documents  # noqa: E402
from agent.planner import (  # noqa: E402
    compute_plan_fingerprint,
    replan_incremental,
    verify_plan_fingerprint,
)
from agent.prompt_budget import fit_budget, estimate_tokens, split_by_headings  # noqa: E402
from agent.run_control import map_api_error, acquire_run, release_run, RunBusyError  # noqa: E402


def test_fit_budget_preserves_steps():
    text = "封面\n" * 100 + "三、实验步骤\n需要编写程序\n" + "四、实验结果\n" * 50
    out = fit_budget(text, budget_tokens=200, preserve_sections=["步骤"])
    assert "实验步骤" in out or "步骤" in out


def test_fingerprint_document_ids():
    steps = [{"module": "solve_lab", "params": {}, "default_checked": True}]
    a = compute_plan_fingerprint("x", steps, document_ids=["a"])
    b = compute_plan_fingerprint("x", steps, document_ids=["b"])
    assert a != b


def test_stale_plan_detection():
    ctx = {"report_text": "hi", "document_ids": ["d1"]}
    steps = [{"module": "solve_lab", "params": {}, "default_checked": True}]
    fp = compute_plan_fingerprint("hi", steps, document_ids=["d1"])
    ok, _ = verify_plan_fingerprint(ctx, fp, steps)
    assert ok
    ok2, expected = verify_plan_fingerprint(ctx, "sha256:wrong", steps)
    assert not ok2
    assert expected.startswith("sha256:")


def test_document_store():
    doc_id, _ = store_from_text("实验报告正文", metadata={"course": "OS"})
    assert get_document(doc_id)
    text, meta, _, _ = resolve_documents([doc_id])
    assert "实验报告" in text
    assert meta.get("course") == "OS"


def test_replan_incremental():
    confirmed = [
        {"module": "solve_lab", "params": {}, "default_checked": True},
        {"module": "run_code", "params": {}, "default_checked": True},
    ]
    ctx = {
        "report_text": "三、实验步骤",
        "user_profile": {"default_language": "java"},
        "confirmed_steps": confirmed,
        "plan": {"steps": confirmed},
        "decision_log": [],
        "replan_rounds": 0,
        "document_ids": [],
    }
    plan = replan_incremental(
        ctx,
        {
            "failed_module": "run_code",
            "error_summary": "compile error",
            "completed_modules": ["solve_lab"],
        },
    )
    mods = [s["module"] for s in plan["steps"]]
    assert "solve_lab" in mods
    assert ctx["replan_rounds"] == 1


def test_run_busy():
    rid = acquire_run()
    try:
        acquire_run()
        assert False, "expected RunBusyError"
    except RunBusyError:
        pass
    release_run(rid)


def test_run_fifo_queue_mode():
    from agent.run_control import (
        get_run,
        register_run_starter,
        reset_run_control_for_tests,
        try_acquire_or_queue,
    )

    started: list[str] = []
    register_run_starter(lambda rid, _payload: started.append(rid))
    reset_run_control_for_tests()
    rid1 = acquire_run("phase2a-q1")
    payload = {"ctx": {}, "steps_in": []}
    rid2, status, pos = try_acquire_or_queue(
        "phase2a-q2",
        queue_mode="fifo",
        queue_payload=payload,
    )
    assert status == "queued" and pos == 1
    release_run(rid1)
    assert started == ["phase2a-q2"]
    assert get_run(rid2)["status"] == "running"
    release_run(rid2)
    reset_run_control_for_tests()


def test_map_api_error():
    m = map_api_error(Exception("API HTTP 429: rate limit"))
    assert m["error_code"] == "rate_limit"
    assert m["retryable"]


def main():
    test_fit_budget_preserves_steps()
    test_fingerprint_document_ids()
    test_stale_plan_detection()
    test_document_store()
    test_replan_incremental()
    test_run_busy()
    test_map_api_error()
    print("test_phase2a: OK")


if __name__ == "__main__":
    main()
