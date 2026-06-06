"""Lab-solver capability modules (Phase 1.1)."""

from . import deliverable, fill_report, lab_parse, parse_report, run_code, screenshot, solve_lab, solve_pipeline, uml
from .fill_report import do_fill
from .parse_report import (
    build_question_from_docx,
    build_question_from_document,
    collect_parse_warnings,
    document_format,
    extract_docx,
    extract_document_paragraphs,
    is_legacy_doc,
    is_pdf,
    parse_document,
)
from .run_code import execute_code, get_java_exe, java_status_info

__all__ = [
    "parse_report",
    "solve_lab",
    "run_code",
    "screenshot",
    "uml",
    "deliverable",
    "fill_report",
    "lab_parse",
    "extract_docx",
    "parse_document",
    "build_question_from_docx",
    "build_question_from_document",
    "extract_document_paragraphs",
    "document_format",
    "is_pdf",
    "collect_parse_warnings",
    "is_legacy_doc",
    "execute_code",
    "get_java_exe",
    "java_status_info",
    "do_fill",
]
