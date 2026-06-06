"""
Phase 2b B5 — PDF parse (no LLM).

Usage:
  python tests/test_phase2b5_pdf.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from config import PDF_OK, TEMP_DIR  # noqa: E402
from agent.parse_documents import parse_single_file  # noqa: E402
from modules.parse_report import (  # noqa: E402
    build_question_from_document,
    document_format,
    is_pdf,
    parse_document,
)


def _make_sample_pdf(path: Path) -> None:
    if not PDF_OK:
        return
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    # Latin-only sample: default PDF font lacks CJK glyphs in synthetic PDFs.
    text = (
        "Course: Computer Networks\n"
        "Experiment: Wireshark Capture Lab\n"
        "Section 3 - Lab Steps\n"
        "1. Install Wireshark\n"
        "Section 4 - Results\n"
        "(to be filled)\n"
        "Section 5 - Summary\n"
        "(to be filled)\n"
    )
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()


def test_document_format():
    assert is_pdf("report.PDF")
    assert document_format("a.pdf") == "pdf"
    assert document_format("a.docx") == "docx"


def test_parse_document_pdf():
    if not PDF_OK:
        print("SKIP: pymupdf not installed")
        return
    path = TEMP_DIR / "test_phase2b5_sample.pdf"
    _make_sample_pdf(path)
    full_text, metadata, hints = parse_document(path, "test.pdf")
    assert metadata.get("source_format") == "pdf"
    assert "Wireshark" in full_text
    assert metadata.get("source_format") == "pdf"

    q, meta, text, warnings = build_question_from_document(path, "test.pdf")
    assert q["type"] == "lab_report"
    assert meta.get("source_format") == "pdf"
    assert len(text) > 50
    codes = {w.get("code") for w in warnings if isinstance(w, dict)}
    assert "pdf_scanned" not in codes


def test_parse_single_file_pdf_bundle():
    if not PDF_OK:
        print("SKIP: pymupdf not installed")
        return
    path = TEMP_DIR / "test_phase2b5_bundle.pdf"
    _make_sample_pdf(path)
    bundle = parse_single_file(path.read_bytes(), "bundle.pdf", role="fill_target")
    assert bundle["metadata"]["source_format"] == "pdf"
    assert "Wireshark" in bundle["planner_input_text"]
    assert bundle["role"] == "fill_target"


def main():
    test_document_format()
    test_parse_document_pdf()
    test_parse_single_file_pdf_bundle()
    print("test_phase2b5_pdf: OK")


if __name__ == "__main__":
    main()
