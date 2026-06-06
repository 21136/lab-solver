"""Extract embedded images from docx files (IM1).

Walks document body elements in document order, extracts image blobs,
computes SHA-256 for dedup, guesses role from nearby text + dimensions.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from config import DOCX_OK

# XML namespaces
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# ── Role-guessing heuristics ──────────────────────────────────────────
_SIGNATURE_W_PX = 200
_SIGNATURE_H_PX = 80
_DECORATION_W_PX = 50
_DECORATION_H_PX = 50
_MIN_ASSIGNMENT_W_PX = 300

_ASSIGNMENT_KW = (
    "实验目的", "实验要求", "题目", "要求", "原理", "电路",
    "流程图", "接线图", "数据表", "曲线", "波形", "图",
)
_SIGNATURE_KW = ("签名", "盖章", "签字")
_DECORATION_KW = ("logo", "Logo", "校徽", "图标")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_pixel_size(blob: bytes) -> tuple[int, int]:
    try:
        import io
        from PIL import Image

        with Image.open(io.BytesIO(blob)) as img:
            return img.size
    except Exception:
        return (0, 0)


def _guess_role(nearby_text: str, w_px: int, h_px: int) -> str:
    text = nearby_text or ""
    for kw in _SIGNATURE_KW:
        if kw in text:
            return "signature"
    for kw in _DECORATION_KW:
        if kw in text:
            return "decoration"
    # Check smaller threshold first: tiny = decoration, small = signature
    if 0 < w_px < _DECORATION_W_PX and 0 < h_px < _DECORATION_H_PX:
        return "decoration"
    if 0 < w_px < _SIGNATURE_W_PX and 0 < h_px < _SIGNATURE_H_PX:
        return "signature"
    for kw in _ASSIGNMENT_KW:
        if kw in text:
            return "assignment"
    if w_px >= _MIN_ASSIGNMENT_W_PX:
        return "assignment"
    return "unknown"


def _body_texts(body_children: list, max_children: int = 0) -> list[str]:
    """Pre-compute text content for each body child element."""
    texts: list[str] = []
    for child in body_children[:max_children] if max_children else body_children:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in ("p", "tbl"):
            t_elms = child.findall(f".//{{{W_NS}}}t")
            texts.append("".join(t.text or "" for t in t_elms).strip())
        else:
            texts.append("")
    return texts


def _nearby_text(element_texts: list[str], ei: int, radius: int = 2) -> str:
    parts = []
    for offset in range(-radius, radius + 1):
        idx = ei + offset
        if 0 <= idx < len(element_texts) and idx != ei:
            t = element_texts[idx]
            if t:
                parts.append(t)
    return "\n".join(parts)


def extract_docx_images(path: Path | str) -> dict[str, Any]:
    """Enumerate all embedded images from a docx file in document order.

    Returns:
        {"image_assets": [...], "image_bundle_meta": {...}}
    """
    if not DOCX_OK:
        return {
            "image_assets": [],
            "image_bundle_meta": {
                "total": 0,
                "deduped": 0,
                "extraction_warnings": [
                    {"code": "docx_unavailable", "message": "python-docx 未安装"}
                ],
            },
        }

    from docx import Document

    try:
        doc = Document(str(path))
    except Exception as e:
        return {
            "image_assets": [],
            "image_bundle_meta": {
                "total": 0,
                "deduped": 0,
                "extraction_warnings": [
                    {"code": "docx_open_failed", "message": str(e)}
                ],
            },
        }

    body_children = list(doc.element.body)
    elem_texts = _body_texts(body_children)

    image_assets: list[dict] = []
    seen_hashes: set[str] = set()
    total_blips = 0

    for ei, child in enumerate(body_children):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag not in ("p", "tbl"):
            continue

        blips = child.findall(f".//{{{A_NS}}}blip")
        if not blips:
            continue

        nearby = _nearby_text(elem_texts, ei)

        for blip in blips:
            total_blips += 1
            embed = blip.get(f"{{{R_NS}}}embed")
            if not embed:
                continue

            part = doc.part.related_parts.get(embed)
            if part is None:
                continue

            blob = part.blob
            sha = _sha256_hex(blob)
            if sha in seen_hashes:
                continue
            seen_hashes.add(sha)

            mime = getattr(part, "content_type", "image/png")
            w_px, h_px = _image_pixel_size(blob)
            role_guess = _guess_role(nearby, w_px, h_px)
            page_hint = (ei // 25) + 1

            image_assets.append({
                "id": f"img_{len(image_assets) + 1:03d}",
                "source": "docx_inline",
                "order": len(image_assets),
                "page_hint": page_hint,
                "mime": mime,
                "bytes_b64": base64.b64encode(blob).decode(),
                "sha256": sha,
                "width_px": w_px,
                "height_px": h_px,
                "nearby_text": nearby[:500],
                "role_guess": role_guess,
                "ocr_text": "",
                "vision_summary": "",
            })

    warnings: list[dict] = []
    if total_blips > 0 and len(image_assets) < total_blips:
        warnings.append({
            "code": "images_deduped",
            "message": f"发现 {total_blips} 处图片引用，去重后保留 {len(image_assets)} 张",
        })

    return {
        "image_assets": image_assets,
        "image_bundle_meta": {
            "total": total_blips,
            "deduped": len(image_assets),
            "extraction_warnings": warnings,
        },
    }
