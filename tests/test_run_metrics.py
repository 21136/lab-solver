"""IR-25: local run_events aggregation."""

import json

from agent.run_metrics import aggregate_run_events


def test_aggregate_run_events_empty(tmp_path, monkeypatch):
    events_dir = tmp_path / "run_events"
    events_dir.mkdir()
    monkeypatch.setattr("agent.run_metrics.RUN_EVENTS_DIR", events_dir)
    summary = aggregate_run_events(max_files=10, max_age_days=7)
    assert summary["files_scanned"] == 0
    assert summary["runs_with_done"] == 0


def test_aggregate_run_events_counts_done(tmp_path, monkeypatch):
    events_dir = tmp_path / "run_events"
    events_dir.mkdir()
    monkeypatch.setattr("agent.run_metrics.RUN_EVENTS_DIR", events_dir)
    path = events_dir / "run-abc.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "progress", "module": "solve_lab"}),
                json.dumps(
                    {
                        "type": "done",
                        "ok": True,
                        "run_summary": {
                            "mode": "standard",
                            "verify_pass": True,
                            "llm_calls": 4,
                            "replan_count": 0,
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    summary = aggregate_run_events(max_files=10, max_age_days=7)
    assert summary["files_scanned"] == 1
    assert summary["runs_with_done"] == 1
    assert summary["done_ok"] == 1
    assert summary["verify_pass"] == 1
    assert summary["llm_calls_total"] == 4


def test_agent_run_metrics_api():
    from server import app

    client = app.test_client()
    resp = client.get("/api/agent/run-metrics?max_files=5&max_age_days=7")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "run_events" in data
    assert "keep_rate" in data
