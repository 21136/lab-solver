"""C2 behavior outcomes + keep rate (AGENT_CAPABILITY_GAPS step 3-4)."""

from agent.user_profile import (
    compute_keep_rate_summary,
    load_profile,
    normalize_profile,
    record_behavior_outcome,
    save_profile,
)


def test_default_profile_enables_behavior_learning():
    profile = normalize_profile(None)
    assert profile.get("optimize_plan_from_usage") is True


def test_record_behavior_outcome_when_enabled(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setattr("agent.user_profile.PROFILE_PATH", path)
    monkeypatch.setattr("agent.user_profile.APP_DATA", tmp_path)

    profile = normalize_profile({})
    updated = record_behavior_outcome(profile, "copy_section", section="steps_analysis")
    save_profile(updated)
    loaded = load_profile()
    outcomes = loaded["behavior"]["outcomes"]
    assert len(outcomes) == 1
    assert outcomes[0]["event"] == "copy_section"
    assert outcomes[0]["section"] == "steps_analysis"


def test_compute_keep_rate_summary():
    profile = normalize_profile(
        {
            "optimize_plan_from_usage": True,
            "behavior": {
                "outcomes": [
                    {"event": "copy_section"},
                    {"event": "export_markdown"},
                    {"event": "revise_submit"},
                ]
            },
        }
    )
    summary = compute_keep_rate_summary(profile)
    assert summary["copy_section"] == 1
    assert summary["export_events"] == 1
    assert summary["revise_submit"] == 1
    assert summary["keep_signals"] == 2
