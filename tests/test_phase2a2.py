"""
Phase 2a.2 unit tests (no LLM).

Usage:
  python tests/test_phase2a2.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.document_store import put_bundle, resolve_agent_context  # noqa: E402
from agent.parse_documents import (  # noqa: E402
    build_planner_input_text,
    detect_combined_layout,
    find_split_idx,
    split_combined_text,
)
from agent.planner import (  # noqa: E402
    compute_plan_fingerprint,
    replan_with_answers,
)
from agent.sections_config import normalize  # noqa: E402


def test_sections_normalize():
    cfg = {
        "global": {"language": "python", "include_code": False},
        "sections": [
            {"id": "cover", "mode": "skip"},
            {"id": "result", "mode": "user_provided", "input": "我的实验结果正文"},
            {
                "id": "summary",
                "mode": "auto",
                "input": "末尾必须有：本实验由本人独立完成",
            },
        ],
    }
    norm = normalize(cfg)
    assert norm["fill_scope"]["sections"]["cover"] == "skip"
    assert norm["fill_scope"]["sections"]["result"] == "user_provided"
    assert "result" in norm["user_content"]
    assert len(norm["teacher_constraints"]["rules"]) >= 1


def test_combined_split():
    paragraphs = [
        "实验目的：理解进程调度",
        "实验要求：" + "x" * 250,
        "三、实验步骤",
        "请在此填写步骤",
        "四、实验结果",
    ]
    full_text = "\n".join(paragraphs)
    layout = detect_combined_layout(full_text, paragraphs)
    assert layout == "combined"
    idx = find_split_idx(paragraphs)
    assert idx == 2
    assign, fill, heading = split_combined_text(paragraphs, idx)
    assert "实验目的" in assign
    assert heading.startswith("三")
    assert "实验结果" in fill

    planner_text = build_planner_input_text(
        assignment_text=assign,
        fill_body_text=fill,
        layout="combined",
    )
    assert "【实验要求】" in planner_text
    assert "【待填报告" in planner_text


def test_fingerprint_sections_and_split():
    steps = [{"module": "solve_lab", "params": {}, "default_checked": True}]
    a = compute_plan_fingerprint(
        "text",
        steps,
        document_ids=["d1"],
        sections_config={"sections": []},
        split_idx=3,
    )
    b = compute_plan_fingerprint(
        "text",
        steps,
        document_ids=["d1"],
        sections_config={"sections": []},
        split_idx=4,
    )
    assert a != b


def test_parse_assignment_only_no_fill_target():
    from agent.parse_documents import parse_documents_list

    parsed = parse_documents_list(
        [
            {
                "id": "paste-only",
                "role": "assignment",
                "text_content": "实验项目二：创建型设计模式实验\n1. 简单工厂模式…\n2. 工厂方法模式…",
                "file_name": "粘贴的题目.txt",
            },
        ]
    )
    assert parsed["fill_target"] is None
    assert parsed["layout"] == "assignment_only"
    assert "创建型设计模式" in parsed["assignment_text"]
    assert parsed.get("question")


def test_parse_report_route_assignment_only_text():
    from server import app

    client = app.test_client()
    resp = client.post(
        "/api/parse-report",
        json={
            "documents": [
                {
                    "id": "paste-only",
                    "role": "assignment",
                    "text_content": "实验项目二：创建型设计模式实验\n要求完成简单工厂与工厂方法。",
                    "file_name": "粘贴的题目.txt",
                }
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["fill_target"] is None
    assert data["layout"] == "assignment_only"
    assert data["split_at_heading"] in (None, "")
    assert data["questions"]


SAMPLE_CLOZE_TEXT = """
public class MainControllerCenter {
    ( 1 ) MainControllerCenter instance;
    private ( 2 ) MainControllerCenter() {}
    public static MainControllerCenter getInstance() {
        if (instance == null) {
            instance = ( 3 ) MainControllerCenter();
        }
        return instance;
    }
}
""".strip()


def test_parse_assignment_only_code_cloze():
    from agent.parse_documents import parse_documents_list

    parsed = parse_documents_list(
        [
            {
                "id": "cloze-paste",
                "role": "assignment",
                "text_content": SAMPLE_CLOZE_TEXT,
                "file_name": "Singleton填空.txt",
            },
        ]
    )
    q = parsed["question"]
    assert q["type"] == "code_cloze"
    cloze = q["metadata"]["code_cloze"]
    assert cloze["is_code_cloze"] is True
    assert cloze["blank_count"] >= 3
    assert parsed["metadata"]["code_cloze"]["blank_count"] == cloze["blank_count"]


def test_parse_report_route_code_cloze():
    from server import app

    client = app.test_client()
    resp = client.post(
        "/api/parse-report",
        json={
            "documents": [
                {
                    "id": "cloze-paste",
                    "role": "assignment",
                    "text_content": SAMPLE_CLOZE_TEXT,
                    "file_name": "Singleton填空.txt",
                }
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["layout"] == "assignment_only"
    q = data["question"]
    assert q["type"] == "code_cloze"
    assert data["metadata"]["code_cloze"]["is_code_cloze"] is True
    assert data["metadata"]["code_cloze"]["blank_count"] >= 3
    assert data["questions"][0]["type"] == "code_cloze"


def test_parse_docx_code_cloze_singleton():
    """R5 / Phase D: Word import recognizes numbered blanks in table code blocks."""
    import base64

    from agent.parse_documents import parse_documents_list
    from modules.parse_report import build_question_from_document

    fixture = ROOT / "tests" / "fixtures" / "code_cloze_singleton.docx"
    if not fixture.exists():
        from tests.generate_fixtures import code_cloze_singleton

        code_cloze_singleton().save(fixture)

    q, qmeta, _, _ = build_question_from_document(fixture, fixture.name)
    assert q["type"] == "code_cloze"
    assert qmeta["code_cloze"]["is_code_cloze"] is True
    assert qmeta["code_cloze"]["blank_count"] >= 3
    assert qmeta.get("code_cloze_source") == "docx_code_segments"

    file_bytes = fixture.read_bytes()
    parsed = parse_documents_list(
        [
            {
                "id": "cloze-docx",
                "role": "assignment",
                "file_data": base64.b64encode(file_bytes).decode(),
                "file_name": fixture.name,
            },
        ]
    )
    assert parsed["question"]["type"] == "code_cloze"
    assert parsed["metadata"]["code_cloze"]["blank_count"] >= 3


def test_parse_docx_lab_report_not_code_cloze():
    """Ordinary lab report docx must stay lab_report (R5 regression)."""
    from modules.parse_report import build_question_from_document

    fixture = ROOT / "tests" / "fixtures" / "programming_lab.docx"
    if not fixture.exists():
        from tests.generate_fixtures import programming_lab

        programming_lab().save(fixture)

    q, qmeta, _, _ = build_question_from_document(fixture, fixture.name)
    assert q["type"] == "lab_report"
    assert "code_cloze" not in qmeta or not qmeta.get("code_cloze", {}).get("is_code_cloze")


def test_parse_report_route_docx_code_cloze():
    import base64

    from server import app

    fixture = ROOT / "tests" / "fixtures" / "code_cloze_singleton.docx"
    if not fixture.exists():
        from tests.generate_fixtures import code_cloze_singleton

        code_cloze_singleton().save(fixture)

    client = app.test_client()
    resp = client.post(
        "/api/parse-report",
        json={
            "documents": [
                {
                    "id": "cloze-docx",
                    "role": "assignment",
                    "file_data": base64.b64encode(fixture.read_bytes()).decode(),
                    "file_name": fixture.name,
                }
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["question"]["type"] == "code_cloze"
    assert data["metadata"]["code_cloze"]["blank_count"] >= 3
    assert data["questions"][0]["type"] == "code_cloze"


def test_parse_inline_text_with_fill_target():
    from agent.parse_documents import parse_documents_list

    parsed = parse_documents_list(
        [
            {
                "id": "paste-1",
                "role": "assignment",
                "text_content": "实验项目二：创建型设计模式实验\n1. 简单工厂模式…",
                "file_name": "粘贴的题目.txt",
            },
            {
                "id": "fill-1",
                "role": "fill_target",
                "text_content": "设计模式实验报告\n实验名：\n实验目的：\n实验内容：",
                "file_name": "空白模板.txt",
            },
        ]
    )
    assert "创建型设计模式" in parsed["assignment_text"]
    assert parsed["fill_target"] is not None
    assert "【实验要求】" in parsed["planner_input_text"]
    docs = parsed["documents"]
    assert any(d["role"] == "assignment" and d["format"] == "text" for d in docs)


def test_multi_doc_context():
    b1 = {
        "document_id": "a1",
        "role": "assignment",
        "report_text": "题目要求写代码",
        "full_text": "题目要求写代码",
        "metadata": {},
        "question": {},
        "warnings": [],
        "created_at": time.time(),
    }
    b2 = {
        "document_id": "f1",
        "role": "fill_target",
        "report_text": "三、实验步骤\n填空",
        "fill_body_text": "三、实验步骤\n填空",
        "full_text": "三、实验步骤\n填空",
        "metadata": {"course": "OS"},
        "question": {"type": "lab_report"},
        "warnings": [],
        "layout": "fill_only",
        "created_at": time.time(),
    }
    put_bundle(b1)
    put_bundle(b2)
    ctx = resolve_agent_context(["a1", "f1"])
    assert "题目要求" in ctx["assignment_text"]
    assert "实验步骤" in ctx["planner_input_text"]


def test_replan_clarify_uml():
    steps = [
        {
            "module": "solve_lab",
            "params": {},
            "default_checked": True,
            "confidence": "high",
        },
        {
            "module": "render_uml",
            "params": {},
            "default_checked": True,
            "confidence": "medium",
        },
    ]
    ctx = {
        "report_text": "需要类图",
        "document_ids": [],
        "plan": {"steps": steps},
        "decision_log": [],
        "user_profile": {},
    }
    plan = replan_with_answers(ctx, {"q_uml": "不需要"})
    mods = [s["module"] for s in plan["steps"]]
    assert "render_uml" not in mods


def main():
    test_sections_normalize()
    test_combined_split()
    test_fingerprint_sections_and_split()
    test_parse_inline_text_with_fill_target()
    test_multi_doc_context()
    test_replan_clarify_uml()
    print("test_phase2a2: OK")


if __name__ == "__main__":
    main()
