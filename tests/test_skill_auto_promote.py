"""Skill auto-promote when candidates reach occurrence threshold."""

import json

import pytest

import agent.skill_store as skill_store
from agent.skill_store import (
    auto_promote_ready_candidates,
    auto_promote_skills_enabled,
    list_skill_candidates,
    record_skill_candidates_from_run,
)


@pytest.fixture(autouse=True)
def _isolate_skill_paths(tmp_path, monkeypatch):
    cand = tmp_path / "skill_candidates.json"
    promoted = tmp_path / "promoted_skills.json"
    monkeypatch.setattr("agent.skill_store.SKILL_CANDIDATES_PATH", cand)
    monkeypatch.setattr("agent.skill_store.PROMOTED_SKILLS_PATH", promoted)
    monkeypatch.setattr("agent.skill_store.APP_DATA", tmp_path)
    yield


def _run_with_compile_error(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "auto_promote_skills": True,
        "module_results": {
            "run_code": {"ok": False, "data": {"error_category": "compile_error"}},
        },
        "decision_log": [],
    }


def test_auto_promote_skills_enabled_default():
    assert auto_promote_skills_enabled({}) is True
    assert auto_promote_skills_enabled({"auto_promote_skills": False}) is False
    assert auto_promote_skills_enabled({"settings": {"autoPromoteSkills": False}}) is False


def test_auto_promote_after_two_occurrences():
    record_skill_candidates_from_run(_run_with_compile_error("r1"))
    record_skill_candidates_from_run(_run_with_compile_error("r2"))

    promoted_raw = json.loads(skill_store.PROMOTED_SKILLS_PATH.read_text(encoding="utf-8"))
    ids = [s.get("id") for s in promoted_raw.get("skills", [])]
    assert "error_category-compile_error" in ids

    pending = list_skill_candidates(status="pending")
    assert all(c.get("id") != "error_category-compile_error" for c in pending)


def test_auto_promote_skipped_when_disabled():
    ctx = _run_with_compile_error("r1")
    ctx["auto_promote_skills"] = False
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "r2"
    record_skill_candidates_from_run(ctx)

    assert not skill_store.PROMOTED_SKILLS_PATH.exists() or json.loads(
        skill_store.PROMOTED_SKILLS_PATH.read_text(encoding="utf-8")
    ).get("skills") in ([], None)


def test_notes_hash_not_auto_promoted():
    ctx = {
        "run_id": "r1",
        "auto_promote_skills": True,
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {"parsed": {"notes": "singleton pattern used"}},
            },
        },
        "decision_log": [],
    }
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "r2"
    record_skill_candidates_from_run(ctx)

    pending = list_skill_candidates(status="pending")
    assert pending
    assert pending[0]["id"].startswith("notes_hash-")
    promoted = json.loads(skill_store.PROMOTED_SKILLS_PATH.read_text(encoding="utf-8")) if skill_store.PROMOTED_SKILLS_PATH.exists() else {"skills": []}
    assert not any(str(s.get("id", "")).startswith("notes_hash-") for s in promoted.get("skills", []))


def test_auto_promote_writes_decision_log():
    ctx = _run_with_compile_error("r1")
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "r2"
    record_skill_candidates_from_run(ctx)

    decisions = [e.get("decision") for e in ctx.get("decision_log") or []]
    assert "skill_auto_promoted" in decisions


def test_auto_promote_ready_candidates_respects_max_per_run():
    ctx = {
        "run_id": "r2",
        "auto_promote_skills": True,
        "decision_log": [],
    }
    # Seed two ready candidates manually
    skill_store._save_skill_candidates(
        [
            {
                "id": "error_category-compile_error",
                "source": "error_category:compile_error",
                "occurrences": 2,
                "status": "pending",
                "suggested_trigger": "run_code.error_category=compile_error",
                "events": [],
            },
            {
                "id": "error_category-runtime_exception",
                "source": "error_category:runtime_exception",
                "occurrences": 2,
                "status": "pending",
                "suggested_trigger": "run_code.error_category=runtime_exception",
                "events": [],
            },
        ]
    )
    promoted = auto_promote_ready_candidates(ctx)
    assert len(promoted) == 1
    assert ctx.get("skills_auto_promoted")
