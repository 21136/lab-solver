"""O10/R8 + R9: mixed theory + code_cloze split, deliverable, ReAct/deep."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

MIXED_QUESTIONS = [
    {
        "id": 0,
        "type": "theory",
        "title": "简答 Facade",
        "full_text": "简述外观模式的作用。",
    },
    {
        "id": 1,
        "type": "code_cloze",
        "title": "Singleton 填空",
        "full_text": "class T { ( 1 ) x; ( 2 ) y; }",
        "metadata": {
            "code_cloze": {"blank_count": 2, "language_hint": "java"},
            "reference_blanks": {
                "1": {"answer": "static", "answer_alt": []},
                "2": {"answer": "private", "answer_alt": []},
            },
        },
    },
]

MIXED_PLAN = [
    {
        "module": "solve_theory",
        "params": {"segment_id": 0, "segment_title": "简答 Facade"},
        "default_checked": True,
    },
    {
        "module": "solve_code_cloze",
        "params": {"segment_id": 1, "segment_title": "Singleton 填空", "language": "java"},
        "default_checked": True,
    },
    {"module": "present_deliverable", "params": {}, "default_checked": True},
]


def _mixed_fixture() -> Path:
    fixture = ROOT / "tests" / "fixtures" / "mixed_theory_cloze.docx"
    if not fixture.exists():
        from tests.generate_fixtures import mixed_theory_cloze

        mixed_theory_cloze().save(fixture)
    return fixture


def test_split_mixed_paste_text_segments():
    from modules.parse_report import (
        build_questions_from_segments,
        should_use_mixed_assignment,
        split_text_assignment_segments,
    )
    from tests.generate_fixtures import mixed_theory_cloze_paste_text

    segments = split_text_assignment_segments(mixed_theory_cloze_paste_text())
    assert len(segments) >= 2
    questions = build_questions_from_segments(segments, title_base="混排样卷")
    assert should_use_mixed_assignment(questions)
    types = [q["type"] for q in questions]
    assert types[0] == "theory"
    assert "code_cloze" in types


def test_split_mixed_docx_segments():
    from docx import Document

    from modules.parse_report import (
        build_questions_from_segments,
        should_use_mixed_assignment,
        split_docx_assignment_segments,
    )

    doc = Document(str(_mixed_fixture()))
    segments = split_docx_assignment_segments(doc)
    assert len(segments) >= 2
    questions = build_questions_from_segments(segments, title_base="混排样卷")
    assert should_use_mixed_assignment(questions)
    types = {q["type"] for q in questions}
    assert "theory" in types
    assert "code_cloze" in types
    assert questions[0]["type"] == "theory"


def test_parse_mixed_assignment_docx():
    from agent.parse_documents import parse_documents_list

    fixture = _mixed_fixture()
    parsed = parse_documents_list(
        [
            {
                "id": "mixed-1",
                "role": "assignment",
                "file_data": base64.b64encode(fixture.read_bytes()).decode(),
                "file_name": fixture.name,
            },
        ]
    )
    meta = parsed["metadata"]
    assert meta.get("mixed_assignment") is True
    questions = parsed.get("questions") or []
    assert len(questions) >= 2
    assert questions[0]["type"] == "theory"
    assert any(q["type"] == "code_cloze" for q in questions)
    assert parsed["question"]["id"] == questions[0]["id"]


def test_build_mixed_assignment_plan():
    from agent.planner import build_mixed_assignment_plan

    questions = [
        {"id": 0, "type": "theory", "title": "简答", "full_text": "说明 Facade"},
        {
            "id": 1,
            "type": "code_cloze",
            "title": "填空",
            "full_text": "class T { ( 1 ) x; ( 2 ) y; }",
            "metadata": {"code_cloze": {"blank_count": 2, "language_hint": "java"}},
        },
    ]
    steps = build_mixed_assignment_plan(questions)
    modules = [s["module"] for s in steps]
    assert modules == ["solve_theory", "solve_code_cloze", "present_deliverable"]
    assert steps[0]["params"]["segment_id"] == 0
    assert steps[1]["params"]["segment_id"] == 1
    assert steps[1]["params"].get("include_full_context") is True


def test_build_mixed_deliverable_from_segments():
    from modules.deliverable import build_deliverable

    ctx = {
        "metadata": {
            "mixed_assignment": True,
            "assignment_questions": MIXED_QUESTIONS,
        },
        "segment_solve_results": [
            {
                "segment_id": 0,
                "module": "solve_theory",
                "title": "简答 Facade",
                "type": "theory",
                "data": {"answer": "封装子系统，提供统一接口。"},
            },
            {
                "segment_id": 1,
                "module": "solve_code_cloze",
                "title": "Singleton 填空",
                "type": "code_cloze",
                "data": {
                    "type": "code_cloze",
                    "parsed": {
                        "blanks": {
                            "1": {"answer": "static", "brief": "静态"},
                            "2": {"answer": "private", "brief": "私有"},
                        },
                        "completed_code": "class T { static x; private y; }",
                    },
                },
            },
        ],
        "user_constraints": [],
    }
    dlv = build_deliverable(ctx)
    assert dlv["type"] == "mixed_assignment"
    assert len(dlv["mixed_parts"]) == 2
    assert dlv["mixed_parts"][0]["answer_text"].startswith("封装")
    cloze_part = dlv["mixed_parts"][1]["code_cloze"]
    assert cloze_part["blanks"]["1"]["answer"] == "static"
    assert cloze_part["reference_blanks"]["1"]["answer"] == "static"


def test_solve_theory_maps_as_react_module_action():
    from agent.registry import react_action_to_module

    assert react_action_to_module("solve_theory") == "solve_theory"


def test_mixed_plan_checklist():
    from agent.react_prompts import build_plan_checklist

    ctx = {
        "metadata": {"mixed_assignment": True, "assignment_questions": MIXED_QUESTIONS},
        "module_results": {},
        "segment_solve_results": [
            {"segment_id": 0, "module": "solve_theory", "data": {"answer": "ok"}},
        ],
    }
    text = build_plan_checklist(MIXED_PLAN, ctx)
    assert "混排卷" in text
    assert "solve_theory" in text
    assert "solve_code_cloze" in text
    assert "禁止 solve_lab" in text or "勿 solve_lab" in text
    assert "[x] solve_theory" in text
    assert "[ ] solve_code_cloze" in text


@pytest.fixture(autouse=True)
def _not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        with patch("agent.react_loop.is_cancelled", return_value=False):
            with patch("agent.deep_pipeline.is_cancelled", return_value=False):
                yield


@patch("agent.react_loop.chat_messages")
@patch("agent.react_loop.emit_event")
@patch("agent.react_loop.release_run")
def test_react_mixed_bootstrap_sequence(mock_release, mock_emit, mock_chat):
    from agent.react_loop import run_react_loop

    mock_chat.return_value = {
        "content": '{"thought": "收尾", "action": "done", "params": {}}',
        "reasoning_content": "",
        "finish_reason": "stop",
    }
    order: list[str] = []

    def _theory(ctx, p):
        order.append("solve_theory")
        ctx.setdefault("segment_solve_results", []).append(
            {"segment_id": p.get("segment_id"), "module": "solve_theory", "data": {"answer": "a"}}
        )
        return {"ok": True, "data": {"answer": "a"}}

    def _cloze(ctx, p):
        order.append("solve_code_cloze")
        ctx.setdefault("segment_solve_results", []).append(
            {
                "segment_id": p.get("segment_id"),
                "module": "solve_code_cloze",
                "data": {"blanks": {"1": {"answer": "static"}}},
            }
        )
        return {"ok": True, "data": {"type": "code_cloze", "blanks": {"1": {"answer": "static"}}}}

    ctx = {
        "settings": {"api_key": "k", "provider": "deepseek", "model": "m"},
        "report_text": "混排全文",
        "planner_input_text": "混排全文",
        "metadata": {"mixed_assignment": True, "assignment_questions": MIXED_QUESTIONS},
        "module_results": {},
        "output_mode": "deliverable",
    }
    solve_lab_calls: list[str] = []

    def _solve_lab(_ctx, _p):
        solve_lab_calls.append("solve_lab")
        return {"ok": False, "data": {}}

    with patch.dict(
        "agent.executor._MODULE_RUNNERS",
        {
            "solve_theory": _theory,
            "solve_code_cloze": _cloze,
            "solve_lab": _solve_lab,
        },
        clear=False,
    ):

        with patch("agent.quality.verify_answer", return_value={"passed": True, "checks": []}):
            result = run_react_loop("mixed-react", ctx, MIXED_PLAN, use_fallback=False)

    assert order == ["solve_theory", "solve_code_cloze"]
    trace = result.get("thought_trace") or []
    bootstrap_actions = [t.get("action") for t in trace if t.get("bootstrap")]
    assert bootstrap_actions == ["solve_theory", "solve_code_cloze"]
    assert "solve_lab" not in bootstrap_actions
    assert solve_lab_calls == []



def test_programming_lab_not_mixed():
    from modules.parse_report import build_questions_from_segments, should_use_mixed_assignment

    fixture = ROOT / "tests" / "fixtures" / "programming_lab.docx"
    if not fixture.exists():
        from tests.generate_fixtures import programming_lab

        programming_lab().save(fixture)
    from docx import Document

    doc = Document(str(fixture))
    from modules.parse_report import split_docx_assignment_segments

    segments = split_docx_assignment_segments(doc)
    questions = build_questions_from_segments(segments, title_base="lab")
    assert not should_use_mixed_assignment(questions)
