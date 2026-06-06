"""In-memory log buffer and file append with sensitive-data redaction."""

import datetime
import hashlib
import re

from config import LOG_FILE

_log_buf = []

_KEY_PATTERNS = [
    re.compile(r"(api[_-]?key|apikey|x-api-key)\s*[:=]\s*\S+", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}\b"),
]

_FULL_TEXT_KV = re.compile(
    r'("full_text"|full_text)\s*[:=]\s*("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"]{80,}"|\'[^\']{80,}\')',
    re.I,
)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _redact_long_text(match: re.Match) -> str:
    raw = match.group(0)
    inner = match.group(2) if match.lastindex and match.lastindex >= 2 else raw
    quoted = inner.strip("\"'")
    if len(quoted) < 80:
        return raw
    label = match.group(1) if match.lastindex else "text"
    return f'{label}=<redacted len={len(quoted)} hash={_short_hash(quoted)}>'


def sanitize_log_message(msg) -> str:
    """Strip API keys, emoji, and long report bodies from log lines."""
    from text_sanitize import strip_emoji

    text = str(msg)
    for pat in _KEY_PATTERNS:
        text = pat.sub("<redacted>", text)
    text = _FULL_TEXT_KV.sub(_redact_long_text, text)
    text = strip_emoji(text)
    if len(text) > 500:
        text = text[:500] + f"...<truncated total_len={len(str(msg))}>"
    return text


def _safe_print(line: str) -> None:
    """Print without raising UnicodeEncodeError on Windows GBK consoles."""
    import sys

    try:
        print(line, end="")
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc), end="")


def log(level, tag, msg):
    safe_msg = sanitize_log_message(msg)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "level": level, "tag": tag, "msg": safe_msg}
    _log_buf.append(entry)
    if len(_log_buf) > 300:
        _log_buf.pop(0)
    line = f"[{ts}][{level}][{tag}] {safe_msg}\n"
    _safe_print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def logi(tag, msg):
    log("INFO", tag, msg)


def loge(tag, msg):
    log("ERROR", tag, msg)


def get_log_buffer():
    return _log_buf
