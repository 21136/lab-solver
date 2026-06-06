"""Build image_assets from Step1 user-uploaded assignment images (IM4)."""

from __future__ import annotations

import base64
import mimetypes
from typing import Any

from document.extract_images import _image_pixel_size, _sha256_hex

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _guess_mime(file_name: str, blob: bytes) -> str:
    ext = ""
    if file_name and "." in file_name:
        ext = "." + file_name.rsplit(".", 1)[-1].lower()
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    guessed, _ = mimetypes.guess_type(file_name or "image.png")
    return guessed or "image/png"


def build_user_upload_assets(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert UI payload items to image_assets[] with stable user order + sha256 dedup."""
    indexed = list(enumerate(items or []))
    indexed.sort(key=lambda pair: pair[1].get("order", pair[0]))

    image_assets: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    total = 0
    warnings: list[dict[str, str]] = []

    for orig_idx, item in indexed:
        total += 1
        b64 = (item.get("file_data") or "").strip()
        if not b64:
            warnings.append({
                "code": "user_upload_missing_bytes",
                "message": f"题目图片 {item.get('file_name') or orig_idx + 1} 缺少数据，已跳过",
            })
            continue
        try:
            blob = base64.b64decode(b64)
        except Exception:
            warnings.append({
                "code": "user_upload_invalid_base64",
                "message": f"题目图片 {item.get('file_name') or orig_idx + 1} 数据无效，已跳过",
            })
            continue
        if not blob:
            continue

        sha = _sha256_hex(blob)
        if sha in seen_hashes:
            continue
        seen_hashes.add(sha)

        file_name = item.get("file_name") or f"assignment_{orig_idx + 1}.png"
        w_px, h_px = _image_pixel_size(blob)
        include_in_ocr = item.get("include_in_ocr")
        if include_in_ocr is None:
            include_in_ocr = item.get("includeOcr")
        if include_in_ocr is None:
            include_in_ocr = True

        image_assets.append({
            "id": f"img_{len(image_assets) + 1:03d}",
            "source": "user_upload",
            "order": len(image_assets),
            "page_hint": len(image_assets) + 1,
            "mime": _guess_mime(file_name, blob),
            "bytes_b64": base64.b64encode(blob).decode(),
            "sha256": sha,
            "width_px": w_px,
            "height_px": h_px,
            "nearby_text": (item.get("label") or file_name)[:200],
            "role_guess": "assignment",
            "include_in_ocr": bool(include_in_ocr),
            "client_id": item.get("id") or item.get("client_id") or "",
            "ocr_text": "",
            "vision_summary": "",
        })

    if total > len(image_assets):
        warnings.append({
            "code": "user_upload_deduped",
            "message": f"题目图片组 {total} 张，去重后保留 {len(image_assets)} 张",
        })

    return {
        "image_assets": image_assets,
        "image_bundle_meta": {
            "total": total,
            "deduped": len(image_assets),
            "extraction_warnings": warnings,
            "source": "user_upload",
        },
    }


def process_user_upload_images(
    items: list[dict[str, Any]],
    *,
    enable_image_ocr: bool = False,
    ocr_lang: str = "chi_sim+eng",
    ocr_max_pages: int = 20,
    body_text: str = "",
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = 5,
    llm_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build assets, run IM2 OCR pipeline, return merge fields for parse/planner."""
    from document.image_read import apply_image_reading

    built = build_user_upload_assets(items)
    image_assets = built.get("image_assets") or []
    bundle_meta = built.get("image_bundle_meta") or {}
    warnings: list[dict[str, str]] = list(bundle_meta.get("extraction_warnings") or [])

    if not image_assets:
        return {
            "image_assets": [],
            "image_bundle_meta": bundle_meta,
            "warnings": warnings,
            "assignment_text": (body_text or "").strip(),
            "assignment_from_images": False,
            "image_reading_mode": "",
            "image_sections": [],
            "image_read_summary": None,
            "image_ocr_merged": "",
            "document_assignment_text": (body_text or "").strip(),
        }

    metadata: dict[str, Any] = {
        "image_assets": image_assets,
        "image_bundle_meta": bundle_meta,
        "source_format": "user_upload",
    }
    ocr_warnings, image_read = apply_image_reading(
        body_text,
        metadata,
        enable_image_ocr=enable_image_ocr,
        ocr_lang=ocr_lang,
        ocr_max_pages=ocr_max_pages,
        hints=[],
        image_reading_mode=image_reading_mode,
        vision_max_pages=vision_max_pages,
        llm_settings=llm_settings,
    )
    warnings.extend(ocr_warnings)

    assignment_text = image_read.get("document_assignment_text") or (body_text or "").strip()
    return {
        "image_assets": metadata.get("image_assets") or image_assets,
        "image_bundle_meta": metadata.get("image_bundle_meta") or bundle_meta,
        "warnings": warnings,
        "assignment_text": assignment_text,
        "assignment_from_images": bool(image_read.get("assignment_from_images")),
        "image_reading_mode": image_read.get("image_reading_mode") or "",
        "image_sections": image_read.get("image_sections") or [],
        "image_read_summary": image_read.get("image_read_summary"),
        "image_ocr_merged": image_read.get("image_ocr_merged") or "",
        "document_assignment_text": assignment_text,
    }
