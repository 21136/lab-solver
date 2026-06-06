"""
Multi-document parse, combined layout split (Phase 2a.2).
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from config import TEMP_DIR
from log_util import logi
from modules.fill_report import SECTION_HEADER_PATTERNS
from modules.parse_report import (
    build_question_from_document,
    document_format,
    extract_document_paragraphs,
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
    question = {
        "id": 0,
        "type": "lab_report",
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

    return {
        "document_id": doc_id,
        "id": doc_id,
        "role": resolved_role,
        "layout": layout,
        "file_name": file_name,
        "file_path": "",
        "report_text": report_text,
        "planner_input_text": planner_input_text,
        "full_text": full_text,
        "assignment_text": assignment_text,
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


def parse_single_file(
    file_bytes: bytes,
    file_name: str,
    *,
    doc_id: Optional[str] = None,
    role: str = "auto",
    layout_override: Optional[str] = None,
    split_at_heading: Optional[str] = None,
    needs_uml: bool = False,
) -> dict[str, Any]:
    doc_id = doc_id or str(uuid.uuid4())
    tmp = TEMP_DIR / f"doc_{doc_id[:8]}_{file_name}"
    tmp.write_bytes(file_bytes)

    question, metadata, full_text, warnings = build_question_from_document(tmp, file_name)
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

    return {
        "document_id": doc_id,
        "id": doc_id,
        "role": resolved_role,
        "layout": layout,
        "file_name": file_name,
        "file_path": str(tmp),
        "report_text": report_text,
        "planner_input_text": planner_input_text,
        "full_text": full_text,
        "assignment_text": assignment_text,
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
        "created_at": __import__("time").time(),
    }


def parse_documents_list(
    documents: list[dict],
    *,
    default_needs_uml: bool = False,
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

        return {
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
            "_bundles": parsed_docs,
        }

    # No fill_target — assignment-only documents, answers go to new doc or UI only
    if len(parsed_docs) == 0:
        raise ValueError("documents 不能为空")

    primary = parsed_docs[0]
    document_ids = [d["document_id"] for d in parsed_docs]
    assignment_text = "\n\n".join([t for t in assignments if t.strip()])
    planner_input = build_planner_input_text(
        assignment_text=assignment_text,
        fill_body_text=primary.get("fill_body_text") or primary.get("report_text") or "",
        reference_excerpts=references,
        layout="assignment_only",
    )
    logi(
        "parse_documents",
        f"docs={len(parsed_docs)} no fill_target, assignment_only",
    )
    return {
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
        "warnings": all_warnings,
        "needs_uml": primary.get("needs_uml", False),
        "split_idx": None,
        "layout": "assignment_only",
        "format_spec": format_spec,
        "format_spec_source_id": (
            format_spec_source["document_id"] if format_spec_source else None
        ),
        "_bundles": parsed_docs,
    }
