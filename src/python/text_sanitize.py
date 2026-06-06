"""Detect and strip emoji / decorative Unicode in generated code and logs."""

from __future__ import annotations

import re

# Dingbats (✅❌), misc symbols, emoji blocks — CJK is allowed (outside these ranges).
_EMOJI_RE = re.compile(
    "["
    "\U00002600-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\U0001F300-\U0001FAFF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "]",
    re.UNICODE,
)


def find_emoji(text: str, *, max_samples: int = 5) -> list[str]:
    """Return up to max_samples distinct emoji/symbol characters found in text."""
    if not text:
        return []
    seen: list[str] = []
    for ch in _EMOJI_RE.findall(text):
        if ch not in seen:
            seen.append(ch)
        if len(seen) >= max_samples:
            break
    return seen


def has_emoji(text: str) -> bool:
    return bool(text and _EMOJI_RE.search(text))


def strip_emoji(text: str) -> str:
    if not text:
        return text
    return _EMOJI_RE.sub("", text)


def ascii_safe(text: str) -> str:
    """Make text safe for Windows GBK stdout (replace unencodable chars)."""
    if not text:
        return text
    try:
        import sys

        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        return text.encode(enc, errors="replace").decode(enc)
    except Exception:
        return text.encode("ascii", errors="replace").decode("ascii")
