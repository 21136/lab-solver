"""
PDF text extraction via PyMuPDF (Phase 2b B5, IM3 page render).
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

from config import PDF_OK

_MIN_SCANNED_CHARS = 80
_RENDER_ZOOM = 2.0
_MIN_ASSIGNMENT_W_PX = 300
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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_pdf_pages(doc, *, max_pages: int = 0) -> list[dict[str, Any]]:
    """Render each PDF page to a PNG image asset (IM3 scanned-PDF path)."""
    import fitz

    assets: list[dict[str, Any]] = []
    mat = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
    limit = doc.page_count if not max_pages else min(doc.page_count, max_pages)

    for page_idx in range(limit):
        page = doc[page_idx]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        w_px, h_px = pix.width, pix.height
        role_guess = "assignment" if w_px >= _MIN_ASSIGNMENT_W_PX else "unknown"

        assets.append({
            "id": f"img_{len(assets) + 1:03d}",
            "source": "pdf_page_render",
            "order": len(assets),
            "page_hint": page_idx + 1,
            "mime": "image/png",
            "bytes_b64": base64.b64encode(png_bytes).decode(),
            "sha256": _sha256_hex(png_bytes),
            "width_px": w_px,
            "height_px": h_px,
            "nearby_text": f"PDF 第 {page_idx + 1} 页",
            "role_guess": role_guess,
            "ocr_text": "",
            "vision_summary": "",
        })
    return assets


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

        if len(full_text.strip()) < _MIN_SCANNED_CHARS and page_count:
            page_assets = render_pdf_pages(doc)
            metadata["image_assets"] = page_assets
            metadata["image_bundle_meta"] = {
                "total": len(page_assets),
                "deduped": len(page_assets),
                "extraction_warnings": [],
            }
            n_pages = len(page_assets)
            hints.append(
                {
                    "code": "pdf_scanned",
                    "message": (
                        f"疑似扫描版 PDF（几乎无文字层），已按页提取 {n_pages} 张图片"
                        "；将自动尝试 OCR 识别图中文字（需本机安装 Tesseract）"
                        "，也可在设置中开启「识别图片中的文字」"
                    ),
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
