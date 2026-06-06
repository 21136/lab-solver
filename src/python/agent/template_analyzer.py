"""
Answer template → format_spec (Phase 2b B4).

Rule-based structure extraction; optional LLM summary deferred to Phase 3+.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from config import DOCX_OK, TEMP_DIR
from log_util import logi
from modules.fill_report import SECTION_HEADER_PATTERNS
from modules.parse_report import extract_docx, is_legacy_doc

_CODE_MARKERS = re.compile(
    r"(public\s+class|def\s+\w+|#include\s*<|class\s+\w+\s*\{)",
    re.MULTILINE,
)
_IMAGE_MARKERS = re.compile(r"(图\s*\d|截图|\.png|\.jpg|插入图片)", re.IGNORECASE)

_SECTION_KEYS = ("steps", "result", "summary")
_SECTION_FALLBACK_TITLES = {
    "steps": ("实验步骤", "实验内容", "内容及步骤"),
    "result": ("实验结果", "结果与分析"),
    "summary": ("实验总结", "心得"),
}


def _section_bounds(paragraphs: list[str]) -> dict[str, tuple[int, int, str]]:
    """Map section key → (start_idx, end_idx, title_line)."""
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(paragraphs):
        stripped = line.strip()
        if not stripped or len(stripped) > 40:
            continue
        for key, pat in SECTION_HEADER_PATTERNS.items():
            if pat.match(stripped):
                hits.append((i, key, stripped))
                break
        else:
            for key, titles in _SECTION_FALLBACK_TITLES.items():
                if any(stripped.startswith(t) or stripped == t for t in titles):
                    hits.append((i, key, stripped))
                    break
    hits.sort(key=lambda x: x[0])
    bounds: dict[str, tuple[int, int, str]] = {}
    for idx, (start, key, title) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(paragraphs)
        if key not in bounds:
            bounds[key] = (start, end, title)
    return bounds


def _slice_section_text(paragraphs: list[str], start: int, end: int) -> str:
    body = paragraphs[start + 1 : end]
    return "\n".join(body).strip()


def _analyze_section_body(text: str, key: str) -> dict[str, Any]:
    chars = len(text)
    paras = [p for p in text.split("\n") if p.strip()]
    has_code = bool(_CODE_MARKERS.search(text))
    has_images = bool(_IMAGE_MARKERS.search(text)) or (
        key == "result" and ("图" in text or "截图" in text)
    )
    style = "numbered_list"
    if re.search(r"^\s*\d+[\.、]", text, re.MULTILINE):
        style = "numbered_list"
    elif re.search(r"^[-•]", text, re.MULTILINE):
        style = "bullet_list"
    else:
        style = "prose"
    if has_code and key == "steps":
        style = "numbered_list_then_code"
    tone = "first_person_reflective" if key == "summary" and re.search(
        r"(我|本实验|心得|体会)", text
    ) else "neutral"
    info: dict[str, Any] = {
        "avg_chars": chars,
        "paragraph_count": len(paras),
        "style": style,
        "tone": tone,
    }
    if has_code:
        info["code_in_section"] = True
    if has_images or key == "result":
        info["requires_images"] = has_images or key == "result"
        if has_images:
            info["image_count"] = len(re.findall(r"图\s*\d", text)) or 1
    return info


def build_section_map_from_text(full_text: str, section_keys=None) -> dict[str, Any]:
    keys = section_keys or _SECTION_KEYS
    paragraphs = [ln.strip() for ln in (full_text or "").split("\n") if ln.strip()]
    bounds = _section_bounds(paragraphs)
    section_map: dict[str, Any] = {}
    for key in keys:
        if key not in bounds:
            continue
        start, end, title = bounds[key]
        body = _slice_section_text(paragraphs, start, end)
        entry = {
            "title_pattern": title,
            **_analyze_section_body(body, key),
        }
        section_map[key] = entry
    return section_map


def _writing_habits(section_map: dict) -> dict[str, Any]:
    chars = [v.get("avg_chars", 0) for v in section_map.values()]
    total = sum(chars)
    verbosity = "low"
    if total > 3500:
        verbosity = "high"
    elif total > 1200:
        verbosity = "medium"
    uses_bullet = any(
        (v.get("style") or "").startswith("bullet") for v in section_map.values()
    )
    return {
        "verbosity": verbosity,
        "uses_bullet_in_steps": uses_bullet,
        "terminology_level": "undergraduate",
    }


def _fill_hints(section_map: dict) -> dict[str, Any]:
    result = section_map.get("result") or {}
    return {
        "preserve_tables": True,
        "image_after_result_text": bool(result.get("requires_images")),
    }


def analyze_template_text(
    full_text: str,
    *,
    template_type: str = "user_sample",
    file_name: str = "",
    section_keys=None,
) -> dict[str, Any]:
    """Rule-only format_spec from template full text."""
    section_map = build_section_map_from_text(full_text, section_keys=section_keys)
    spec: dict[str, Any] = {
        "template_type": template_type or "user_sample",
        "section_map": section_map,
        "writing_habits": _writing_habits(section_map),
        "fill_hints": _fill_hints(section_map),
        "source": "rules",
        "file_name": file_name or "",
    }
    spec["summary"] = format_spec_summary(spec)
    logi(
        "template_analyzer",
        f"type={template_type} sections={list(section_map.keys())} file={file_name}",
    )
    return spec


def analyze_template_file(
    path: Path,
    *,
    template_type: str = "user_sample",
) -> dict[str, Any]:
    full_text, metadata = extract_docx(path)
    spec = analyze_template_text(
        full_text,
        template_type=template_type,
        file_name=path.name,
    )
    spec["metadata"] = metadata
    return spec


def analyze_template_bytes(
    file_bytes: bytes,
    file_name: str,
    *,
    template_type: str = "user_sample",
) -> dict[str, Any]:
    if not DOCX_OK:
        raise ValueError("未安装 python-docx，无法解析模版")
    if is_legacy_doc(file_name):
        from document.convert_doc import convert_doc_to_docx

        tmp_doc = TEMP_DIR / f"tpl_{abs(hash(file_name))}.doc"
        tmp_doc.write_bytes(file_bytes)
        try:
            converted, err = convert_doc_to_docx(tmp_doc)
            if not converted or not converted.exists():
                raise ValueError(err or "旧版 .doc 无法转换，请安装 LibreOffice 或在 Word 中另存为 .docx")
            return analyze_template_file(converted, template_type=template_type)
        finally:
            try:
                tmp_doc.unlink(missing_ok=True)
            except OSError:
                pass
    suffix = ".docx" if not file_name.lower().endswith(".docx") else ""
    tmp = TEMP_DIR / f"tpl_{abs(hash(file_name))}{suffix or '.docx'}"
    tmp.write_bytes(file_bytes)
    try:
        return analyze_template_file(tmp, template_type=template_type)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def assignment_section_map(metadata: Optional[dict], assignment_text: str = "") -> dict[str, str]:
    """Detect which standard sections exist in the current assignment report."""
    sm = (metadata or {}).get("section_map")
    if isinstance(sm, dict) and sm:
        return {k: str(v) for k, v in sm.items() if k in _SECTION_KEYS}
    found: dict[str, str] = {}
    text = assignment_text or ""
    paragraphs = [ln.strip() for ln in text.split("\n") if ln.strip()]
    bounds = _section_bounds(paragraphs)
    for key, (_, _, title) in bounds.items():
        found[key] = title
    return found


def align_sections(
    format_spec: dict,
    assignment_metadata: Optional[dict] = None,
    assignment_text: str = "",
) -> dict[str, Any]:
    """
    Keep only template section constraints that match sections in the assignment.
    """
    tpl_map = dict(format_spec.get("section_map") or {})
    assign_map = assignment_section_map(assignment_metadata, assignment_text)
    if not assign_map:
        return {
            "aligned_section_map": tpl_map,
            "assignment_sections": {},
            "dropped_sections": [],
            "alignment": "no_assignment_sections",
        }
    aligned = {k: v for k, v in tpl_map.items() if k in assign_map}
    dropped = [k for k in tpl_map if k not in assign_map]
    return {
        "aligned_section_map": aligned,
        "assignment_sections": assign_map,
        "dropped_sections": dropped,
        "alignment": "partial" if dropped else "full",
    }


def to_format_constraints(format_spec: Optional[dict]) -> str:
    """Prompt block for solve_lab / LAB_PROMPT (format only, not experiment facts)."""
    if not format_spec:
        return ""
    sm = format_spec.get("aligned_section_map") or format_spec.get("section_map") or {}
    if not sm:
        return ""
    lines = [
        "【答题格式约束】（来自用户模版/范文，仅约束篇幅与排版习惯，不得编造实验内容）"
    ]
    label = {"steps": "实验步骤节", "result": "实验结果节", "summary": "实验总结节"}
    for key in _SECTION_KEYS:
        sec = sm.get(key)
        if not sec:
            continue
        parts = [label.get(key, key)]
        if sec.get("avg_chars"):
            parts.append(f"参考篇幅约 {sec['avg_chars']} 字")
        if sec.get("style"):
            parts.append(f"体裁={sec['style']}")
        if sec.get("code_in_section"):
            parts.append("步骤节可含代码块")
        if sec.get("requires_images"):
            n = sec.get("image_count") or 1
            parts.append(f"结果节建议配图约 {n} 张")
        if sec.get("tone"):
            parts.append(f"语气={sec['tone']}")
        lines.append("- " + "；".join(parts))
    habits = format_spec.get("writing_habits") or {}
    if habits.get("verbosity"):
        lines.append(f"- 整体详略: {habits['verbosity']}")
    hints = format_spec.get("fill_hints") or {}
    if hints.get("image_after_result_text"):
        lines.append("- 插图宜放在结果说明文字之后")
    return "\n".join(lines)


def format_spec_summary(format_spec: dict) -> str:
    sm = format_spec.get("section_map") or {}
    bits = []
    for key in _SECTION_KEYS:
        sec = sm.get(key)
        if not sec:
            continue
        bits.append(f"{key}:{sec.get('avg_chars', 0)}字")
    habits = (format_spec.get("writing_habits") or {}).get("verbosity", "")
    head = "、".join(bits) if bits else "未识别标准三节"
    return f"{head}" + (f"；详略={habits}" if habits else "")


def prepare_format_spec_for_session(
    format_spec: dict,
    *,
    assignment_metadata: Optional[dict] = None,
    assignment_text: str = "",
) -> dict[str, Any]:
    """Attach alignment + summary for planner/solve."""
    out = dict(format_spec)
    alignment = align_sections(out, assignment_metadata, assignment_text)
    out["aligned_section_map"] = alignment["aligned_section_map"]
    out["alignment"] = alignment
    out["summary"] = format_spec_summary(out)
    return out
