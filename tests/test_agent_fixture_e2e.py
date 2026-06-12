"""IR-17 / IR-18: Real docx fixture plan→run matrix (mock LLM, no API key)."""

from __future__ import annotations

import base64
import json
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from server import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_FIXTURE_FACTORIES = {
    "programming_lab.docx": "programming_lab",
    "code_cloze_singleton.docx": "code_cloze_singleton",
    "theory_lab.docx": "theory_lab",
    "training_table.docx": "training_table",
    "mixed_theory_cloze.docx": "mixed_theory_cloze",
}

LLM_REQUEST = {
    "api_key": "sk-test-mock",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "run_mode": "standard",
}

_WRONG_LAB_PLANNER = ["solve_lab", "run_code", "present_deliverable"]


@dataclass(frozen=True)
class FixtureE2ECase:
    """One row in the IR-18 plan→run matrix."""

    id: str
    filename: str
    doc_id: str
    role: str
    planner_modules: list[str]
    expected_plan_modules: list[str]
    expected_run_modules: list[str]
    question_type: str
    force_snapshot_on_run: bool = True
    notes: str = ""


IR18_FIXTURE_MATRIX: tuple[FixtureE2ECase, ...] = (
    FixtureE2ECase(
        id="programming_lab",
        filename="programming_lab.docx",
        doc_id="prog-lab",
        role="fill_target",
        planner_modules=["solve_lab", "present_deliverable"],
        expected_plan_modules=["solve_lab", "present_deliverable"],
        expected_run_modules=["solve_lab", "present_deliverable"],
        question_type="lab_report",
        force_snapshot_on_run=False,
        notes="标准编程实验报告（document_ids 缓存路径）",
    ),
    FixtureE2ECase(
        id="code_cloze_singleton",
        filename="code_cloze_singleton.docx",
        doc_id="cloze-docx",
        role="assignment",
        planner_modules=_WRONG_LAB_PLANNER,
        expected_plan_modules=["solve_code_cloze", "present_deliverable"],
        expected_run_modules=["solve_code_cloze", "present_deliverable"],
        question_type="code_cloze",
        force_snapshot_on_run=True,
        notes="LLM 误出 lab 计划时规则链纠正为 cloze",
    ),
    FixtureE2ECase(
        id="theory_lab",
        filename="theory_lab.docx",
        doc_id="theory-lab",
        role="assignment",
        planner_modules=_WRONG_LAB_PLANNER,
        expected_plan_modules=["solve_lab", "present_deliverable"],
        expected_run_modules=["solve_lab", "present_deliverable"],
        question_type="lab_report",
        notes="纯理论/分析型实验：theory_only 规则剔除 run_code",
    ),
    FixtureE2ECase(
        id="training_table",
        filename="training_table.docx",
        doc_id="train-table",
        role="fill_target",
        planner_modules=_WRONG_LAB_PLANNER,
        expected_plan_modules=["solve_short_answer", "present_deliverable"],
        expected_run_modules=["solve_short_answer", "present_deliverable"],
        question_type="short_answer",
        notes="实训表格型：解析为 short_answer + 规则覆盖",
    ),
    FixtureE2ECase(
        id="mixed_theory_cloze",
        filename="mixed_theory_cloze.docx",
        doc_id="mixed-doc",
        role="assignment",
        planner_modules=_WRONG_LAB_PLANNER,
        expected_plan_modules=[
            "solve_theory",
            "solve_theory",
            "solve_theory",
            "solve_code_cloze",
            "present_deliverable",
        ],
        expected_run_modules=[
            "solve_theory",
            "solve_theory",
            "solve_theory",
            "solve_code_cloze",
            "present_deliverable",
        ],
        question_type="mixed_assignment",
        notes="混排卷：简答 + 填空按段顺序",
    ),
)


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
            if name == "solve_theory":
                return {
                    "ok": True,
                    "data": {
                        "type": "theory",
                        "parsed": {"answer_text": "理论作答"},
                    },
                }
            if name == "solve_short_answer":
                return {
                    "ok": True,
                    "data": {
                        "type": "short_answer",
                        "parsed": {"answers": [{"q": 1, "text": "简答"}]},
                    },
                }
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
                "solve_theory",
                "solve_short_answer",
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
        "llm_replan": True,
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
                    assert "keep_rate" in summary
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


class TestAgentFixtureMatrixIR18:
    """IR-18: parametrized docx → plan → standard run matrix."""

    @pytest.mark.parametrize("case", IR18_FIXTURE_MATRIX, ids=lambda c: c.id)
    def test_fixture_plan_then_run(self, client, case: FixtureE2ECase):
        _run_plan_then_execute(
            client,
            documents=_docx_documents_payload(case.doc_id, case.filename, role=case.role),
            planner_modules=case.planner_modules,
            expected_plan_modules=case.expected_plan_modules,
            expected_run_modules=case.expected_run_modules,
            question_type=case.question_type,
            force_snapshot_on_run=case.force_snapshot_on_run,
        )


# Backward-compatible aliases (IR-17 test names)
class TestAgentFixtureE2E:
    def test_programming_lab_docx_plan_then_run(self, client):
        case = next(c for c in IR18_FIXTURE_MATRIX if c.id == "programming_lab")
        TestAgentFixtureMatrixIR18().test_fixture_plan_then_run(client, case)

    def test_code_cloze_singleton_docx_plan_then_run(self, client):
        case = next(c for c in IR18_FIXTURE_MATRIX if c.id == "code_cloze_singleton")
        TestAgentFixtureMatrixIR18().test_fixture_plan_then_run(client, case)
