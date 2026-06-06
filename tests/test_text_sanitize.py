"""Tests for emoji detection and log sanitization."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.preflight import _check_execution_pattern  # noqa: E402
from text_sanitize import find_emoji, has_emoji, strip_emoji  # noqa: E402


def test_find_emoji_detects_common_symbols():
    samples = find_emoji('System.out.println("失败 ❌");')
    assert "\u274c" in samples or "❌" in samples


def test_has_emoji_chinese_ok():
    assert has_emoji("绘制圆形: 已擦除") is False
    assert has_emoji("测试 ✅ 通过") is True


def test_strip_emoji_removes_symbols():
    assert strip_emoji("ok ✅ done") == "ok  done"


def test_preflight_blocks_emoji_in_code():
    check = _check_execution_pattern(
        'public class Main { public static void main(String[] a) { System.out.println("❌"); } }',
        "java",
    )
    assert check["ok"] is False
    assert check["pattern"] == "emoji_in_code"


def test_preflight_allows_chinese_output():
    check = _check_execution_pattern(
        'public class Main { public static void main(String[] a) { System.out.println("测试通过"); } }',
        "java",
    )
    assert check["ok"] is True


def test_log_sanitize_strips_emoji():
    from log_util import sanitize_log_message

    msg = sanitize_log_message("run ok ✅")
    assert "✅" not in msg
    assert "run ok" in msg
