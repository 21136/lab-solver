"""IR-17: Real docx fixture E2E — POST /api/agent/plan → /api/agent/run (mock LLM)."""

from __future__ import annotations

import base64
import json
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from server import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_FIXTURE_FACTORIES = {
    "programming_lab.docx": "programming_lab",
    "code_cloze_singleton.docx": "code_cloze_singleton",
}

LLM_REQUEST = {
    "api_key": "sk-test-mock",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "run_mode": "standard",
}


def _ensure_fixture(name: str) -> Path:
    path = FIXTURES / name
    if path.exists():
        return path
    factory_name = _FIXTURE_FACTORIES.get(name)
    if not factory_name:
        raise FileNotFoundError(name)
    from tests import generate_fixtures

    factory = getattr(generate_fixtures, factory_name)
    factory().save(path)
    return path


def _docx_documents_payload(doc_id: str, filename: str, *, role: str) -> list[dict]:
    data = base64.b64encode(_ensure_fixture(filename).read_bytes()).decode()
    return [
        {
            "id": doc_id,
            "role": role,
            "file_data": data,
            "file_name": filename,
        }
    ]


def _planner_chat_response(modules: list[str]) -> dict:
    steps = [
        {
            "module": module,
            "params": {"language": "java"} if module in ("solve_lab", "solve_code_cloze") else {},
            "reason": "e2e mock planner",
            "source": "llm",
            "confidence": "high",
            "default_checked": True,
        }
        for module in modules
    ]
    return {
        "content": json.dumps({"steps": steps, "clarifications": []}, ensure_ascii=False),
        "reasoning_content": "",
    }


def _mock_solve_lab_payload() -> dict:
    return {
        "ok": True,
        "data": {
            "code": "public class Main { public static void main(String[] a) {} }",
            "language": "java",
            "parsed": {
                "steps_analysis": "步骤",
                "result_description": "结果",
                "summary": "小结",
            },
            "pipeline_meta": {"version": "v4", "code_status": "verified"},
            "solve_session": {"code_status": "verified", "pipeline_version": "v4"},
        },
    }


class _ModuleSequenceTracker:
    def __init__(self) -> None:
        self.order: list[str] = []

    def runner(self, name: str):
        def _run(_ctx, _params):
            self.order.append(name)
            if name == "solve_lab":
                return _mock_solve_lab_payload()
            if name == "solve_code_cloze":
                return {
                    "ok": True,
                    "data": {
                        "type": "code_cloze",
                        "blanks": {
                            "1": {"answer": "static", "brief": "类变量"},
                            "2": {"answer": "private", "brief": "私有构造"},
                            "3": {"answer": "new", "brief": "实例化"},
                        },
                    },
                }
            if name == "present_deliverable":
                return {
                    "ok": True,
                    "data": {"deliverable": {"sections": [], "code_files": []}},
                }
            return {"ok": True, "data": {}}

        return _run

    def as_dict(self) -> dict:
        return {
            name: self.runner(name)
            for name in (
                "solve_lab",
                "solve_code_cloze",
                "present_deliverable",
                "run_code",
                "render_uml",
            )
        }


def _wait_run_done(run_id: str, timeout: float = 15.0) -> list[dict]:
    from agent.run_control import get_run_events

    deadline = time.time() + timeout
    while time.time() < deadline:
        status, events = get_run_events(run_id, since=0)
        if any(e.get("type") == "done" for e in events):
            return events
        if status not in ("running", "unknown"):
            _, events = get_run_events(run_id, since=0)
            return events
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} did not finish within {timeout}s")


def _run_plan_then_execute(
    client,
    *,
    documents: list[dict],
    planner_modules: list[str],
    expected_plan_modules: list[str],
    expected_run_modules: list[str],
    question_type: str | None = None,
    force_snapshot_on_run: bool = False,
) -> None:
    tracker = _ModuleSequenceTracker()
    plan_payload = {**LLM_REQUEST, "documents": documents}

    with patch("llm_client.chat", return_value=_planner_chat_response(planner_modules)):
        plan_resp = client.post("/api/agent/plan", json=plan_payload)

    assert plan_resp.status_code == 200, plan_resp.get_json()
    plan_data = plan_resp.get_json()
    steps = plan_data.get("steps") or []
    plan_modules = [s.get("module") for s in steps]
    assert plan_modules == expected_plan_modules
    assert plan_data.get("plan_fingerprint", "").startswith("sha256:")
    assert plan_data.get("document_ids")
    snapshot = plan_data.get("agent_context_snapshot") or {}
    assert snapshot.get("planner_input_text")
    if question_type:
        assert (snapshot.get("question") or {}).get("type") == question_type

    run_payload = {
        **LLM_REQUEST,
        "document_ids": plan_data["document_ids"],
        "steps": steps,
        "plan_fingerprint": plan_data["plan_fingerprint"],
        "agent_context_snapshot": snapshot,
    }

    stale_doc_ctx = (
        patch(
            "server.resolve_agent_context",
            side_effect=ValueError("文档缓存已过期或不存在"),
        )
        if force_snapshot_on_run
        else nullcontext()
    )

    with stale_doc_ctx:
        with patch("agent.orchestrator.is_cancelled", return_value=False):
            with patch.dict("agent.executor._MODULE_RUNNERS", tracker.as_dict(), clear=False):
                with patch(
                    "agent.quality.verify_answer",
                    return_value={"passed": True, "checks": []},
                ):
                    run_resp = client.post("/api/agent/run", json=run_payload)

                    assert run_resp.status_code == 200, run_resp.get_json()
                    run_data = run_resp.get_json()
                    assert run_data.get("status") == "running"
                    run_id = run_data.get("run_id")
                    assert run_id
                    assert run_data.get("events_url", "").endswith(run_id)

                    events = _wait_run_done(run_id)
                    done = next(e for e in events if e.get("type") == "done")
                    assert done.get("ok") is True
                    summary = done.get("run_summary") or {}
                    assert summary.get("mode") == "standard"
                    assert "llm_calls_by_phase" in summary
                    assert tracker.order == expected_run_modules


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        with patch("agent.react_loop.is_cancelled", return_value=False):
            with patch("agent.deep_pipeline.is_cancelled", return_value=False):
                yield


class TestAgentFixtureE2E:
    """Parse real docx → plan → standard run without live LLM API keys."""

    def test_programming_lab_docx_plan_then_run(self, client):
        _run_plan_then_execute(
            client,
            documents=_docx_documents_payload(
                "prog-lab",
                "programming_lab.docx",
                role="fill_target",
            ),
            planner_modules=["solve_lab", "present_deliverable"],
            expected_plan_modules=["solve_lab", "present_deliverable"],
            expected_run_modules=["solve_lab", "present_deliverable"],
            question_type="lab_report",
        )

    def test_code_cloze_singleton_docx_plan_then_run(self, client):
        """LLM may return lab plan; server must override to cloze route."""
        _run_plan_then_execute(
            client,
            documents=_docx_documents_payload(
                "cloze-docx",
                "code_cloze_singleton.docx",
                role="assignment",
            ),
            planner_modules=["solve_lab", "run_code", "present_deliverable"],
            expected_plan_modules=["solve_code_cloze", "present_deliverable"],
            expected_run_modules=["solve_code_cloze", "present_deliverable"],
            question_type="code_cloze",
            # assignment_only: resolve_agent_context planner_input ≠ plan-time text;
            # exercise IR-2 snapshot fallback on run (production path).
            force_snapshot_on_run=True,
        )
