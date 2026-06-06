"""
PDF text extraction via PyMuPDF (Phase 2b B5).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from config import PDF_OK

_MIN_SCANNED_CHARS = 80
_METADATA_PATTERNS = (
    ("course", re.compile(r"课程名称\s*[:：]?\s*(.+)", re.MULTILINE)),
    (
        "experiment_title",
        re.compile(r"(?:实验序号|实验名称)\s*[:：]?\s*(.+)", re.MULTILINE),
    ),
    ("major", re.compile(r"专业\s*[:：]?\s*(.+)", re.MULTILINE)),
    ("student_id", re.compile(r"学号\s*[:：]?\s*(\S+)", re.MULTILINE)),
    ("student_name", re.compile(r"姓名\s*[:：]?\s*(\S+)", re.MULTILINE)),
)


def _metadata_from_cover_text(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    head = (text or "")[:4000]
    for key, pat in _METADATA_PATTERNS:
        m = pat.search(head)
        if m:
            val = m.group(1).strip()
            if val and len(val) < 120:
                meta[key] = val
    return meta


def _page_blocks_sorted(page) -> list[tuple[float, float, str]]:
    """Return (y, x, text) tuples in reading order."""
    blocks = page.get_text("blocks") or []
    items: list[tuple[float, float, str]] = []
    for b in blocks:
        if len(b) < 5:
            continue
        text = (b[4] or "").strip()
        if not text:
            continue
        items.append((float(b[1]), float(b[0]), text))
    items.sort(key=lambda t: (round(t[0] / 8), t[1]))
    return items


def _maybe_multicolumn_warn(page, blocks: list[tuple[float, float, str]]) -> bool:
    if not blocks:
        return False
    width = float(page.rect.width) or 1.0
    left = sum(1 for _, x, _ in blocks if x < width * 0.38)
    right = sum(1 for _, x, _ in blocks if x > width * 0.58)
    return left >= 3 and right >= 3


def extract_pdf(path: Path | str) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    """
    Extract full text and metadata from a PDF.

    Returns (full_text, metadata, hints) where hints are parse-time notes
    (not the same shape as warnings[] — converted in parse_report).
    """
    path = Path(path)
    metadata: dict[str, Any] = {"source_format": "pdf"}
    hints: list[dict[str, str]] = []

    if not PDF_OK:
        return (
            "（无法读取 PDF，请更新解题能手到最新版，或联系发布方检查安装包）",
            metadata,
            [
                {
                    "code": "pdf_unavailable",
                    "message": "本机缺少 PDF 解析组件。安装版用户请更新应用；开发者请执行 pip install -r requirements.txt",
                }
            ],
        )

    import fitz

    doc = fitz.open(str(path))
    try:
        page_count = doc.page_count
        metadata["page_count"] = page_count

        lines: list[str] = []
        multicolumn_pages = 0
        for page in doc:
            blocks = _page_blocks_sorted(page)
            if _maybe_multicolumn_warn(page, blocks):
                multicolumn_pages += 1
            for _, _, text in blocks:
                for ln in text.splitlines():
                    stripped = ln.strip()
                    if stripped:
                        lines.append(stripped)

        full_text = "\n".join(lines)
        if page_count:
            cover = "\n".join(lines[:80])
            metadata.update(_metadata_from_cover_text(cover))

        if len(full_text.strip()) < _MIN_SCANNED_CHARS:
            hints.append(
                {
                    "code": "pdf_scanned",
                    "message": "疑似扫描版 PDF（几乎无文字层），请换 Word 或等待后续 OCR 支持",
                }
            )
        if multicolumn_pages >= 1:
            hints.append(
                {
                    "code": "pdf_multicolumn",
                    "message": "检测到可能的双栏版式，抽文顺序或与肉眼阅读不一致，请核对解析结果",
                }
            )
    finally:
        doc.close()

    return full_text, metadata, hints
