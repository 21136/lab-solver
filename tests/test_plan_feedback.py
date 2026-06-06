"""Plan feedback diff and record (no LLM)."""

from agent.plan_feedback import compute_plan_diff, record_plan_feedback  # noqa: E402


def test_compute_plan_diff_no_change():
    steps = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True},
    ]
    diff = compute_plan_diff(steps, steps)
    assert diff["changed"] is False
    assert diff["toggles"] == []


def test_compute_plan_diff_toggle():
    baseline = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": True},
    ]
    confirmed = [
        {"module": "solve_lab", "default_checked": True},
        {"module": "run_code", "default_checked": False},
    ]
    diff = compute_plan_diff(baseline, confirmed)
    assert diff["changed"] is True
    assert len(diff["toggles"]) == 1
    assert diff["toggles"][0]["module"] == "run_code"
    assert diff["toggles"][0]["to_checked"] is False


def test_compute_plan_diff_reorder():
    baseline = [
        {"module": "solve_lab"},
        {"module": "run_code"},
    ]
    confirmed = [
        {"module": "run_code"},
        {"module": "solve_lab"},
    ]
    diff = compute_plan_diff(baseline, confirmed)
    assert diff["reordered"] is True
    assert diff["changed"] is True


def test_record_plan_feedback_appends_decision_log():
    baseline = [{"module": "fill_report", "default_checked": True}]
    confirmed = [{"module": "fill_report", "default_checked": False}]
    out = record_plan_feedback(
        baseline,
        confirmed,
        plan_fingerprint="fp_test",
        document_ids=["doc1"],
    )
    assert out["recorded"] is True
    assert out["diff"]["changed"] is True
    entry = out["decision_log_entry"]
    assert entry["agent"] == "user"
    assert entry["decision"] == "plan_feedback"
    assert entry["overridden"] is True
    assert out["history"]["plan_feedback"]["changed"] is True
    assert len(out["history"]["decision_summary"]) >= 1


def test_agent_plan_feedback_route():
    from server import app  # noqa: E402

    client = app.test_client()
    resp = client.post(
        "/api/agent/plan/feedback",
        json={
            "baseline_steps": [{"module": "solve_lab", "default_checked": True}],
            "steps": [{"module": "solve_lab", "default_checked": False}],
            "plan_fingerprint": "abc",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["recorded"] is True
    assert data["diff"]["changed"] is True
    assert data["decision_log_entry"]["decision"] == "plan_feedback"
