"""Local OCR + optional Vision for embedded images (IM2-a / IM5).

Tesseract via pytesseract when available; Vision via llm_client when hybrid/vision mode.
"""

from __future__ import annotations

import base64
import io
import re
from typing import Any

from config import OCR_OK, PIL_OK

DEFAULT_OCR_LANG = "chi_sim+eng"
DEFAULT_PSM = 6
LOW_CONFIDENCE_THRESHOLD = 0.45
MAX_IMAGE_WIDTH_PX = 2000
DEFAULT_VISION_MAX_PAGES = 5
_SKIP_ROLES = frozenset({"signature", "decoration"})
_OCR_ELIGIBLE_ROLES = frozenset({"assignment", "unknown"})
_OCR_SEPARATOR = "\n\n--- 图 {order}（OCR）---\n\n"
_VISION_SEPARATOR = "\n\n--- 图 {order} ---\n\n"
_VISION_FALLBACK_STATUSES = frozenset({"empty", "low_confidence", "failed"})


def _preprocess_image(blob: bytes) -> Any:
    """Grayscale, autocontrast, max-width resize (Tier 2 minimal)."""
    if not PIL_OK:
        return blob
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(blob)) as img:
        img = img.convert("L")
        img = ImageOps.autocontrast(img)
        w, h = img.size
        if w > MAX_IMAGE_WIDTH_PX:
            ratio = MAX_IMAGE_WIDTH_PX / w
            img = img.resize((MAX_IMAGE_WIDTH_PX, max(1, int(h * ratio))), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _mean_confidence(data: dict) -> float:
    confs = data.get("conf") or []
    nums = []
    for c in confs:
        try:
            v = float(c)
            if v >= 0:
                nums.append(v)
        except (TypeError, ValueError):
            continue
    if not nums:
        return 0.0
    return sum(nums) / len(nums) / 100.0


def ocr_image_asset(
    asset: dict[str, Any],
    *,
    lang: str = DEFAULT_OCR_LANG,
    psm: int = DEFAULT_PSM,
) -> dict[str, Any]:
    """Run OCR on one image asset; return OCR metadata fields."""
    out: dict[str, Any] = {
        "ocr_text": "",
        "ocr_confidence": 0.0,
        "ocr_status": "pending",
        "ocr_engine": "tesseract",
        "ocr_lang": lang,
        "ocr_error": "",
    }
    if not OCR_OK:
        out["ocr_status"] = "skipped"
        out["ocr_error"] = "tesseract_unavailable"
        return out

    b64 = asset.get("bytes_b64") or ""
    if not b64:
        out["ocr_status"] = "failed"
        out["ocr_error"] = "missing_image_bytes"
        return out

    try:
        import pytesseract

        blob = base64.b64decode(b64)
        processed = _preprocess_image(blob)
        config = f"--psm {psm}"
        text = pytesseract.image_to_string(processed, lang=lang, config=config)
        text = (text or "").strip()
        try:
            data = pytesseract.image_to_data(
                processed, lang=lang, config=config, output_type=pytesseract.Output.DICT
            )
            confidence = _mean_confidence(data)
        except Exception:
            confidence = 0.5 if text else 0.0

        out["ocr_text"] = text
        out["ocr_confidence"] = round(confidence, 3)
        if not text:
            out["ocr_status"] = "empty"
        elif confidence < LOW_CONFIDENCE_THRESHOLD:
            out["ocr_status"] = "low_confidence"
        else:
            out["ocr_status"] = "ok"
    except Exception as e:
        out["ocr_status"] = "failed"
        out["ocr_error"] = str(e)[:300]
    return out


def _select_ocr_targets(
    image_assets: list[dict[str, Any]],
    *,
    enable_image_ocr: bool,
    body_len: int,
    pdf_scanned: bool,
) -> list[dict[str, Any]]:
    """Pick images to OCR per IM_OCR_FIRST §6."""
    eligible = [
        img
        for img in image_assets
        if img.get("include_in_ocr", True) is not False
        and (
            (img.get("role_guess") or "unknown") in _OCR_ELIGIBLE_ROLES
            or (enable_image_ocr and (img.get("role_guess") or "") not in _SKIP_ROLES)
        )
    ]
    if not eligible:
        return []

    if enable_image_ocr or pdf_scanned:
        return eligible

    # Auto OCR assignment images when body is very short
    if body_len < 80:
        assignment_only = [
            img for img in eligible if img.get("role_guess") == "assignment"
        ]
        if assignment_only:
            return assignment_only

    return []


def should_run_ocr(
    body_len: int,
    image_assets: list[dict[str, Any]],
    *,
    enable_image_ocr: bool = False,
    hints: list[dict[str, str]] | None = None,
) -> bool:
    pdf_scanned = any(
        isinstance(h, dict) and h.get("code") == "pdf_scanned" for h in (hints or [])
    )
    return bool(
        _select_ocr_targets(
            image_assets,
            enable_image_ocr=enable_image_ocr,
            body_len=body_len,
            pdf_scanned=pdf_scanned,
        )
    )


def ocr_batch(
    image_assets: list[dict[str, Any]],
    *,
    lang: str = DEFAULT_OCR_LANG,
    max_pages: int = 20,
    enable_image_ocr: bool = False,
    body_len: int = 0,
    hints: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """OCR selected assets in order; dedupe by sha256. Mutates assets in place."""
    pdf_scanned = any(
        isinstance(h, dict) and h.get("code") == "pdf_scanned" for h in (hints or [])
    )
    targets = _select_ocr_targets(
        image_assets,
        enable_image_ocr=enable_image_ocr,
        body_len=body_len,
        pdf_scanned=pdf_scanned,
    )
    summary: dict[str, Any] = {
        "ocr_attempted": 0,
        "ocr_ok": 0,
        "ocr_empty": 0,
        "ocr_low_confidence": 0,
        "ocr_failed": 0,
        "ocr_skipped": 0,
        "merged_chars": 0,
    }
    if not targets:
        return image_assets, summary

    if not OCR_OK:
        for img in image_assets:
            if img in targets:
                ocr = ocr_image_asset(img, lang=lang)
                img.update(ocr)
                summary["ocr_skipped"] += 1
        return image_assets, summary

    sha_cache: dict[str, dict[str, Any]] = {}
    attempted = 0

    for img in image_assets:
        role = img.get("role_guess") or "unknown"
        if img not in targets:
            if role in _SKIP_ROLES:
                img.update({
                    "ocr_status": "skipped",
                    "ocr_engine": "tesseract",
                    "ocr_lang": lang,
                    "ocr_text": img.get("ocr_text") or "",
                    "ocr_confidence": img.get("ocr_confidence") or 0.0,
                    "ocr_error": "",
                })
            continue

        if attempted >= max_pages:
            img.update({
                "ocr_status": "skipped",
                "ocr_error": "max_pages_exceeded",
                "ocr_engine": "tesseract",
                "ocr_lang": lang,
            })
            summary["ocr_skipped"] += 1
            continue

        attempted += 1
        summary["ocr_attempted"] += 1
        sha = img.get("sha256") or ""
        if sha and sha in sha_cache:
            cached = sha_cache[sha]
            img.update(dict(cached))
        else:
            ocr = ocr_image_asset(img, lang=lang)
            img.update(ocr)
            if sha:
                sha_cache[sha] = dict(ocr)

        status = img.get("ocr_status") or ""
        if status == "ok":
            summary["ocr_ok"] += 1
        elif status == "empty":
            summary["ocr_empty"] += 1
        elif status == "low_confidence":
            summary["ocr_low_confidence"] += 1
            summary["ocr_ok"] += 1
        elif status == "failed":
            summary["ocr_failed"] += 1
        elif status == "skipped":
            summary["ocr_skipped"] += 1

    return image_assets, summary


def _section_text(asset: dict[str, Any]) -> str:
    ocr = (asset.get("ocr_text") or "").strip()
    vision = (asset.get("vision_summary") or "").strip()
    status = asset.get("ocr_status") or ""
    if ocr and status in ("ok", "low_confidence"):
        text = ocr
        source = "ocr"
    elif vision:
        text = vision
        source = "vision"
    elif ocr:
        text = ocr
        source = "ocr"
    else:
        return "", "none"
    nearby = (asset.get("nearby_text") or "").strip()
    if nearby:
        return f"[上下文：{nearby[:200]}]\n{text}", source
    return text, source


def _select_vision_targets(
    image_assets: list[dict[str, Any]],
    *,
    reading_mode: str,
) -> list[dict[str, Any]]:
    """Pick images for Vision per IM5 hybrid/vision rules."""
    mode = (reading_mode or "ocr_only").strip().lower()
    if mode not in ("hybrid", "vision"):
        return []

    eligible = [
        img
        for img in image_assets
        if img.get("include_in_ocr", True) is not False
        and (img.get("role_guess") or "unknown") not in _SKIP_ROLES
    ]
    if not eligible:
        return []

    if mode == "vision":
        return eligible

    return [
        img
        for img in eligible
        if (img.get("ocr_status") or "") in _VISION_FALLBACK_STATUSES
        or not (img.get("ocr_text") or "").strip()
    ]


def vision_image_asset(
    asset: dict[str, Any],
    settings: dict[str, Any],
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Run Vision on one image asset; return vision metadata fields."""
    from llm_client import VISION_ASSIGNMENT_PROMPT, chat_vision

    out: dict[str, Any] = {
        "vision_summary": "",
        "vision_status": "pending",
        "vision_error": "",
    }
    b64 = asset.get("bytes_b64") or ""
    if not b64:
        out["vision_status"] = "failed"
        out["vision_error"] = "missing_image_bytes"
        return out

    try:
        result = chat_vision(
            settings,
            image_b64=b64,
            prompt=prompt or VISION_ASSIGNMENT_PROMPT,
            mime=asset.get("mime") or "image/png",
            phase="vision_read",
        )
        text = (result.get("content") or "").strip()
        if text in ("（无文字）", "(无文字)", "(no text)", "无文字"):
            text = ""
        out["vision_summary"] = text
        out["vision_status"] = "ok" if text else "empty"
    except Exception as e:
        out["vision_status"] = "failed"
        out["vision_error"] = str(e)[:300]
    return out


def vision_batch(
    image_assets: list[dict[str, Any]],
    *,
    settings: dict[str, Any] | None = None,
    reading_mode: str = "ocr_only",
    max_pages: int = DEFAULT_VISION_MAX_PAGES,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    """Vision selected assets in order; dedupe by sha256. Mutates assets in place."""
    from llm_client import supports_vision

    summary: dict[str, Any] = {
        "vision_attempted": 0,
        "vision_ok": 0,
        "vision_empty": 0,
        "vision_failed": 0,
        "vision_skipped": 0,
        "vision_limit_exceeded": 0,
    }
    warnings: list[dict[str, str]] = []
    targets = _select_vision_targets(image_assets, reading_mode=reading_mode)
    if not targets:
        return image_assets, summary, warnings

    llm_settings = settings or {}
    if not supports_vision(llm_settings):
        warnings.append({
            "code": "vision_unavailable",
            "message": "当前模型不支持多模态识图，已跳过 Vision；请换 Vision 模型或粘贴题目",
        })
        for img in targets:
            img.update({
                "vision_status": "skipped",
                "vision_error": "model_not_vision_capable",
            })
            summary["vision_skipped"] += 1
        return image_assets, summary, warnings

    if not (llm_settings.get("api_key") or llm_settings.get("apiKey")):
        warnings.append({
            "code": "vision_no_api_key",
            "message": "混合/仅 Vision 识图需要 API Key，已跳过 Vision 调用",
        })
        for img in targets:
            img.update({
                "vision_status": "skipped",
                "vision_error": "missing_api_key",
            })
            summary["vision_skipped"] += 1
        return image_assets, summary, warnings

    sha_cache: dict[str, dict[str, Any]] = {}
    attempted = 0
    limit_warned = False

    for img in image_assets:
        if img not in targets:
            continue

        if attempted >= max_pages:
            img.update({
                "vision_status": "skipped",
                "vision_error": "vision_max_pages_exceeded",
            })
            summary["vision_skipped"] += 1
            summary["vision_limit_exceeded"] += 1
            if not limit_warned:
                limit_warned = True
                warnings.append({
                    "code": "vision_limit_exceeded",
                    "message": (
                        f"Vision 识图已达上限 {max_pages} 张，"
                        "请缩小题目图范围或提高设置中的 Vision 张数上限"
                    ),
                    "vision_max_pages": str(max_pages),
                })
            continue

        attempted += 1
        summary["vision_attempted"] += 1
        sha = img.get("sha256") or ""
        if sha and sha in sha_cache:
            cached = sha_cache[sha]
            img.update(dict(cached))
        else:
            vision = vision_image_asset(img, llm_settings)
            img.update(vision)
            if sha:
                sha_cache[sha] = dict(vision)

        status = img.get("vision_status") or ""
        if status == "ok":
            summary["vision_ok"] += 1
        elif status == "empty":
            summary["vision_empty"] += 1
        elif status == "failed":
            summary["vision_failed"] += 1
        elif status == "skipped":
            summary["vision_skipped"] += 1

    return image_assets, summary, warnings


_MULTI_Q_PATTERNS = (
    re.compile(r"(?:^|\n)\s*[一二三四五六七八九十]+[、．.．]"),
    re.compile(r"(?:^|\n)\s*\d+[、．.)）]"),
    re.compile(r"(?:^|\n)\s*(?:问题|题目|实验)\s*\d+"),
)


def detect_multi_question_in_image(text: str) -> bool:
    """Heuristic: one image OCR/Vision text may contain multiple numbered questions."""
    body = (text or "").strip()
    if len(body) < 24:
        return False
    hits = sum(len(p.findall(body)) for p in _MULTI_Q_PATTERNS)
    return hits >= 2


def multi_question_image_warnings(
    image_sections: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Warn when a single image section looks like multiple questions (no auto-split)."""
    warnings: list[dict[str, str]] = []
    for sec in image_sections:
        txt = (sec.get("text") or "").strip()
        if not detect_multi_question_in_image(txt):
            continue
        img_id = sec.get("image_id") or "?"
        warnings.append({
            "code": "multi_question_in_image",
            "message": (
                f"图 {img_id} 的识别文字可能含多道题，"
                "v2 不会自动拆分；请在识题预览中手动分节或删减"
            ),
            "image_id": str(img_id),
        })
    return warnings


def merge_assignment_from_images(
    body_text: str,
    image_assets: list[dict[str, Any]],
    *,
    only_with_text: bool = True,
) -> dict[str, Any]:
    """Merge OCR/Vision segments into assignment text per §4.1 / IM5."""
    sections: list[dict[str, Any]] = []
    parts: list[str] = []

    merge_assets = [
        a for a in image_assets if a.get("include_in_ocr", True) is not False
    ]
    for asset in sorted(merge_assets, key=lambda a: a.get("order", 0)):
        text, source = _section_text(asset)
        if only_with_text and not text:
            continue
        order = asset.get("order", len(parts))
        sep = _OCR_SEPARATOR if source == "ocr" else _VISION_SEPARATOR
        parts.append(sep.format(order=order + 1) + text)
        sections.append({
            "image_id": asset.get("id") or f"img_{order + 1:03d}",
            "text": text,
            "source": source,
        })

    ocr_merged = "\n".join(parts).strip()
    body = (body_text or "").strip()
    if body and ocr_merged:
        assignment_text = body + "\n\n" + ocr_merged
    elif ocr_merged:
        assignment_text = ocr_merged
    else:
        assignment_text = body

    return {
        "assignment_text": assignment_text,
        "image_sections": sections,
        "assignment_from_images": bool(sections),
        "image_ocr_merged": ocr_merged,
        "merged_chars": len(ocr_merged),
    }


def apply_image_reading(
    full_text: str,
    metadata: dict[str, Any],
    *,
    enable_image_ocr: bool = False,
    ocr_lang: str = DEFAULT_OCR_LANG,
    ocr_max_pages: int = 20,
    hints: list[dict[str, str]] | None = None,
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = DEFAULT_VISION_MAX_PAGES,
    llm_settings: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Run OCR (+ optional Vision) pipeline; update metadata.image_assets."""
    image_assets: list[dict[str, Any]] = list(metadata.get("image_assets") or [])
    body_len = len((full_text or "").strip())
    extra_warnings: list[dict[str, str]] = []
    reading_mode = (image_reading_mode or "ocr_only").strip().lower()
    if reading_mode not in ("ocr_only", "hybrid", "vision"):
        reading_mode = "ocr_only"

    if not image_assets:
        return extra_warnings, {}

    run_ocr = should_run_ocr(
        body_len,
        image_assets,
        enable_image_ocr=enable_image_ocr,
        hints=hints,
    )
    run_vision = reading_mode == "vision" and bool(
        _select_vision_targets(image_assets, reading_mode="vision")
    )
    run_hybrid_vision = reading_mode == "hybrid" and run_ocr

    if not run_ocr and not run_vision:
        if (
            body_len < MIN_BODY_CHARS_FOR_WARN
            and image_assets
            and not enable_image_ocr
        ):
            extra_warnings.append({
                "code": "ocr_suggested",
                "message": "正文较短且含嵌入图片，可启用「识别图片中的文字」以 OCR 题目",
            })
        return extra_warnings, {}

    summary: dict[str, Any] = {}

    if run_ocr and reading_mode != "vision":
        if not OCR_OK:
            extra_warnings.append({
                "code": "ocr_unavailable",
                "message": "检测到图片但本机未安装 Tesseract，无法 OCR 识别图中文字；请粘贴题目或安装 Tesseract",
            })

        image_assets, summary = ocr_batch(
            image_assets,
            lang=ocr_lang,
            max_pages=ocr_max_pages,
            enable_image_ocr=enable_image_ocr,
            body_len=body_len,
            hints=hints,
        )
    elif run_vision:
        for img in image_assets:
            if not img.get("ocr_status"):
                img.update({
                    "ocr_status": "skipped",
                    "ocr_engine": "tesseract",
                    "ocr_lang": ocr_lang,
                    "ocr_text": "",
                    "ocr_error": "vision_only_mode",
                })

    metadata["image_assets"] = image_assets

    if run_vision or run_hybrid_vision:
        image_assets, vision_summary, vision_warnings = vision_batch(
            image_assets,
            settings=llm_settings,
            reading_mode=reading_mode,
            max_pages=vision_max_pages,
        )
        metadata["image_assets"] = image_assets
        summary = {**summary, **vision_summary}
        extra_warnings.extend(vision_warnings)

    merge = merge_assignment_from_images(full_text, image_assets)
    summary["merged_chars"] = merge.get("merged_chars") or 0
    extra_warnings.extend(multi_question_image_warnings(merge.get("image_sections") or []))

    effective_mode = reading_mode
    if reading_mode == "hybrid" and summary.get("vision_attempted", 0) == 0:
        effective_mode = "ocr_only"

    result = {
        "image_reading_mode": effective_mode,
        "assignment_from_images": merge["assignment_from_images"],
        "image_sections": merge["image_sections"],
        "image_ocr_merged": merge["image_ocr_merged"],
        "image_read_summary": summary,
        "document_assignment_text": merge["assignment_text"],
    }
    return extra_warnings, result


MIN_BODY_CHARS_FOR_WARN = 200
