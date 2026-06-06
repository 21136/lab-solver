"""Shared heuristics for detecting code-related assignment text (no LLM deps)."""

_CODE_KEYWORDS = (
    "代码",
    "编程",
    "程序",
    "实现",
    "编写",
    "java",
    "python",
    "c语言",
    "c++",
    "javascript",
    "算法",
    "源码",
)


def assignment_needs_code(text: str, text_lower: str | None = None) -> bool:
    lower = text_lower if text_lower is not None else text.lower()
    return any(k in text or k in lower for k in _CODE_KEYWORDS)
