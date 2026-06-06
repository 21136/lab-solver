"""
Token budget: section-priority trimming instead of hard [:N] truncation.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十]+[章节部分]|[一二三四五六七八九十][、．.]|"
    r"[三四五][、．.]\s*|#{1,3}\s+)(.+)$",
    re.MULTILINE,
)

_SECTION_PRIORITY = (
    ("步骤", 0),
    ("结果", 1),
    ("总结", 2),
    ("要求", 3),
    ("原理", 4),
    ("目的", 5),
    ("封面", 6),
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 3)."""
    if not text:
        return 0
    return max(1, len(text) // 3)


def _section_priority(heading: str) -> int:
    h = heading or ""
    for key, prio in _SECTION_PRIORITY:
        if key in h:
            return prio
    return 50


def split_by_headings(text: str, section_map: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Split report text into sections by headings."""
    if section_map and section_map.get("sections"):
        out = []
        for item in section_map["sections"]:
            if not isinstance(item, dict):
                continue
            heading = str(item.get("heading") or item.get("title") or "")
            body = str(item.get("text") or item.get("body") or "")
            if body.strip():
                out.append({"heading": heading, "text": body.strip()})
        if out:
            return out

    text = text or ""
    if not text.strip():
        return [{"heading": "", "text": ""}]

    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [{"heading": "正文", "text": text.strip()}]

    sections: list[dict[str, Any]] = []
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            sections.append({"heading": "前文", "text": pre})

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = m.group(0).strip()
        body = text[m.end() : end].strip()
        sections.append({"heading": heading, "text": body})

    return sections or [{"heading": "正文", "text": text.strip()}]


def _sort_sections(
    sections: list[dict[str, Any]], preserve_sections: list[str]
) -> list[dict[str, Any]]:
    preserve = set(preserve_sections or [])

    def key(sec: dict) -> tuple[int, int]:
        heading = sec.get("heading") or ""
        if heading in preserve or any(p in heading for p in preserve):
            return (0, 0)
        return (1, _section_priority(heading))

    return sorted(sections, key=key)


def format_for_prompt(sections: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for sec in sections:
        heading = (sec.get("heading") or "").strip()
        body = (sec.get("text") or "").strip()
        if not body:
            continue
        if sec.get("truncated"):
            orig = sec.get("original_len", len(body))
            body = f"{body}\n[已截断，原文 {orig} 字]"
        if heading:
            parts.append(f"## {heading}\n{body}")
        else:
            parts.append(body)
    return "\n\n".join(parts)


def fit_budget(
    text: str,
    budget_tokens: int,
    preserve_sections: Optional[list[str]] = None,
    section_map: Optional[dict[str, Any]] = None,
) -> str:
    """
    Trim text by section priority within token budget.
    preserve_sections: heading substrings to keep first (e.g. 步骤, 结果).
    """
    if not text:
        return ""
    budget_tokens = max(200, int(budget_tokens or 2500))
    if estimate_tokens(text) <= budget_tokens:
        return text

    sections = split_by_headings(text, section_map)
    ordered = _sort_sections(sections, preserve_sections or ["步骤", "结果"])
    result: list[dict[str, Any]] = []
    remaining = budget_tokens

    for section in ordered:
        body = section.get("text") or ""
        if not body:
            continue
        need = estimate_tokens(body)
        if need <= remaining:
            result.append(section)
            remaining -= need
        elif remaining > 80:
            ratio = remaining / max(need, 1)
            cut = max(80, int(len(body) * ratio))
            result.append(
                {
                    **section,
                    "text": body[:cut],
                    "truncated": True,
                    "original_len": len(body),
                }
            )
            remaining = 0
            break
        else:
            break

    if not result:
        cut = budget_tokens * 3
        return text[:cut] + f"\n[已截断，原文 {len(text)} 字]"
    return format_for_prompt(result)
