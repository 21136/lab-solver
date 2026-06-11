"""
Multi-document parse, combined layout split (Phase 2a.2).
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from config import DOCX_OK, TEMP_DIR
from log_util import logi
from modules.code_cloze import detect_code_cloze

_SHORT_ANSWER_LAB_KEYWORDS = (
    "代码",
    "程序",
    "实验步骤",
    "运行结果",
    "实验报告",
    "实验目的",
    "实验内容",
)
_SHORT_ANSWER_NUMBERED_RE = re.compile(
    r"(?:^|\n)\s*(?:[一二三四五六七八九十]+[、.．]|(?:\d+[.、．]\s))"
)
_SHORT_ANSWER_CODE_HINT_RE = re.compile(
    r"```|\b(class|public\s+static|def\s+\w+|#include\b)",
    re.IGNORECASE,
)


def detect_short_answer(text: str, *, metadata: dict | None = None) -> bool:
    """Score-based detector for pure short-answer papers (non-mixed, non-cloze)."""
    body = (text or "").strip()
    if len(body) < 40:
        return False
    score = 0
    has_numbered = bool(_SHORT_ANSWER_NUMBERED_RE.search(body))
    has_code_hint = bool(_SHORT_ANSWER_CODE_HINT_RE.search(body))
    if has_numbered and not has_code_hint:
        score += 3
    if not any(kw in body for kw in _SHORT_ANSWER_LAB_KEYWORDS):
        score += 2
    meta = metadata or {}
    if meta.get("inline_paste") or meta.get("source_format") == "text":
        score += 1
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(body) < 800 and len(paragraphs) >= 3:
        score += 1
    return score >= 4


def _apply_short_answer_type(bundle: dict[str, Any]) -> bool:
    """Mark bundle as short_answer when heuristics match."""
    meta = dict(bundle.get("metadata") or {})
    if meta.get("mixed_assignment"):
        return False
    cloze = meta.get("code_cloze") or {}
    if cloze.get("is_code_cloze"):
        return False
    if (meta.get("question_type") or "").strip().lower() == "code_cloze":
        return False
    full_text = (bundle.get("assignment_text") or bundle.get("full_text") or "").strip()
    if not detect_short_answer(full_text, metadata=meta):
        return False
    meta["question_type"] = "short_answer"
    bundle["metadata"] = meta
    question = dict(bundle.get("question") or {})
    question["type"] = "short_answer"
    bundle["question"] = question
    logi("parse_documents", "short_answer detected")
    return True
from modules.fill_report import SECTION_HEADER_PATTERNS
from modules.parse_report import (
    build_question_from_document,
    build_questions_from_segments,
    document_format,
    extract_document_paragraphs,
    format_mixed_assignment_text,
    should_use_mixed_assignment,
    split_docx_assignment_segments,
    split_text_assignment_segments,
)

VALID_ROLES = frozenset(
    {"assignment", "fill_target", "fill_template", "answer_template", "reference", "auto"}
)

_STEPS_TITLE_FALLBACK = re.compile(
    r"^(三|3)[、．.\s]*.*(实验步骤|实验内容|内容及步骤)",
    re.IGNORECASE,
)
_ASSIGNMENT_MARKERS = ("实验目的", "实验要求", "题目", "要求", "原理")
_FILL_MARKERS = ("实验步骤", "实验结果", "实验总结", "三、", "四、", "五、")
_MIN_ASSIGNMENT_CHARS = 200


def guess_doc_role(full_text: str) -> str:
    text = full_text or ""
    has_sections = any(m in text for m in _FILL_MARKERS)
    short = len(text) < 1500
    assignment_like = any(m in text for m in _ASSIGNMENT_MARKERS) and not has_sections
    if has_sections and _looks_like_template_sample(text):
        return "answer_template"
    if assignment_like and short:
        return "assignment"
    if has_sections:
        return "fill_target"
    return "fill_target"


def _looks_like_template_sample(text: str) -> bool:
    """Heuristic: filled sections + long body → sample report."""
    if len(text) < 2500:
        return False
    for key in ("steps", "result", "summary"):
        pat = SECTION_HEADER_PATTERNS.get(key)
        if pat:
            m = pat.search(text)
            if m:
                chunk = text[m.start() : m.start() + 500]
                if len(chunk.strip()) > 120:
                    return True
    return False


def _match_steps_header(line: str, custom_heading: Optional[str] = None) -> bool:
    if custom_heading and custom_heading.strip():
        return line.strip() == custom_heading.strip() or custom_heading.strip() in line
    pat = SECTION_HEADER_PATTERNS.get("steps")
    if pat and pat.match(line):
        return True
    return bool(_STEPS_TITLE_FALLBACK.match(line))


def find_split_idx(
    paragraphs: list[str],
    *,
    split_at_heading: Optional[str] = None,
) -> Optional[int]:
    for i, line in enumerate(paragraphs):
        if _match_steps_header(line, split_at_heading):
            return i
    return None


def detect_combined_layout(
    full_text: str,
    paragraphs: list[str],
    *,
    split_at_heading: Optional[str] = None,
) -> str:
    """
    Returns: combined | fill_only | assignment_only
    """
    split_idx = find_split_idx(paragraphs, split_at_heading=split_at_heading)
    if split_idx is None:
        if any(m in full_text for m in _FILL_MARKERS):
            return "fill_only"
        return "assignment_only"

    prefix = "\n".join(paragraphs[:split_idx])
    if len(prefix.strip()) >= _MIN_ASSIGNMENT_CHARS:
        return "combined"
    if split_idx > 0:
        return "combined"
    return "fill_only"


def split_combined_text(
    paragraphs: list[str],
    split_idx: int,
) -> tuple[str, str, str]:
    """Returns assignment_text, fill_body_text, split_heading."""
    if split_idx <= 0 or split_idx >= len(paragraphs):
        joined = "\n".join(paragraphs)
        return "", joined, ""
    heading = paragraphs[split_idx]
    assignment_text = "\n".join(paragraphs[:split_idx])
    fill_body_text = "\n".join(paragraphs[split_idx:])
    return assignment_text, fill_body_text, heading


def apply_assignment_text_override(bundle: dict[str, Any], override: str) -> None:
    """Rebuild planner_input_text after O30 user edits assignment_text."""
    text = (override or "").strip()
    if not text:
        return
    bundle["assignment_text"] = text
    fill_body = ""
    ft = bundle.get("fill_target")
    if isinstance(ft, dict):
        fill_body = ft.get("full_text") or ""
    if not fill_body:
        fill_body = bundle.get("fill_body_text") or bundle.get("report_text") or ""
    references: list[str] = []
    for d in bundle.get("documents") or []:
        if not isinstance(d, dict) or d.get("role") != "reference":
            continue
        ref = (d.get("full_text") or d.get("report_text") or "")[:3000]
        if ref.strip():
            references.append(ref)
    bundle["planner_input_text"] = build_planner_input_text(
        assignment_text=text,
        fill_body_text=fill_body,
        reference_excerpts=references,
        layout=bundle.get("layout") or "fill_only",
    )


def build_planner_input_text(
    *,
    assignment_text: str,
    fill_body_text: str,
    reference_excerpts: Optional[list[str]] = None,
    layout: str = "fill_only",
) -> str:
    parts: list[str] = []
    if assignment_text.strip():
        parts.append("【实验要求】\n" + assignment_text.strip())
    if fill_body_text.strip():
        label = "【待填报告"
        if layout == "combined":
            label += "（从实验步骤节起）"
        label += "】\n"
        parts.append(label + fill_body_text.strip())
    if not parts:
        parts.append("【报告全文】\n" + (fill_body_text or assignment_text or "").strip())
    for i, ref in enumerate(reference_excerpts or []):
        if ref.strip():
            parts.append(f"【参考资料 {i + 1}】\n" + ref.strip()[:2000])
    return "\n\n".join(parts)


def parse_inline_text(
    text: str,
    file_name: str = "粘贴的题目.txt",
    *,
    doc_id: Optional[str] = None,
    role: str = "assignment",
    needs_uml: bool = False,
) -> dict[str, Any]:
    """Parse user-pasted assignment / reference text (no file upload)."""
    doc_id = doc_id or str(uuid.uuid4())
    full_text = (text or "").strip()
    if not full_text:
        raise ValueError("粘贴内容不能为空")

    paragraphs = [ln for ln in full_text.split("\n") if ln.strip()]
    resolved_role = role if role in VALID_ROLES and role != "auto" else guess_doc_role(full_text)
    layout = detect_combined_layout(full_text, paragraphs)

    assignment_text = ""
    fill_body_text = full_text
    split_idx = find_split_idx(paragraphs)
    split_heading = ""

    if resolved_role == "fill_target" and layout == "combined" and split_idx is not None:
        assignment_text, fill_body_text, split_heading = split_combined_text(paragraphs, split_idx)
    elif resolved_role == "assignment":
        assignment_text = full_text
        fill_body_text = ""
        layout = "assignment_only"
    elif resolved_role == "reference":
        assignment_text = ""
        fill_body_text = ""
        layout = "assignment_only"

    report_text = fill_body_text or full_text
    title_base = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    metadata: dict[str, Any] = {
        "source_format": "text",
        "doc_role": resolved_role,
        "layout": layout,
        "inline_paste": True,
    }
    q_type = "lab_report"
    cloze = detect_code_cloze(full_text)
    if layout == "assignment_only" and cloze.get("is_code_cloze"):
        q_type = "code_cloze"
        metadata["code_cloze"] = cloze

    question = {
        "id": 0,
        "type": q_type,
        "title": title_base,
        "full_text": full_text,
        "metadata": dict(metadata),
        "placeholder": "",
        "image_assets": [],
        "image_bundle_meta": {},
    }

    warnings: list[Any] = []
    if len(full_text) < 80:
        warnings.append(
            {
                "code": "short_inline_text",
                "message": "粘贴内容较短，请确认已从作业页完整复制题目",
            }
        )

    planner_input_text = build_planner_input_text(
        assignment_text=assignment_text,
        fill_body_text=fill_body_text or full_text,
        layout=layout,
    )

    bundle: dict[str, Any] = {
        "document_id": doc_id,
        "id": doc_id,
        "role": resolved_role,
        "layout": layout,
        "file_name": file_name,
        "file_path": "",
        "report_text": report_text,
        "planner_input_text": planner_input_text,
        "full_text": full_text,
        "assignment_text": assignment_text or full_text,
        "fill_body_text": fill_body_text,
        "metadata": metadata,
        "question": question,
        "warnings": warnings,
        "needs_uml": needs_uml,
        "split_idx": split_idx,
        "split_at_heading": split_heading or "",
        "paragraph_count": len(paragraphs),
        "report_layout": "",
        "table_map": [],
        "created_at": __import__("time").time(),
    }
    if layout == "assignment_only":
        if not _apply_mixed_assignment_split(bundle):
            _apply_short_answer_type(bundle)
    return bundle


def _apply_ocr_to_assignment_text(assignment_text: str, metadata: dict) -> str:
    """Append IM2 OCR merge segment to assignment_text for planner_input."""
    ocr_merged = (metadata.get("image_ocr_merged") or "").strip()
    if not ocr_merged:
        return assignment_text
    base = (assignment_text or "").strip()
    if base:
        return base + "\n\n" + ocr_merged
    return ocr_merged


def _assignment_segments_for_bundle(bundle: dict[str, Any]) -> list[dict[str, str]]:
    """Collect raw segments from docx body or plain text."""
    layout = bundle.get("layout") or ""
    role = bundle.get("role") or ""
    if layout != "assignment_only" and role == "fill_target":
        return []
    full_text = (bundle.get("full_text") or "").strip()
    if not full_text:
        return []
    file_path = bundle.get("file_path") or ""
    src = (bundle.get("metadata") or {}).get("source_format") or ""
    if file_path and src in ("docx", "doc") and DOCX_OK:
        try:
            from docx import Document

            doc = Document(str(file_path))
            return split_docx_assignment_segments(doc)
        except Exception:
            pass
    return split_text_assignment_segments(full_text)


def _apply_mixed_assignment_split(bundle: dict[str, Any]) -> bool:
    """O10/R8: split theory + code_cloze in one assignment; False if not mixed."""
    if bundle.get("fill_target"):
        return False
    layout = bundle.get("layout") or ""
    if layout not in ("assignment_only", ""):
        return False
    segments = _assignment_segments_for_bundle(bundle)
    if not segments:
        return False
    title_base = bundle.get("file_name", "题目").rsplit(".", 1)[0]
    questions = build_questions_from_segments(segments, title_base=title_base)
    if not should_use_mixed_assignment(questions):
        return False

    combined = format_mixed_assignment_text(questions)
    bundle["questions"] = questions
    bundle["question"] = dict(questions[0])
    bundle["assignment_text"] = combined
    bundle["planner_input_text"] = build_planner_input_text(
        assignment_text=combined,
        fill_body_text="",
        layout="assignment_only",
    )
    metadata = dict(bundle.get("metadata") or {})
    metadata["mixed_assignment"] = True
    metadata["assignment_questions"] = [
        {
            "id": q["id"],
            "type": q["type"],
            "title": q.get("title"),
            "full_text": q.get("full_text"),
            "metadata": q.get("metadata") or {},
        }
        for q in questions
    ]
    metadata["question_type"] = "mixed_assignment"
    metadata["question_count"] = len(questions)
    metadata.pop("code_cloze", None)
    bundle["metadata"] = metadata
    if isinstance(bundle.get("question"), dict):
        q0 = dict(bundle["question"])
        qmeta = dict(q0.get("metadata") or {})
        qmeta.pop("code_cloze", None)
        q0["metadata"] = qmeta
        bundle["question"] = q0
    logi(
        "parse_documents",
        f"mixed_assignment segments={len(questions)} types="
        f"{sorted({q.get('type') for q in questions})}",
    )
    return True


def _apply_user_upload_assignment_images(
    result: dict[str, Any],
    assignment_images: list[dict[str, Any]],
    *,
    enable_image_ocr: bool = False,
    ocr_lang: str = "chi_sim+eng",
    ocr_max_pages: int = 20,
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = 5,
    llm_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge Step1 user-uploaded assignment images (IM4) into parse result."""
    if not assignment_images:
        return result

    from document.user_upload_images import process_user_upload_images

    base_assignment = (result.get("assignment_text") or "").strip()
    upload = process_user_upload_images(
        assignment_images,
        enable_image_ocr=enable_image_ocr,
        ocr_lang=ocr_lang,
        ocr_max_pages=ocr_max_pages,
        body_text=base_assignment,
        image_reading_mode=image_reading_mode,
        vision_max_pages=vision_max_pages,
        llm_settings=llm_settings,
    )
    upload_assets = upload.get("image_assets") or []
    upload_meta = upload.get("image_bundle_meta") or {}

    result["assignment_text"] = upload.get("assignment_text") or base_assignment
    result["assignment_from_images"] = bool(
        result.get("assignment_from_images") or upload.get("assignment_from_images")
    )
    if upload.get("image_reading_mode"):
        result["image_reading_mode"] = upload["image_reading_mode"]
    if upload.get("image_read_summary"):
        result["image_read_summary"] = upload["image_read_summary"]
    if upload.get("image_sections"):
        result["image_sections"] = upload["image_sections"]

    all_warnings = list(result.get("warnings") or [])
    all_warnings.extend(upload.get("warnings") or [])
    result["warnings"] = all_warnings

    primary_meta = dict(result.get("metadata") or {})
    doc_assets = list(primary_meta.get("image_assets") or [])
    primary_meta["image_assets"] = doc_assets + upload_assets
    bundle_meta = dict(primary_meta.get("image_bundle_meta") or {})
    bundle_meta["user_upload_total"] = upload_meta.get("total", len(upload_assets))
    bundle_meta["user_upload_deduped"] = upload_meta.get("deduped", len(upload_assets))
    primary_meta["image_bundle_meta"] = bundle_meta
    if upload.get("assignment_from_images"):
        primary_meta["assignment_from_images"] = True
        primary_meta["document_assignment_text"] = result["assignment_text"]
        primary_meta["image_ocr_merged"] = upload.get("image_ocr_merged") or ""
        primary_meta["image_read_summary"] = upload.get("image_read_summary")
        primary_meta["image_sections"] = upload.get("image_sections") or []
    result["metadata"] = primary_meta

    fill_body = ""
    primary = (result.get("fill_target") or {}) if result.get("fill_target") else {}
    if primary:
        fill_body = primary.get("full_text") or result.get("report_text") or ""
    else:
        fill_body = result.get("report_text") or ""

    references = []
    for d in result.get("documents") or []:
        if d.get("role") == "reference":
            meta = d.get("metadata") or {}
            ref_text = meta.get("full_text") or ""
            if ref_text:
                references.append(ref_text[:3000])

    result["planner_input_text"] = build_planner_input_text(
        assignment_text=result["assignment_text"],
        fill_body_text=fill_body,
        reference_excerpts=references,
        layout=result.get("layout") or "assignment_only",
    )

    bundles = list(result.get("_bundles") or [])
    if bundles:
        bundles[0]["assignment_text"] = result["assignment_text"]
        bundles[0]["planner_input_text"] = result["planner_input_text"]
        bundles[0]["assignment_from_images"] = result["assignment_from_images"]
        bmeta = dict(bundles[0].get("metadata") or {})
        bmeta["image_assets"] = primary_meta.get("image_assets") or []
        bmeta["image_bundle_meta"] = primary_meta.get("image_bundle_meta") or {}
        bundles[0]["metadata"] = bmeta
    else:
        bundles.append(_build_user_upload_bundle(upload, result["assignment_text"]))
    result["_bundles"] = bundles
    result["_user_upload_assets"] = upload_assets
    return result


def _build_user_upload_bundle(upload: dict[str, Any], assignment_text: str) -> dict[str, Any]:
    """Synthetic document bundle for assignment-only image uploads."""
    doc_id = str(uuid.uuid4())
    metadata: dict[str, Any] = {
        "source_format": "user_upload",
        "doc_role": "assignment",
        "layout": "assignment_only",
        "image_assets": upload.get("image_assets") or [],
        "image_bundle_meta": upload.get("image_bundle_meta") or {},
        "assignment_from_images": upload.get("assignment_from_images"),
        "document_assignment_text": assignment_text,
        "image_ocr_merged": upload.get("image_ocr_merged") or "",
        "image_read_summary": upload.get("image_read_summary"),
        "image_sections": upload.get("image_sections") or [],
    }
    cloze = detect_code_cloze(assignment_text)
    q_type = "code_cloze" if cloze.get("is_code_cloze") else "lab_report"
    if q_type == "code_cloze":
        metadata["code_cloze"] = cloze

    question = {
        "id": 0,
        "type": q_type,
        "title": "题目图片组",
        "full_text": assignment_text,
        "metadata": {k: v for k, v in metadata.items() if k not in ("image_assets", "image_bundle_meta")},
        "placeholder": "",
        "image_assets": upload.get("image_assets") or [],
        "image_bundle_meta": upload.get("image_bundle_meta") or {},
        "assignment_from_images": upload.get("assignment_from_images"),
        "assignment_text": assignment_text,
    }
    planner_input_text = build_planner_input_text(
        assignment_text=assignment_text,
        fill_body_text="",
        layout="assignment_only",
    )
    return {
        "document_id": doc_id,
        "id": doc_id,
        "role": "assignment",
        "layout": "assignment_only",
        "file_name": "题目图片组",
        "file_path": "",
        "report_text": assignment_text,
        "planner_input_text": planner_input_text,
        "full_text": assignment_text,
        "assignment_text": assignment_text,
        "fill_body_text": "",
        "metadata": metadata,
        "question": question,
        "warnings": upload.get("warnings") or [],
        "needs_uml": False,
        "split_idx": None,
        "split_at_heading": "",
        "paragraph_count": 0,
        "report_layout": "",
        "table_map": [],
        "assignment_from_images": upload.get("assignment_from_images"),
        "image_reading_mode": upload.get("image_reading_mode") or "",
        "image_read_summary": upload.get("image_read_summary"),
        "image_sections": upload.get("image_sections") or [],
        "created_at": __import__("time").time(),
    }


def parse_assignment_images_only(
    assignment_images: list[dict[str, Any]],
    *,
    enable_image_ocr: bool = False,
    ocr_lang: str = "chi_sim+eng",
    ocr_max_pages: int = 20,
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = 5,
    llm_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse Step1 assignment image group without file documents (IM4 / I4)."""
    from document.user_upload_images import process_user_upload_images

    upload = process_user_upload_images(
        assignment_images,
        enable_image_ocr=enable_image_ocr,
        ocr_lang=ocr_lang,
        ocr_max_pages=ocr_max_pages,
        body_text="",
        image_reading_mode=image_reading_mode,
        vision_max_pages=vision_max_pages,
        llm_settings=llm_settings,
    )
    if not upload.get("image_assets"):
        raise ValueError("题目图片组为空或无效")

    assignment_text = upload.get("assignment_text") or ""
    bundle = _build_user_upload_bundle(upload, assignment_text)
    return {
        "documents": [
            {
                "id": bundle["document_id"],
                "role": "assignment",
                "layout": "assignment_only",
                "file_name": bundle["file_name"],
                "format": "user_upload",
                "metadata": bundle["metadata"],
                "assignment_excerpt_len": len(assignment_text),
                "fill_body_len": 0,
                "split_at_heading": "",
            }
        ],
        "document_ids": [bundle["document_id"]],
        "fill_target": None,
        "fill_target_info": None,
        "assignment_text": assignment_text,
        "planner_input_text": bundle["planner_input_text"],
        "report_text": assignment_text,
        "metadata": bundle["metadata"],
        "question": bundle["question"],
        "warnings": upload.get("warnings") or [],
        "needs_uml": False,
        "split_idx": None,
        "layout": "assignment_only",
        "format_spec": None,
        "format_spec_source_id": None,
        "assignment_from_images": bool(upload.get("assignment_from_images")),
        "image_reading_mode": upload.get("image_reading_mode") or "",
        "image_read_summary": upload.get("image_read_summary"),
        "image_sections": upload.get("image_sections") or [],
        "_bundles": [bundle],
        "_user_upload_assets": upload.get("image_assets") or [],
    }


def parse_single_file(
    file_bytes: bytes,
    file_name: str,
    *,
    doc_id: Optional[str] = None,
    role: str = "auto",
    layout_override: Optional[str] = None,
    split_at_heading: Optional[str] = None,
    needs_uml: bool = False,
    enable_image_ocr: bool = False,
    ocr_lang: str = "chi_sim+eng",
    ocr_max_pages: int = 20,
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = 5,
    llm_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc_id = doc_id or str(uuid.uuid4())
    tmp = TEMP_DIR / f"doc_{doc_id[:8]}_{file_name}"
    tmp.write_bytes(file_bytes)

    question, metadata, full_text, warnings = build_question_from_document(
        tmp,
        file_name,
        enable_image_ocr=enable_image_ocr,
        ocr_lang=ocr_lang,
        ocr_max_pages=ocr_max_pages,
        image_reading_mode=image_reading_mode,
        vision_max_pages=vision_max_pages,
        llm_settings=llm_settings,
    )
    paragraphs = extract_document_paragraphs(tmp, file_name)
    src_fmt = document_format(file_name)
    resolved_role = role if role in VALID_ROLES and role != "auto" else guess_doc_role(full_text)

    layout = layout_override or detect_combined_layout(
        full_text, paragraphs, split_at_heading=split_at_heading
    )

    # P0A: training_table reports lack "三/四/五" headers → detect_combined_layout
    # misclassifies as assignment_only. Use parse_report's table detection from metadata.
    report_layout = metadata.get("report_layout") or ""
    if layout == "assignment_only" and report_layout == "training_table":
        layout = "fill_only"
        if resolved_role == "assignment":
            resolved_role = "fill_target"

    split_idx = find_split_idx(paragraphs, split_at_heading=split_at_heading)
    assignment_text = ""
    fill_body_text = full_text
    split_heading = ""

    if resolved_role == "fill_target" and layout == "combined" and split_idx is not None:
        assignment_text, fill_body_text, split_heading = split_combined_text(
            paragraphs, split_idx
        )
    elif resolved_role == "assignment":
        assignment_text = full_text
        fill_body_text = ""
        layout = "assignment_only"

    assignment_text = _apply_ocr_to_assignment_text(assignment_text, metadata or {})

    report_text = fill_body_text or full_text
    metadata = dict(metadata or {})
    metadata["source_format"] = metadata.get("source_format") or src_fmt
    metadata["doc_role"] = resolved_role
    metadata["layout"] = layout

    # DA2: persist section structure for fill_report (survives document_store cache)
    if src_fmt in ("docx", "doc"):
        try:
            from modules.parse_report import detect_docx_sections, is_legacy_doc
            from document.convert_doc import convert_doc_to_docx

            sec_path = tmp
            if is_legacy_doc(file_name):
                converted, _ = convert_doc_to_docx(tmp)
                if converted and converted.exists():
                    sec_path = converted
            sd = detect_docx_sections(sec_path)
            if sd.get("sections_detected"):
                metadata["sections_detected"] = sd["sections_detected"]
            if sd.get("section_map"):
                metadata["section_map"] = sd["section_map"]
            if sd.get("fill_hints"):
                metadata["fill_hints"] = sd["fill_hints"]
            if sd.get("report_layout"):
                metadata["report_layout"] = sd["report_layout"]
            if sd.get("table_map") and not metadata.get("table_map"):
                metadata["table_map"] = sd["table_map"]
        except Exception:
            pass
    # IM1: propagate image_assets from question to bundle metadata
    metadata["image_assets"] = question.get("image_assets") or []
    metadata["image_bundle_meta"] = question.get("image_bundle_meta") or {}

    planner_input_text = build_planner_input_text(
        assignment_text=assignment_text,
        fill_body_text=fill_body_text or full_text,
        layout=layout,
    )

    image_read_summary = metadata.get("image_read_summary")
    cloze_source = (assignment_text or "").strip()
    if not cloze_source:
        cloze_source = (full_text or "").strip()
    cloze = metadata.get("code_cloze") or detect_code_cloze(cloze_source)
    if not cloze.get("is_code_cloze"):
        existing = ((question or {}).get("metadata") or {}).get("code_cloze")
        if existing and existing.get("is_code_cloze"):
            cloze = existing
    if cloze.get("is_code_cloze"):
        question = dict(question or {})
        question["type"] = "code_cloze"
        qmeta = dict(question.get("metadata") or {})
        qmeta["code_cloze"] = cloze
        question["metadata"] = qmeta
        metadata["code_cloze"] = cloze
    bundle: dict[str, Any] = {
        "document_id": doc_id,
        "id": doc_id,
        "role": resolved_role,
        "layout": layout,
        "file_name": file_name,
        "file_path": str(tmp),
        "report_text": report_text,
        "planner_input_text": planner_input_text,
        "full_text": full_text,
        "assignment_text": assignment_text or full_text,
        "fill_body_text": fill_body_text,
        "metadata": metadata,
        "question": question,
        "warnings": warnings,
        "needs_uml": needs_uml,
        "split_idx": split_idx,
        "split_at_heading": split_heading or split_at_heading or "",
        "paragraph_count": len(paragraphs),
        "report_layout": report_layout,
        "table_map": metadata.get("table_map") or [],
        "assignment_from_images": bool(metadata.get("assignment_from_images")),
        "image_reading_mode": metadata.get("image_reading_mode") or "",
        "image_read_summary": image_read_summary,
        "image_sections": metadata.get("image_sections") or [],
        "created_at": __import__("time").time(),
    }
    if layout == "assignment_only" or (
        resolved_role == "assignment" and not fill_body_text
    ):
        _apply_mixed_assignment_split(bundle)
    return bundle


def _questions_from_parse_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("questions"):
        return list(result["questions"])
    q = result.get("question")
    return [q] if q else []


def _attach_questions_to_result(result: dict[str, Any]) -> dict[str, Any]:
    result["questions"] = _questions_from_parse_result(result)
    return result


def parse_documents_list(
    documents: list[dict],
    *,
    default_needs_uml: bool = False,
    enable_image_ocr: bool = False,
    ocr_lang: str = "chi_sim+eng",
    ocr_max_pages: int = 20,
    image_reading_mode: str = "ocr_only",
    vision_max_pages: int = 5,
    llm_settings: dict[str, Any] | None = None,
    assignment_images: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Parse documents[] payload; enforce one fill_target.
    """
    if not documents:
        raise ValueError("documents 不能为空")

    parsed_docs: list[dict[str, Any]] = []
    fill_targets: list[dict[str, Any]] = []
    assignments: list[str] = []
    references: list[str] = []
    all_warnings: list[Any] = []
    format_spec_source: Optional[dict] = None
    format_spec: Optional[dict[str, Any]] = None

    for item in documents:
        if not isinstance(item, dict):
            continue
        text_content = item.get("text_content")
        file_data = item.get("file_data")
        file_name = item.get("file_name", "report.docx")
        doc_id = str(item.get("id") or uuid.uuid4())
        role = (item.get("role") or "auto").strip().lower()
        if text_content is not None:
            bundle = parse_inline_text(
                str(text_content),
                file_name,
                doc_id=doc_id,
                role=role if role != "auto" else "assignment",
                needs_uml=bool(item.get("needs_uml") or default_needs_uml),
            )
        elif file_data:
            file_bytes = base64.b64decode(file_data)
            bundle = parse_single_file(
                file_bytes,
                file_name,
                doc_id=doc_id,
                role=role,
                layout_override=item.get("layout"),
                split_at_heading=item.get("split_at_heading"),
                needs_uml=bool(item.get("needs_uml") or default_needs_uml),
                enable_image_ocr=bool(
                    item.get("enableImageOcr")
                    or item.get("enable_image_ocr")
                    or enable_image_ocr
                ),
                ocr_lang=str(
                    item.get("imageOcrLang") or item.get("ocr_lang") or ocr_lang
                ),
                ocr_max_pages=int(
                    item.get("imageOcrMaxPages")
                    or item.get("ocr_max_pages")
                    or ocr_max_pages
                ),
                image_reading_mode=str(
                    item.get("imageReadingMode")
                    or item.get("image_reading_mode")
                    or image_reading_mode
                ),
                vision_max_pages=int(
                    item.get("imageVisionMaxPages")
                    or item.get("vision_max_pages")
                    or vision_max_pages
                ),
                llm_settings=llm_settings,
            )
        else:
            raise ValueError(f"文档 {file_name} 缺少 file_data 或 text_content")
        parsed_docs.append(bundle)
        all_warnings.extend(bundle.get("warnings") or [])
        if bundle["role"] == "fill_target":
            fill_targets.append(bundle)
        elif bundle["role"] == "assignment":
            assignments.append(bundle.get("full_text") or bundle.get("report_text") or "")
        elif bundle["role"] == "reference":
            references.append((bundle.get("full_text") or "")[:3000])
        elif bundle["role"] == "answer_template":
            format_spec_source = bundle

    if len(fill_targets) > 1:
        raise ValueError("只能有一份待填报告 (fill_target)")

    if fill_targets:
        primary = fill_targets[0]
        assignment_parts = [t for t in assignments if t.strip()]
        if primary.get("assignment_text"):
            assignment_parts.insert(0, primary["assignment_text"])
        assignment_text = "\n\n".join(assignment_parts)
        cloze = detect_code_cloze(assignment_text)

        # Separate assignment file overrides combined split assignment half
        if assignments and primary.get("layout") == "combined":
            primary["layout"] = "fill_only"
            primary["assignment_text"] = ""

        planner_input = build_planner_input_text(
            assignment_text=assignment_text,
            fill_body_text=primary.get("fill_body_text") or primary.get("report_text") or "",
            reference_excerpts=references,
            layout=primary.get("layout") or "fill_only",
        )

        if format_spec_source:
            from pathlib import Path

            from modules.parse_answer_template import parse_answer_template

            tpl_path = Path(format_spec_source["file_path"])
            if tpl_path.exists():
                format_spec = parse_answer_template(
                    tpl_path.read_bytes(),
                    format_spec_source.get("file_name") or "template.docx",
                    template_type=format_spec_source.get("template_type") or "user_sample",
                    assignment_metadata=primary.get("metadata"),
                    assignment_text=assignment_text or planner_input,
                )
                format_spec_source["format_spec"] = format_spec

        document_ids = [d["document_id"] for d in parsed_docs]
        logi(
            "parse_documents",
            f"docs={len(parsed_docs)} fill={primary['file_name']} layout={primary.get('layout')}",
        )

        from document.pdf_export import resolve_fill_target_info

        fill_target_info = resolve_fill_target_info(parsed_docs, primary)
        fill_target_payload = {
            "id": primary["document_id"],
            "file_name": primary["file_name"],
            "file_path": primary["file_path"],
            "metadata": primary["metadata"],
            "full_text": primary.get("fill_body_text") or primary["report_text"],
            "source_format": fill_target_info.get("source_format")
            or (primary.get("metadata") or {}).get("source_format", "docx"),
            "layout": primary.get("layout"),
            "split_idx": primary.get("split_idx"),
            "split_at_heading": primary.get("split_at_heading"),
            "export_format": "docx",
            "fill_docx_from": fill_target_info.get("from"),
        }
        if fill_target_info.get("path"):
            fill_target_payload["fill_docx_path"] = fill_target_info["path"]
        if fill_target_info.get("message"):
            fill_target_payload["export_message"] = fill_target_info["message"]

        result = {
            "documents": [
                {
                    "id": d["document_id"],
                    "role": d["role"],
                    "layout": d.get("layout"),
                    "file_name": d.get("file_name"),
                    "format": (d.get("metadata") or {}).get("source_format", "docx"),
                    "metadata": d.get("metadata"),
                    "assignment_excerpt_len": len(d.get("assignment_text") or ""),
                    "fill_body_len": len(d.get("fill_body_text") or d.get("report_text") or ""),
                    "split_at_heading": d.get("split_at_heading") or "",
                }
                for d in parsed_docs
            ],
            "document_ids": document_ids,
            "fill_target": fill_target_payload,
            "fill_target_info": fill_target_info,
            "assignment_text": assignment_text,
            "planner_input_text": planner_input,
            "report_text": primary["report_text"],
            "metadata": primary["metadata"],
            "question": primary["question"],
            "warnings": all_warnings,
            "needs_uml": primary.get("needs_uml", False),
            "split_idx": primary.get("split_idx"),
            "layout": primary.get("layout"),
            "format_spec": format_spec,
            "format_spec_source_id": (
                format_spec_source["document_id"] if format_spec_source else None
            ),
            "assignment_from_images": any(
                d.get("assignment_from_images") for d in parsed_docs
            ),
            "image_reading_mode": primary.get("image_reading_mode") or "",
            "image_read_summary": primary.get("image_read_summary"),
            "image_sections": primary.get("image_sections") or [],
            "_bundles": parsed_docs,
        }
        meta = result.get("metadata") or {}
        if not meta.get("mixed_assignment") and cloze.get("is_code_cloze"):
            result["question"] = dict(result.get("question") or {})
            result["question"]["type"] = "code_cloze"
            qmeta = dict((result["question"].get("metadata") or {}))
            qmeta["code_cloze"] = cloze
            result["question"]["metadata"] = qmeta
            result["metadata"] = dict(result.get("metadata") or {})
            result["metadata"]["code_cloze"] = cloze
        elif not meta.get("mixed_assignment") and not cloze.get("is_code_cloze"):
            assign = assignment_text or primary.get("full_text") or ""
            if detect_short_answer(assign, metadata=meta):
                result["question"] = dict(result.get("question") or {})
                result["question"]["type"] = "short_answer"
                result["metadata"] = dict(result.get("metadata") or {})
                result["metadata"]["question_type"] = "short_answer"
        return _attach_questions_to_result(
            _apply_user_upload_assignment_images(
                result,
                assignment_images or [],
                enable_image_ocr=enable_image_ocr,
                ocr_lang=ocr_lang,
                ocr_max_pages=ocr_max_pages,
                image_reading_mode=image_reading_mode,
                vision_max_pages=vision_max_pages,
                llm_settings=llm_settings,
            )
        )

    # No fill_target — assignment-only documents, answers go to new doc or UI only
    if len(parsed_docs) == 0:
        raise ValueError("documents 不能为空")

    primary = parsed_docs[0]
    document_ids = [d["document_id"] for d in parsed_docs]
    assignment_text = "\n\n".join([t for t in assignments if t.strip()])
    primary_meta = primary.get("metadata") or {}
    if primary_meta.get("mixed_assignment"):
        assignment_text = primary.get("assignment_text") or assignment_text
    cloze = detect_code_cloze(assignment_text or primary.get("full_text") or "")
    planner_input = (
        primary.get("planner_input_text")
        if primary_meta.get("mixed_assignment")
        else build_planner_input_text(
            assignment_text=assignment_text,
            fill_body_text=primary.get("fill_body_text") or primary.get("report_text") or "",
            reference_excerpts=references,
            layout="assignment_only",
        )
    )
    logi(
        "parse_documents",
        f"docs={len(parsed_docs)} no fill_target, assignment_only",
    )
    result = {
        "documents": [
            {
                "id": d["document_id"],
                "role": d["role"],
                "layout": d.get("layout"),
                "file_name": d.get("file_name"),
                "format": (d.get("metadata") or {}).get("source_format", "docx"),
                "metadata": d.get("metadata"),
                "assignment_excerpt_len": len(d.get("assignment_text") or ""),
                "fill_body_len": len(d.get("fill_body_text") or d.get("report_text") or ""),
                "split_at_heading": d.get("split_at_heading") or "",
            }
            for d in parsed_docs
        ],
        "document_ids": document_ids,
        "fill_target": None,
        "fill_target_info": None,
        "assignment_text": assignment_text,
        "planner_input_text": planner_input,
        "report_text": primary["report_text"],
        "metadata": primary["metadata"],
        "question": primary["question"],
        "questions": primary.get("questions"),
        "warnings": all_warnings,
        "needs_uml": primary.get("needs_uml", False),
        "split_idx": None,
        "layout": "assignment_only",
        "format_spec": format_spec,
        "format_spec_source_id": (
            format_spec_source["document_id"] if format_spec_source else None
        ),
        "assignment_from_images": any(
            d.get("assignment_from_images") for d in parsed_docs
        ),
        "image_reading_mode": primary.get("image_reading_mode") or "",
        "image_read_summary": primary.get("image_read_summary"),
        "image_sections": primary.get("image_sections") or [],
        "_bundles": parsed_docs,
    }
    meta = result.get("metadata") or {}
    if not meta.get("mixed_assignment") and cloze.get("is_code_cloze"):
        result["question"] = dict(result.get("question") or {})
        result["question"]["type"] = "code_cloze"
        qmeta = dict((result["question"].get("metadata") or {}))
        qmeta["code_cloze"] = cloze
        result["question"]["metadata"] = qmeta
        result["metadata"] = dict(result.get("metadata") or {})
        result["metadata"]["code_cloze"] = cloze
    elif not meta.get("mixed_assignment") and not cloze.get("is_code_cloze"):
        assign = assignment_text or primary.get("full_text") or ""
        if detect_short_answer(assign, metadata=meta):
            result["question"] = dict(result.get("question") or {})
            result["question"]["type"] = "short_answer"
            result["metadata"] = dict(result.get("metadata") or {})
            result["metadata"]["question_type"] = "short_answer"
    return _attach_questions_to_result(
        _apply_user_upload_assignment_images(
            result,
            assignment_images or [],
            enable_image_ocr=enable_image_ocr,
            ocr_lang=ocr_lang,
            ocr_max_pages=ocr_max_pages,
            image_reading_mode=image_reading_mode,
            vision_max_pages=vision_max_pages,
            llm_settings=llm_settings,
        )
    )
