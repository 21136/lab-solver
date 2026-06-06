"""Skill candidate queue — error_category / notes hash (V3-4)."""

import json
from unittest.mock import patch

import pytest

from agent.skill_store import (
    SKILL_CANDIDATE_MIN_OCCURRENCES,
    record_skill_candidates_from_run,
)


@pytest.fixture(autouse=True)
def _isolate_candidates(tmp_path, monkeypatch):
    path = tmp_path / "skill_candidates.json"
    monkeypatch.setattr("agent.skill_store.SKILL_CANDIDATES_PATH", path)
    monkeypatch.setattr("agent.skill_store.APP_DATA", tmp_path)
    yield


def test_skill_candidate_after_repeated_error_category():
    ctx = {
        "run_id": "r1",
        "module_results": {
            "run_code": {"ok": False, "data": {"error_category": "compile_error"}},
        },
    }
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "r2"
    new = record_skill_candidates_from_run(ctx)
    assert len(new) == 1
    assert new[0]["source"] == "error_category:compile_error"
    assert new[0]["occurrences"] >= SKILL_CANDIDATE_MIN_OCCURRENCES
    assert new[0]["status"] == "pending"

    raw = json.loads(
        __import__("agent.skill_store", fromlist=["SKILL_CANDIDATES_PATH"]).SKILL_CANDIDATES_PATH.read_text(
            encoding="utf-8"
        )
    )
    assert len(raw["candidates"]) >= 1


def test_skill_candidate_notes_hash():
    notes = "由于运行环境为纯Java SE命令行，没有Servlet容器"
    ctx = {
        "run_id": "n1",
        "module_results": {
            "solve_lab": {"ok": True, "data": {"parsed": {"notes": notes}}},
        },
    }
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "n2"
    new = record_skill_candidates_from_run(ctx)
    assert any("notes_hash" in c.get("source", "") for c in new)
