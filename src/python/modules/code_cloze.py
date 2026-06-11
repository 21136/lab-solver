"""Code cloze (代码完形填空) detection and normalization helpers."""

from __future__ import annotations

import re
from typing import Any

_BLANK_PATTERNS = (
    re.compile(r"\(\s*(\d+)\s*\)"),
    re.compile(r"（\s*(\d+)\s*）"),
)
_CODE_HINT_RE = re.compile(
    r"\b(class|public|private|protected|extends|implements|interface|def|function|import|return)\b|//|/\*",
    re.IGNORECASE,
)
_LANG_HINTS = (
    ("java", re.compile(r"\b(public\s+class|extends|implements|String\s+\w+|new\s+\w+\()", re.IGNORECASE)),
    ("python", re.compile(r"\bdef\s+\w+\(|import\s+\w+|print\(", re.IGNORECASE)),
    ("javascript", re.compile(r"\bfunction\s+\w+\(|console\.log|const\s+\w+\s*=", re.IGNORECASE)),
)


def detect_code_cloze(text: str) -> dict[str, Any]:
    raw = text or ""
    numbers: set[int] = set()
    for pat in _BLANK_PATTERNS:
        for m in pat.finditer(raw):
            try:
                numbers.add(int(m.group(1)))
            except Exception:
                continue
    blanks = sorted(numbers)
    has_code_hints = bool(_CODE_HINT_RE.search(raw))
    is_code_cloze = len(blanks) >= 2 and has_code_hints
    language = ""
    for lang, pat in _LANG_HINTS:
        if pat.search(raw):
            language = lang
            break
    return {
        "is_code_cloze": is_code_cloze,
        "blank_count": len(blanks),
        "blanks": blanks,
        "has_code_hints": has_code_hints,
        "language_hint": language,
    }


def normalize_code_cloze_parsed(
    parsed: dict[str, Any],
    *,
    detected_blanks: list[int] | None = None,
) -> dict[str, Any]:
    out = dict(parsed or {})
    blanks_in = out.get("blanks") or {}
    normalized: dict[str, dict[str, str]] = {}
    if isinstance(blanks_in, dict):
        for k, v in blanks_in.items():
            kk = str(k).strip()
            if not kk:
                continue
            if isinstance(v, dict):
                normalized[kk] = {
                    "answer": str(v.get("answer") or "").strip(),
                    "brief": str(v.get("brief") or "").strip(),
                }
            else:
                normalized[kk] = {"answer": str(v).strip(), "brief": ""}
    elif isinstance(blanks_in, list):
        for item in blanks_in:
            if not isinstance(item, dict):
                continue
            n = item.get("n")
            if n is None:
                continue
            kk = str(n).strip()
            normalized[kk] = {
                "answer": str(item.get("answer") or "").strip(),
                "brief": str(item.get("brief") or item.get("explanation") or "").strip(),
            }
    if detected_blanks:
        for n in detected_blanks:
            normalized.setdefault(str(n), {"answer": "", "brief": ""})
    out["type"] = "code_cloze"
    out["blanks"] = normalized
    out["completed_code"] = str(out.get("completed_code") or "").strip()
    out["pattern_note"] = str(out.get("pattern_note") or "").strip()
    return out


def normalize_cloze_answer(s: str) -> str:
    """Trim and collapse internal whitespace for answer comparison (Phase E / Q4)."""
    return re.sub(r"\s+", " ", (s or "").strip())


def match_cloze_answer(
    user: str,
    primary: str,
    answer_alt: list[str] | None = None,
) -> bool:
    """True if normalized user input matches primary or any acceptable alternate."""
    norm_user = normalize_cloze_answer(user)
    if not norm_user:
        return False
    candidates = [primary, *(answer_alt or [])]
    return any(normalize_cloze_answer(c) == norm_user for c in candidates if c)


def normalize_reference_blanks(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize §3.1 blanks / reference_blanks into {n: {answer, answer_alt, brief}}."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            kk = str(k).strip()
            if not kk:
                continue
            if isinstance(v, dict):
                out[kk] = {
                    "answer": str(v.get("answer") or "").strip(),
                    "answer_alt": [
                        str(a).strip() for a in (v.get("answer_alt") or []) if a
                    ],
                    "brief": str(v.get("brief") or v.get("explanation") or "").strip(),
                }
            else:
                out[kk] = {"answer": str(v).strip(), "answer_alt": [], "brief": ""}
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            n = item.get("n")
            if n is None:
                continue
            kk = str(n).strip()
            out[kk] = {
                "answer": str(item.get("answer") or "").strip(),
                "answer_alt": [
                    str(a).strip() for a in (item.get("answer_alt") or []) if a
                ],
                "brief": str(item.get("brief") or item.get("explanation") or "").strip(),
            }
    return out

