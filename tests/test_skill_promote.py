"""AO-10 skill candidate promote API (no LLM)."""

import json
from unittest.mock import patch

import pytest

import agent.skill_store as skill_store
from agent.skill_store import list_skill_candidates, promote_skill_candidate, record_skill_candidates_from_run


@pytest.fixture(autouse=True)
def _isolate_skill_paths(tmp_path, monkeypatch):
    cand = tmp_path / "skill_candidates.json"
    promoted = tmp_path / "promoted_skills.json"
    monkeypatch.setattr("agent.skill_store.SKILL_CANDIDATES_PATH", cand)
    monkeypatch.setattr("agent.skill_store.PROMOTED_SKILLS_PATH", promoted)
    monkeypatch.setattr("agent.skill_store.APP_DATA", tmp_path)
    yield


def _seed_pending_candidate():
    ctx = {
        "run_id": "r1",
        "module_results": {
            "run_code": {"ok": False, "data": {"error_category": "compile_error"}},
        },
    }
    record_skill_candidates_from_run(ctx)
    ctx["run_id"] = "r2"
    record_skill_candidates_from_run(ctx)
    pending = list_skill_candidates(status="pending")
    assert pending
    return pending[0]["id"]


def test_promote_skill_candidate_writes_promoted_file():
    cid = _seed_pending_candidate()
    result = promote_skill_candidate(
        cid,
        inject="编译错误时检查文件扩展名与语法是否匹配。",
        description="compile_error 提醒",
    )
    assert result["id"] == cid
    raw = json.loads(skill_store.PROMOTED_SKILLS_PATH.read_text(encoding="utf-8"))
    assert any(s.get("id") == cid for s in raw.get("skills", []))
    assert list_skill_candidates(status="pending") == []


@patch("agent.skill_store._append_ai_insights_promote_note", return_value=True)
def test_promote_skill_candidate_api(mock_insights):
    from server import app  # noqa: E402

    cid = _seed_pending_candidate()
    client = app.test_client()
    resp = client.post(
        "/api/skill-candidates/promote",
        json={"id": cid, "inject": "测试注入文本"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == cid
    assert data["insights_updated"] is True
    mock_insights.assert_called_once()


def test_list_skill_candidates_api():
    _seed_pending_candidate()
    from server import app  # noqa: E402

    client = app.test_client()
    resp = client.get("/api/skill-candidates?status=pending")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] >= 1
    assert data["candidates"][0]["status"] == "pending"
