"""
Log sanitization: API Key must not appear in app.log output.

Usage:
  python tests/test_log_util.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from log_util import sanitize_log_message  # noqa: E402

_SECRET = "sk-test1234567890123456"


def _assert_no_secret(text: str) -> None:
    assert _SECRET not in text, f"secret leaked in: {text!r}"


def test_kv_and_bearer_redaction():
    for msg in (
        f"api_key={_SECRET}",
        f"api_key: {_SECRET}",
        f'{{"api_key": "{_SECRET}"}}',
        f"Bearer {_SECRET}",
        f"x-api-key: {_SECRET}",
    ):
        out = sanitize_log_message(msg)
        _assert_no_secret(out)
        assert "<redacted>" in out


if __name__ == "__main__":
    test_kv_and_bearer_redaction()
    print("test_log_util: OK")
