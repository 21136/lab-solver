"""Word / PDF report parsing."""

from pathlib import Path

from config import DOCX_OK, PDF_OK

if DOCX_OK:
    from docx import Document

MIN_BODY_CHARS = 200
WARN_LEGACY_DOC = {
    "code": "legacy_doc",
    "message": "旧版 .doc 无法转换。请安装免费的 LibreOffice（https://www.libreoffice.org）或在 Word 中另存为 .docx 后重新上传",
}


def is_legacy_doc(file_name: str) -> bool:
    lower = (file_name or "").lower()
    return lower.endswith(".doc") and not lower.endswith(".docx")


def is_pdf(file_name: str) -> bool:
    return (file_name or "").lower().endswith(".pdf")


def document_format(file_name: str) -> str:
    if is_pdf(file_name):
        return "pdf"
    if is_legacy_doc(file_name):
        return "doc"
    return "docx"


def _pdf_hints_to_warnings(hints: list) -> list:
    warnings = []
    for h in hints or []:
        if isinstance(h, dict) and h.get("message"):
            warnings.append({"code": h.get("code", "pdf_hint"), "message": h["message"]})
    return warnings


def collect_parse_warnings(full_text: str, metadata: dict, file_name: str) -> list:
    """Surface parse quality issues without changing question shape."""
    warnings = []
    if is_legacy_doc(file_name):
        warnings.append(dict(WARN_LEGACY_DOC))

    if is_pdf(file_name):
        if not PDF_OK:
            warnings.append(
                {
                    "code": "pdf_unavailable",
                    "message": "无法读取 PDF（请更新解题能手或联系管理员检查安装包）",
                }
            )
            return warnings
    elif not DOCX_OK:
        warnings.append(
            {
                "code": "docx_unavailable",
                "message": "未安装 python-docx，无法读取 Word 文档",
            }
        )
        return warnings

    body = (full_text or "").strip()
    body_len = len(body)
    has_cover = bool(
        metadata.get("course")
        or metadata.get("experiment_title")
        or metadata.get("student_name")
    )
    image_assets = (metadata.get("image_assets") or [])
    has_images = len(image_assets) > 0
    assignment_images = [img for img in image_assets if img.get("role_guess") == "assignment"]

    if has_cover and body_len < MIN_BODY_CHARS:
        if has_images:
            warnings.append(
                {
                    "code": "short_body_with_images",
                    "message": f"正文较短但检测到 {len(image_assets)} 张嵌入图片"
                    + (f"（{len(assignment_images)} 张疑似题目图）" if assignment_images else "")
                    + "，建议启用 OCR 识别图片中的题目文字",
                }
            )
        else:
            warnings.append(
                {
                    "code": "short_body_with_cover",
                    "message": "已从封面表格读取信息，但正文过短，可能漏读表格或图片中的题目",
                }
            )
    elif body_len < 80:
        if has_images:
            warnings.append(
                {
                    "code": "short_text_with_images",
                    "message": f"正文极短但检测到 {len(image_assets)} 张嵌入图片，题目可能在图片中",
                }
            )
        else:
            warnings.append(
                {
                    "code": "short_text",
                    "message": "提取的正文过短，可能漏读表格/图片题",
                }
            )

    if body and "图" in body and body_len < 500:
        warnings.append(
            {
                "code": "possible_missing_figures",
                "message": "文档含图题但正文较短，图片内文字可能未被读取",
            }
        )

    # IM1: warn when many images detected — suggest OCR
    if len(assignment_images) >= 3:
        warnings.append({
            "code": "multiple_assignment_images",
            "message": f"检测到 {len(assignment_images)} 张疑似题目图片，"
                       "题目要求可能在图片中，建议后续使用 OCR/Vision 识别",
        })

    return warnings


_TRAINING_TABLE_MARKERS = (
    "实训步骤及内容", "实验步骤及内容",
    "实训步骤", "实训任务", "实训内容",
    "实验内容", "实验目的", "实验名",
)

# Longest first so "实验名称" matches before "实验名"
_TRAINING_TABLE_MARKERS_SORTED = tuple(
    sorted(_TRAINING_TABLE_MARKERS, key=len, reverse=True)
)

_TABLE_LAYOUT_KEY_LABELS = (
    "课程名称", "实验序号", "实验名称", "实验名", "实训项目", "实训名称",
    "实训步骤及内容", "实训任务", "实训内容", "实训步骤",
    "实验内容", "实验目的", "实验环境", "指导老师", "指导教师",
    "专业", "学号", "姓名", "班级", "日期", "实验日期",
)


def _cell_texts(row) -> list[str]:
    """Deduplicate merged-cell repeats within a row."""
    seen = []
    for c in row.cells:
        t = c.text.strip()
        if t and (not seen or t != seen[-1]):
            seen.append(t)
    return seen


def _render_table_as_text(table, table_index: int) -> str:
    """Render a docx table as readable text.

    For 2-column tables (key-value style), renders each row as ``【label】value``.
    Otherwise renders rows as pipe-joined cells.
    """
    rows = []
    col_count = max((len(row.cells) for row in table.rows), default=0)

    for ri, row in enumerate(table.rows):
        cells = _cell_texts(row)
        if not cells:
            continue
        if col_count == 2 and len(cells) == 2:
            label, value = cells[0], cells[1]
            if any(kw in label for kw in _TABLE_LAYOUT_KEY_LABELS):
                rows.append(f"【{label}】{value}")
            else:
                rows.append(f"{label}：{value}")
        else:
            rows.append(" | ".join(cells))

    if not rows:
        return ""
    return f"[表格{table_index + 1}]\n" + "\n".join(rows)


# Cell labels that must match exactly (avoid「实验名」⊂「实验名称」误报)
_EXACT_TABLE_MARKERS = frozenset({"实验名"})


def _table_marker_matches(marker: str, cell_text: str) -> bool:
    text = cell_text.strip()
    if marker in _EXACT_TABLE_MARKERS:
        return text == marker
    return marker in text


def _detect_table_layout(doc) -> dict[str, object]:
    """Walk all tables looking for training-report markers.

    Returns a dict with ``report_layout`` and ``table_map`` (cell coordinates
    of each matched marker), or an empty dict for standard paragraph reports.
    """
    table_map_entries: list[dict[str, object]] = []

    for ti, table in enumerate(doc.tables):
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                text = cell.text.strip()
                for marker in _TRAINING_TABLE_MARKERS_SORTED:
                    if _table_marker_matches(marker, text):
                        table_map_entries.append({
                            "table": ti,
                            "row": ri,
                            "col": ci,
                            "label": marker,
                            "text_excerpt": text[:200],
                        })
                        break

    if table_map_entries:
        return {
            "report_layout": "training_table",
            "table_map": table_map_entries,
            "metadata_tables": [0, 1] if len(doc.tables) >= 2 else [0],
        }
    return {}


def extract_docx(path):
    """提取 Word 文档全文和封面表格元数据。"""
    metadata: dict[str, object] = {}
    if not DOCX_OK:
        return "（无法读取Word文档，请安装 python-docx）", metadata

    doc = Document(str(path))

    if doc.tables:
        for row in doc.tables[0].rows:
            cells = [c.text.strip() for c in row.cells]
            for i, cell in enumerate(cells):
                nxt = cells[i + 1] if i + 1 < len(cells) else ""
                if "课程名称" in cell:
                    metadata["course"] = nxt or cells[-1]
                if "实验序号" in cell or "实验名称" in cell:
                    for c in cells[i + 1 :]:
                        if c and len(c) < 40:
                            metadata["experiment_title"] = c
                            break
                if "专业" in cell and nxt:
                    metadata["major"] = nxt
                if "学号" in cell:
                    metadata["student_id"] = nxt
                if "姓名" in cell:
                    for c in cells[i + 1 :]:
                        if c:
                            metadata["student_name"] = c
                            break

    # Detect table layout and extract all table text
    layout = _detect_table_layout(doc)
    if layout:
        metadata.update(layout)

    table_texts = []
    for ti, table in enumerate(doc.tables):
        rendered = _render_table_as_text(table, ti)
        if rendered:
            table_texts.append(rendered)

    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(lines)
    if table_texts:
        full_text = full_text + "\n\n" + "\n\n".join(table_texts)

    # IM1: extract embedded images (lazy import to avoid circular dep)
    from document.extract_images import extract_docx_images

    image_result = extract_docx_images(path)
    metadata["image_assets"] = image_result.get("image_assets") or []
    metadata["image_bundle_meta"] = image_result.get("image_bundle_meta") or {}

    return full_text, metadata


def parse_document(path, file_name: str | None = None):
    """Extract full_text and metadata from docx or pdf by extension."""
    path = Path(path)
    name = file_name or path.name
    if is_legacy_doc(name):
        from document.convert_doc import convert_doc_to_docx

        converted, err = convert_doc_to_docx(path)
        if converted and converted.exists():
            path = converted
            name = converted.name
        else:
            return "", {}, [{"code": "legacy_doc", "message": err or WARN_LEGACY_DOC["message"]}]
    if is_pdf(name):
        from document.extract_pdf import extract_pdf

        full_text, metadata, hints = extract_pdf(path)
        metadata.setdefault("source_format", "pdf")
        return full_text, metadata, hints
    full_text, metadata = extract_docx(path)
    metadata.setdefault("source_format", "docx")
    return full_text, metadata, []


def extract_document_paragraphs(path: Path, file_name: str) -> list[str]:
    """Paragraph list for combined-layout detection (docx or pdf)."""
    if is_pdf(file_name):
        full_text, _, _ = parse_document(path, file_name)
        return [ln for ln in full_text.split("\n") if ln.strip()]
    return [ln for ln in extract_docx_paragraphs(path)]


def extract_docx_paragraphs(path: Path) -> list[str]:
    if not DOCX_OK:
        full_text, _ = extract_docx(path)
        return [ln for ln in full_text.split("\n") if ln.strip()]
    from docx import Document

    doc = Document(str(path))
    return [p.text.strip() for p in doc.paragraphs if p.text.strip()]


def build_question_from_document(path, file_name: str):
    """Parse docx/pdf and return question dict, metadata, full_text, warnings."""
    path = Path(path)
    if is_legacy_doc(file_name):
        from document.convert_doc import convert_doc_to_docx

        converted, err = convert_doc_to_docx(path)
        if not converted or not converted.exists():
            warnings = [{"code": "legacy_doc", "message": err or WARN_LEGACY_DOC["message"]}]
            question = {
                "id": 0,
                "type": "lab_report",
                "title": file_name.replace(".doc", ""),
                "full_text": "",
                "metadata": {},
                "placeholder": "",
                "image_assets": [],
                "image_bundle_meta": {},
            }
            return question, {}, "", warnings
        import shutil

        shutil.copy2(converted, path)
        file_name = converted.name

    full_text, metadata, hints = parse_document(path, file_name)
    warnings = collect_parse_warnings(full_text, metadata, file_name)
    warnings.extend(_pdf_hints_to_warnings(hints))
    fmt = metadata.get("source_format") or document_format(file_name)
    title_base = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    image_assets = metadata.get("image_assets") or []
    image_bundle_meta = metadata.get("image_bundle_meta") or {}
    question_metadata = {**metadata, "source_format": fmt}
    question_metadata.pop("image_assets", None)
    question_metadata.pop("image_bundle_meta", None)
    question = {
        "id": 0,
        "type": "lab_report",
        "title": metadata.get("experiment_title", title_base),
        "full_text": full_text,
        "metadata": question_metadata,
        "placeholder": "",
        "image_assets": image_assets,
        "image_bundle_meta": image_bundle_meta,
    }
    return question, question_metadata, full_text, warnings


def build_question_from_docx(path, file_name: str):
    """Backward-compatible alias for build_question_from_document."""
    return build_question_from_document(path, file_name)


def detect_docx_sections(path):
    """
    Detect section structure from a docx file.

    Returns dict with:
        sections_detected: [{index, heading, semantic}, ...]
        section_map: {steps/result/summary: {type, heading, para_index} or None}
        fill_hints: {screenshots_target, merge_*, ...}
        report_layout: "training_table" | "standard_sections" | "variant_sections" | None
        table_map: [{table, row, col, label, text_excerpt}, ...]
    """
    from modules.fill_report import _build_fill_hints, detect_sections

    if not DOCX_OK:
        return {}

    from docx import Document

    doc = Document(str(path))
    paragraphs = list(doc.paragraphs)
    sections_detected, section_map = detect_sections(paragraphs)
    fill_hints = _build_fill_hints(section_map)

    # Determine report_layout from detected sections + table detection
    layout_info = _detect_table_layout(doc)
    report_layout = layout_info.get("report_layout") or ""
    if not report_layout:
        mapped_count = sum(1 for v in section_map.values() if v)
        if mapped_count == 3:
            has_standard = all(
                section_map[k] and any(
                    str(n) in (section_map[k].get("heading") or "")
                    for n in ["三", "四", "五"]
                )
                for k in ["steps", "result", "summary"]
            )
            report_layout = "standard_sections" if has_standard else "variant_sections"
        elif mapped_count >= 1:
            report_layout = "variant_sections"

    return {
        "sections_detected": sections_detected,
        "section_map": section_map,
        "fill_hints": fill_hints,
        "report_layout": report_layout,
        "table_map": layout_info.get("table_map") or [],
    }
