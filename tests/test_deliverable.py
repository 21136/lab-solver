"""V5 LabDeliverable assembly and export tests."""

import base64
import sys
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from config import DOCX_OK  # noqa: E402
from modules.deliverable import (  # noqa: E402
    build_deliverable,
    deliverable_code_zip_bytes,
    deliverable_diagrams_zip_bytes,
    deliverable_to_docx,
    deliverable_to_markdown,
    ensure_deliverable_provenance,
    export_deliverable,
    is_content_only_output_mode,
)


def _sample_ctx(*, provenance_label: bool = False, custom_label: str = ""):
    ctx = {
        "output_mode": "deliverable",
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {
                    "language": "python",
                    "code": "print('hi')",
                    "parsed": {
                        "steps_analysis": "步骤思路",
                        "result_description": "运行输出 hi",
                        "summary": "总结",
                        "code": "print('hi')",
                    },
                },
            },
        },
    }
    if provenance_label:
        ctx["user_constraints"] = ["provenance_label"]
    if custom_label:
        ctx["provenance_custom_label"] = custom_label
    return ctx


def test_is_content_only_output_mode():
    assert is_content_only_output_mode("deliverable")
    assert is_content_only_output_mode("answer_only")
    assert not is_content_only_output_mode("fill_original")


def test_build_deliverable_sections():
    dlv = build_deliverable(_sample_ctx())
    assert dlv["sections"]["steps_analysis"] == "步骤思路"
    assert dlv["sections"]["result_description"] == "运行输出 hi"
    assert dlv["code"]["files"][0]["code"] == "print('hi')"
    assert dlv["execution"]["validation_status"] in ("skipped", "not_requested")
    assert dlv["provenance"]["ai_assisted"] is True
    assert len(dlv["provenance"]["integrity_hash"]) == 16


def test_build_deliverable_provenance_label():
    dlv = build_deliverable(_sample_ctx(provenance_label=True))
    assert dlv["provenance"]["custom_label"] == "内容由 AI 辅助生成，本人已核对"
    dlv2 = build_deliverable(_sample_ctx(provenance_label=True, custom_label="本人已核对"))
    assert dlv2["provenance"]["custom_label"] == "本人已核对"


def test_deliverable_to_markdown():
    dlv = build_deliverable(_sample_ctx())
    md = deliverable_to_markdown(dlv)
    assert "## 实验步骤" in md or "步骤" in md
    assert "print('hi')" in md
    assert "验证状态" in md
    assert dlv["provenance"]["integrity_hash"] in md


def test_deliverable_markdown_provenance_footer():
    dlv = build_deliverable(_sample_ctx(provenance_label=True, custom_label="AI 辅助"))
    md = deliverable_to_markdown(dlv, include_footer=True)
    assert "AI 辅助" in md
    assert "本报告内容由 AI 辅助生成" in md


def test_ensure_deliverable_provenance():
    partial = {
        "sections": {"summary": "x"},
        "code": {"language": "python", "files": [{"name": "a.py", "code": "pass"}], "main_file": "a.py"},
        "diagrams": [],
    }
    enriched = ensure_deliverable_provenance(partial)
    assert len(enriched["provenance"]["integrity_hash"]) == 16


def test_deliverable_code_zip():
    dlv = build_deliverable(_sample_ctx())
    data = deliverable_code_zip_bytes(dlv)
    with zipfile.ZipFile(BytesIO(data), "r") as zf:
        names = zf.namelist()
        assert names
        assert "print('hi')" in zf.read(names[0]).decode("utf-8")


def test_deliverable_diagrams_zip():
    dlv = build_deliverable(_sample_ctx())
    dlv["diagrams"] = [{"title": "流程图", "image_b64": base64.b64encode(b"png-bytes").decode("ascii")}]
    data, n = deliverable_diagrams_zip_bytes(dlv)
    assert n == 1
    with zipfile.ZipFile(BytesIO(data), "r") as zf:
        assert zf.namelist()[0].endswith(".png")
        assert zf.read(zf.namelist()[0]) == b"png-bytes"


def test_export_deliverable_docx():
    if not DOCX_OK:
        return
    dlv = build_deliverable(_sample_ctx(provenance_label=True))
    payload = export_deliverable(dlv, "docx")
    assert payload["file_b64"]
    assert payload["filename"].endswith(".docx")
    raw = base64.b64decode(payload["file_b64"])
    assert raw[:2] == b"PK"


def test_export_deliverable_formats():
    dlv = build_deliverable(_sample_ctx())
    j = export_deliverable(dlv, "json")
    assert j["deliverable"]["id"] == dlv["id"]
    m = export_deliverable(dlv, "markdown")
    assert "print('hi')" in m["markdown"]
    z = export_deliverable(dlv, "code_zip")
    assert z["mime_type"] == "application/zip"


def main():
    test_is_content_only_output_mode()
    test_build_deliverable_sections()
    test_build_deliverable_provenance_label()
    test_deliverable_to_markdown()
    test_deliverable_markdown_provenance_footer()
    test_ensure_deliverable_provenance()
    test_deliverable_code_zip()
    test_deliverable_diagrams_zip()
    if DOCX_OK:
        test_export_deliverable_docx()
    else:
        print("skip docx: python-docx not installed")
    test_export_deliverable_formats()
    print("test_deliverable: OK")


if __name__ == "__main__":
    main()
