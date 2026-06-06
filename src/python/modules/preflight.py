"""
Zero-LLM preflight: syntax, UML, answer schema (Phase 2b B1).
"""

from __future__ import annotations

import ast
import json
from typing import Any

from modules.uml import VALID_DIAGRAM_KINDS, extract_diagrams
from modules.uml_consistency import check_uml_code_consistency
from text_sanitize import find_emoji

try:
    from dfd_layout import extract_dfd_json, validate_dfd
except ImportError:
    extract_dfd_json = None  # type: ignore
    validate_dfd = None  # type: ignore


def _check_code_syntax(code: str, language: str) -> dict[str, Any]:
    lang = (language or "java").lower()
    if not (code or "").strip():
        return {"id": "code_syntax", "ok": False, "message": "代码为空"}

    if lang == "python":
        try:
            ast.parse(code)
            return {"id": "code_syntax", "ok": True, "message": "Python 语法通过"}
        except SyntaxError as e:
            return {"id": "code_syntax", "ok": False, "message": f"Python 语法错误: {e}"}

    if lang in ("java", "c", "cpp"):
        # 首期：括号配对 + 基本结构（无 javac 时）
        opens = code.count("{") + code.count("(") + code.count("[")
        closes = code.count("}") + code.count(")") + code.count("]")
        if opens != closes:
            return {
                "id": "code_syntax",
                "ok": False,
                "message": f"括号可能不匹配 ({opens} vs {closes})",
            }
        if lang == "java" and "class " not in code:
            return {"id": "code_syntax", "ok": False, "message": "Java 代码缺少 class 定义"}
        return {"id": "code_syntax", "ok": True, "message": f"{lang} 基本结构检查通过"}

    return {"id": "code_syntax", "ok": True, "message": f"未对 {lang} 做深度语法检查"}


def _check_dfd_diagram(d: dict, index: int) -> list[str]:
    errors: list[str] = []
    if not extract_dfd_json or not validate_dfd:
        return errors
    data = extract_dfd_json(d)
    if not data:
        errors.append(f"图{index}: kind=dfd 需要 dfd_json 或 source 中的 JSON")
        return errors
    for msg in validate_dfd(data):
        errors.append(f"图{index}: {msg}")
    return errors


def _check_uml(diagrams: list) -> dict[str, Any]:
    if not diagrams:
        return {"id": "uml_schema", "ok": True, "message": "无 UML 图"}
    errors = []
    for i, d in enumerate(diagrams):
        kind = (d.get("kind") or "class").strip().lower()
        if kind not in VALID_DIAGRAM_KINDS:
            errors.append(f"图{i + 1}: 非法 kind={kind!r}")
            continue
        if kind == "dfd" or d.get("source_engine") == "graphviz":
            errors.extend(_check_dfd_diagram(d, i + 1))
            continue
        puml = (d.get("plantuml") or d.get("source") or "").strip()
        if isinstance(puml, dict):
            puml = ""
        if not puml:
            errors.append(f"图{i + 1}: 缺少 plantuml")
            continue
        if "@startuml" not in puml.lower():
            errors.append(f"图{i + 1}: 缺少 @startuml")
        if "@enduml" not in puml.lower():
            errors.append(f"图{i + 1}: 缺少 @enduml")
    if errors:
        return {"id": "uml_schema", "ok": False, "message": "; ".join(errors)}
    return {"id": "uml_schema", "ok": True, "message": f"{len(diagrams)} 个图表定义格式通过"}


def _check_answer_schema(parsed: dict) -> dict[str, Any]:
    missing = []
    for key in ("steps_analysis", "result_description", "summary", "code"):
        if not (parsed.get(key) or "").strip():
            missing.append(key)
    if missing:
        return {
            "id": "answer_schema",
            "ok": False,
            "message": f"缺少字段: {', '.join(missing)}",
        }
    return {"id": "answer_schema", "ok": True, "message": "答题 JSON 结构完整"}


def _check_execution_pattern(code: str, language: str) -> dict[str, Any]:
    """Detect code patterns that affect execution strategy.

    Returns {id, ok, pattern, message, risk}.
    ``ok=False`` means the code should NOT be executed as-is (e.g. web server).
    """
    import re

    if not (code or "").strip():
        return {"id": "exec_pattern", "ok": True, "pattern": "script", "message": "代码为空", "risk": None}

    emoji_samples = find_emoji(code)
    if emoji_samples:
        shown = " ".join(repr(c) for c in emoji_samples)
        return {
            "id": "exec_pattern", "ok": False, "pattern": "emoji_in_code",
            "message": (
                f"代码含 emoji/装饰性符号（如 {shown}），Windows GBK 环境无法编码。"
                "请移除所有 emoji，println/print 输出只使用中文和 ASCII。"
            ),
            "risk": "compile_error",
        }

    # JSP directives/scriptlets — not valid Java syntax at all
    if (language or "").lower() == "java" and re.search(
        r"<%@\s*(page|include|taglib)|<%\s*[@=!]|<jsp:",
        code,
    ):
        return {
            "id": "exec_pattern", "ok": False, "pattern": "jsp_tags",
            "message": (
                "代码包含 JSP 指令或脚本标记（<%@、<%、<jsp:），这不是 Java 语法，"
                "javac 编译器无法解析。请完全去掉 JSP 标记，将业务逻辑改写为纯 Java SE "
                "类，在 public static void main 中硬编码测试数据并 print 结果。"
            ),
            "risk": "compile_error",
        }

    # HTML markup in .java source — syntax error
    if (language or "").lower() == "java" and re.search(
        r"<!DOCTYPE\s+html|<html\b|<head\b|<body\b|<div\b|<form\b|<input\b|<table\b",
        code,
    ):
        return {
            "id": "exec_pattern", "ok": False, "pattern": "html_in_java",
            "message": (
                "代码在 .java 文件中混合了 HTML 模板内容（<!DOCTYPE、<html>、<form> 等），"
                "这些不是 Java 语法，javac 无法编译。请去掉所有 HTML，业务逻辑改为 "
                "public static void main 中用 System.out.println 输出结果。"
            ),
            "risk": "compile_error",
        }

    # Servlet API imports — compilable with servlet-api.jar, but we don't have it
    if (language or "").lower() == "java" and re.search(
        r"import\s+javax\.servlet|import\s+jakarta\.servlet|extends\s+HttpServlet",
        code,
    ):
        return {
            "id": "exec_pattern", "ok": False, "pattern": "servlet_api",
            "message": (
                "代码使用了 Servlet API（javax.servlet/jakarta.servlet.HttpServlet），"
                "当前运行环境没有 Servlet 容器和 servlet-api.jar，无法编译运行。"
                "请改写为纯 Java SE 程序：去掉所有 Servlet 相关 import 和继承，"
                "将业务逻辑提取到独立的 public static void main 类中测试。"
            ),
            "risk": "compile_error",
        }

    # Web framework — will block forever in subprocess
    if re.search(
        r"app\.run\(|flask\.Flask|from\s+flask\s+import|http\.server|socketserver|"
        r"server\.forever\(|\.listen\(\d|\.serve_forever\(|make_server\(",
        code,
    ):
        return {
            "id": "exec_pattern", "ok": False, "pattern": "web_server",
            "message": "代码启动了 Web 服务器（如 Flask/Django/http.server），无法普通运行",
            "risk": "timeout_blocking",
        }

    # Interactive input — can't run headless
    if re.search(
        r"\binput\(|\braw_input\(|Scanner\s+.*System\.in|scanf\(|Console\.ReadLine|"
        r"prompt\(|readline\(\)|fgets\(|getchar\(\)",
        code,
    ):
        return {
            "id": "exec_pattern", "ok": False, "pattern": "interactive",
            "message": "代码需要交互输入（input/scanf/Scanner），无法 headless 运行",
            "risk": "timeout_blocking",
        }

    # Infinite loop without break
    if re.search(r"while\s+True\s*:", code) and "break" not in code:
        return {
            "id": "exec_pattern", "ok": True, "pattern": "possible_infinite",
            "message": "检测到 while True 无 break，可能无限运行",
            "risk": "timeout_risk",
        }
    if re.search(r"while\s*\(\s*1\s*\)", code) and "break" not in code:
        return {
            "id": "exec_pattern", "ok": True, "pattern": "possible_infinite",
            "message": "检测到 while(1) 无 break，可能无限运行",
            "risk": "timeout_risk",
        }

    return {
        "id": "exec_pattern", "ok": True, "pattern": "script",
        "message": "代码为普通脚本", "risk": None,
    }


def _check_uml_consistency(solve_data: dict, diagrams: list) -> dict[str, Any]:
    code = solve_data.get("code") or (solve_data.get("parsed") or {}).get("code") or ""
    language = solve_data.get("language") or (solve_data.get("parsed") or {}).get("language") or "java"
    result = check_uml_code_consistency(code, diagrams, language=language)
    return {
        "id": "uml_code_consistency",
        "ok": result.get("ok", True),
        "message": result.get("message", ""),
        "missing_in_uml": result.get("missing_in_uml") or [],
        "coverage": result.get("coverage"),
    }


def _normalize_diagrams_list(parsed: dict) -> list:
    d = (parsed or {}).get("diagrams")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except Exception:
            d = []
    return d if isinstance(d, list) else []


def run_preflight(solve_data: dict, *, include_uml: bool = False) -> dict[str, Any]:
    """
    Returns { ok, checks[], failed_ids[] }.
    """
    parsed = solve_data.get("parsed") or {}
    code = solve_data.get("code") or parsed.get("code") or ""
    language = solve_data.get("language") or parsed.get("language") or "java"

    checks = [
        _check_answer_schema(parsed),
        _check_code_syntax(code, language),
        _check_execution_pattern(code, language),
    ]
    if include_uml or parsed.get("diagrams"):
        diagrams = _normalize_diagrams_list(parsed)
        checks.append(_check_uml(diagrams))
        renderable = extract_diagrams(parsed)
        if renderable and (code or parsed.get("code")):
            checks.append(_check_uml_consistency(solve_data, renderable))

    failed = [c["id"] for c in checks if not c.get("ok")]
    return {
        "ok": len(failed) == 0,
        "checks": checks,
        "failed_ids": failed,
    }
