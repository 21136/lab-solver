"""LLM fix_code — orthogonal to revise_answer (Phase 2b).

L4.1: category-aware fix strategies for targeted code repair.
"""

from __future__ import annotations

from typing import Any

from agent.prompts import PROMPTS
from llm_client import chat, detect_lang_from_code
from modules.lab_parse import complete_lab_parsed, parse_lab_json


FIX_STRATEGIES = {
    "compile_error": (
        "修复编译/语法错误。确保代码语法正确、语言版本兼容，"
        "所有 import 和函数调用都存在。"
    ),
    "missing_module": (
        "错误是因为 import 了不可用的模块。请用标准库或已安装的库替代，"
        "或直接去掉该 import 重写功能。结合上方运行环境信息选择可用替代。"
    ),
    "timeout_blocking": (
        "代码启动了 Web 服务/阻塞进程（如 app.run()、while True 无 break、"
        "input() 等待输入），这导致无法在脚本执行器中运行。"
        "请改写为独立可运行的脚本：去掉服务器启动代码、交互输入和死循环，"
        "改为直接调用核心逻辑并 print 结果。"
    ),
    "timeout_slow": (
        "代码运行太慢导致超时。请优化算法复杂度（如 O(n²)→O(n log n)），"
        "或减少测试数据规模，用 print 输出关键结果验证正确性。"
    ),
    "runtime_exception": (
        "修复运行时异常。检查代码逻辑、边界条件和输入处理，"
        "确保代码在常见输入下能正常运行并输出预期结果。"
    ),
    "web_server": (
        "代码启动了 Web 服务器。请改写为独立脚本：去掉 app.run() 等启动代码，"
        "直接定义核心处理函数并调用它，用 print 输出结果。"
    ),
    "jsp_template": (
        "代码混合了 JSP/HTML 模板标记（如 <%@ page, <html>, <form> 等），"
        "这无法作为纯 Java 文件编译。请将模板部分全部移除，改为纯 Java "
        "独立程序：定义业务逻辑类，在 main 方法中硬编码测试数据并 print 结果。"
    ),
    "jsp_tags": (
        "代码包含 JSP 指令标记（<%@、<%、<jsp:），这不是 Java 语法。"
        "请完全移除所有 JSP 标记，将核心业务逻辑提取为纯 Java SE 类，"
        "在 public static void main 中直接调用并 System.out.println 输出。"
    ),
    "html_in_java": (
        "代码在 .java 文件中混入了 HTML 标签（<html>、<form>、<div> 等），"
        "导致 javac 编译失败。请去掉所有 HTML，改为在 main 方法中使用 "
        "System.out.println 输出纯文本结果。"
    ),
    "servlet_api": (
        "代码使用了 Servlet API（HttpServlet、HttpServletRequest 等），"
        "当前运行环境不提供 Servlet 容器，无法编译运行。请将代码改写为纯 "
        "Java SE 独立程序：去掉 extends HttpServlet、Servlet 相关 import，"
        "将 doGet/doPost 中的核心业务逻辑提取到 public static void main 中，"
        "用硬编码的测试输入代替 request.getParameter，用 System.out.println 代替 response.getWriter。"
    ),
    "interactive": (
        "代码需要交互输入。请改写为独立脚本：去掉 input()/scanf 等交互调用，"
        "改为硬编码测试数据或定义示例输入，直接运行并 print 结果。"
    ),
    "emoji_in_code": (
        "代码或 println/print 输出中含有 emoji 或装饰性 Unicode 符号（如 ✅❌🔴），"
        "Windows 默认 GBK 编码无法处理，会导致运行/日志崩溃。"
        "请移除所有 emoji，输出只使用中文汉字和 ASCII 字符。"
    ),
}


def _build_fix_strategy_section(category: str, pattern: str = "") -> str:
    """Build the fix strategy prompt section for a given error category."""
    strategy = ""
    # Try pattern-specific strategy first, then category
    if pattern and pattern in FIX_STRATEGIES:
        strategy = FIX_STRATEGIES[pattern]
    elif category and category in FIX_STRATEGIES:
        strategy = FIX_STRATEGIES[category]
    if strategy:
        return f"\n【修复策略】{strategy}\n"
    return ""


def fix_code_from_error(
    settings: dict,
    *,
    code: str = "",
    code_files: list[dict] | None = None,
    main_file: str = "",
    language: str,
    error_output: str,
    report_excerpt: str = "",
    category: str = "",
    pattern: str = "",
) -> dict[str, Any]:
    """Return updated { code, code_files, main_file, language, parsed, category }.

    When ``category`` is provided, the fix prompt includes a targeted
    strategy instead of generic repair instructions.
    """
    from config import (
        build_c_env_section,
        build_java_env_section,
        build_js_env_section,
        build_python_env_section,
    )

    api_key = settings.get("api_key", "")
    provider = settings.get("provider", "deepseek")
    model = settings.get("model", "deepseek-chat")
    custom_url = settings.get("custom_url") or settings.get("customUrl") or ""

    # Build language-specific env section
    lang_lower = (language or "").lower()
    env_map = {
        "python": build_python_env_section,
        "java": build_java_env_section,
        "c": build_c_env_section,
        "cpp": build_c_env_section,
        "javascript": build_js_env_section,
    }
    env_builder = env_map.get(lang_lower, build_python_env_section)
    env_section = env_builder()
    if env_section:
        env_section = "【运行环境】代码必须能在以下环境运行：\n" + env_section + "\n"

    # Category-specific fix strategy
    strategy_section = _build_fix_strategy_section(category, pattern)

    # Build code_files_text for prompt
    files = code_files or []
    if not files and code:
        ext = _ext_for_lang(language)
        files = [{"name": f"main{ext}", "code": code}]
    code_files_text = "\n\n".join(
        f"// 文件: {f['name']}\n{f.get('code', '')[:4000]}" for f in files
    ) if files else code[:6000]

    prompt = PROMPTS["fix_code"].render(
        language=language,
        code_files_text=code_files_text or "",
        error_output=(error_output or "")[:2000],
        report_excerpt=(report_excerpt or "")[:1500],
        env_section=env_section,
    ) + strategy_section

    result = chat(
        api_key,
        provider,
        model,
        prompt,
        custom_url=custom_url,
        max_tokens=4000,
        phase="fix_code",
    )
    raw = parse_lab_json(result.get("content") or "")
    new_code = (raw.get("code") or "").strip()
    new_code_files = raw.get("code_files") or []
    new_main_file = raw.get("main_file") or main_file
    if not new_code and not new_code_files:
        from llm_client import extract_code_block

        new_code = extract_code_block(result.get("content") or "", language) or code
    lang = raw.get("language") or detect_lang_from_code(new_code) or language
    parsed_patch = {k: v for k, v in raw.items() if k in (
        "steps_analysis",
        "result_description",
        "expected_output",
        "summary",
        "code",
        "code_files",
        "main_file",
        "language",
        "diagrams",
    )}
    return {
        "code": new_code,
        "code_files": new_code_files,
        "main_file": new_main_file,
        "language": lang,
        "parsed_patch": parsed_patch,
        "reasoning_content": result.get("reasoning_content") or "",
        "category": category,
    }


def _ext_for_lang(language: str) -> str:
    return {"python": ".py", "java": ".java", "c": ".c", "cpp": ".cpp",
            "javascript": ".js"}.get((language or "python").lower(), ".py")


def apply_fix_to_solve_data(solve_data: dict, fix: dict) -> dict:
    """Merge fix into solve_lab module data."""
    out = dict(solve_data)
    out["code"] = fix.get("code") or out.get("code")
    out["language"] = fix.get("language") or out.get("language")
    if fix.get("code_files"):
        out["code_files"] = fix["code_files"]
    if fix.get("main_file"):
        out["main_file"] = fix["main_file"]
    parsed = dict(out.get("parsed") or {})
    patch = fix.get("parsed_patch") or {}
    parsed.update(patch)
    if out.get("code"):
        parsed["code"] = out["code"]
    parsed = complete_lab_parsed(parsed, out.get("answer") or "")
    out["parsed"] = parsed
    return out
