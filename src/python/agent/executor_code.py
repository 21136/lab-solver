"""Code execution and fix module runners."""

from __future__ import annotations

from agent.executor_common import _fail_result, _get_solve_data, _ok_result
from agent.executor_dirty import mark_dirty_from_revise
from agent.types import ModuleResult
from log_util import logi
from modules.run_code import get_java_exe
from modules.solve_lab import solve_lab


def _guess_filename_from_lang(language: str) -> str:
    ext = {"python": ".py", "java": ".java", "c": ".c", "cpp": ".cpp",
           "javascript": ".js"}.get((language or "python").lower(), ".py")
    return f"main{ext}"


def _run_run_code(ctx: dict, params: dict) -> ModuleResult:
    """Execute code with preflight check → classify → fix → retry → degrade loop."""
    from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
    from modules.preflight import _check_execution_pattern
    from modules.run_code import classify_run_error, execute_code, execute_multi_file

    solve = _get_solve_data(ctx)
    session = ctx.get("solve_session") or solve.get("solve_session") or {}
    pipeline_meta = solve.get("pipeline_meta") or {}
    code_status = (session.get("code_status") or pipeline_meta.get("code_status") or "").lower()
    if code_status == "verified":
        run_result = session.get("run_result") or {}
        output = run_result.get("output") or run_result.get("stdout") or ""
        logi("executor", "run_code skipped: already verified in solve_lab V4 pipeline")
        verified_files = session.get("code_files") or solve.get("code_files") or []
        verified_main = session.get("main_file") or solve.get("main_file") or ""
        return _ok_result(
            "run_code",
            {
                "output": output,
                "error": False,
                "is_error": False,
                "degraded": False,
                "reused_from_solve_lab": True,
                "code_files": verified_files,
                "main_file": verified_main,
            },
            params,
        )
    code_files = solve.get("code_files") or []
    main_file = solve.get("main_file") or ""
    code = solve.get("code") or ""
    language = solve.get("language") or params.get("language") or "java"

    # Normalize: single code string → code_files
    if not code_files and code:
        main_file = main_file or _guess_filename_from_lang(language)
        code_files = [{"name": main_file, "code": code}]
    if not code_files:
        return _fail_result("run_code", "无代码可运行", params)
    if not main_file:
        main_file = code_files[0].get("name", "main.py")

    # Preflight: detect execution pattern in all files
    combined_code = "\n".join(f.get("code", "") for f in code_files)
    pattern_check = _check_execution_pattern(combined_code, language)
    pattern = pattern_check.get("pattern", "script")
    pattern_ok = pattern_check.get("ok", True)

    is_multi_file = len(code_files) > 1

    # Patterns that can't run as-is — skip execution entirely, go direct to fix
    if not pattern_ok:
        logi("executor", f"run_code skipped: pattern={pattern} → fix_code")
        # In ReAct mode, surface the preflight failure to the LLM directly
        # so it can observe the specific reason and call fix_code itself.
        # Standard/deep mode keeps the internal auto-fix loop.
        if ctx.get("run_mode") == "react":
            return _fail_result("run_code", pattern_check["message"], params)
        category = {
            "web_server": "timeout_blocking",
            "interactive": "timeout_blocking",
            "jsp_template": "compile_error",
            "jsp_tags": "compile_error",
            "html_in_java": "compile_error",
            "servlet_api": "compile_error",
            "emoji_in_code": "compile_error",
        }.get(pattern, "timeout_blocking")
        result = _fix_and_retry(
            ctx,
            params,
            code or combined_code,
            language,
            pattern_check["message"],
            category=category,
            pattern=pattern,
        )
        if result.get("data") and isinstance(result["data"], dict):
            result["data"].setdefault("error_category", category)
        return result

    if language == "java" and not get_java_exe():
        return _fail_result("run_code", "需要 JRE", params)

    try:
        if is_multi_file:
            output, is_error = execute_multi_file(code_files, language, main_file)
        else:
            output, is_error = execute_code(code_files[0]["code"], language)
    except Exception as e:
        return _fail_result("run_code", str(e), params)

    if not is_error:
        return _ok_result(
            "run_code",
            {"output": output, "error": False, "is_error": False, "degraded": False,
             "code_files": code_files, "main_file": main_file},
            params,
        )

    # Classify and fix
    error_class = classify_run_error(output, pattern)
    category = error_class.get("category", "runtime_exception")
    error_msg = f"{error_class.get('message', '')}: {output[:200]}"

    return _fix_and_retry(ctx, params, language, error_msg,
                          code=code, code_files=code_files, main_file=main_file,
                          category=category, pattern=pattern)


def _regenerate_code(ctx: dict, params: dict, language: str,
                     error_msg: str, category: str, retry_count: int) -> ModuleResult:
    """Abandon incremental fixes — regenerate answer from scratch with error context.

    When the same error category persists through 2+ fix_code attempts,
    patching is making things worse. Re-solve with the accumulated failure
    knowledge injected as a stern constraint.
    """
    from modules.fix_code import apply_fix_to_solve_data
    from modules.run_code import execute_code, execute_multi_file

    logi("executor", f"regenerating code (same {category} x2+, retry={retry_count})")

    # Inject error as a hard constraint into the question
    question = dict(ctx.get("question") or {})
    question["type"] = "lab_report"
    full_text = ctx.get("planner_input_text") or ctx.get("report_text") or question.get("full_text") or ""
    question["full_text"] = full_text + (
        f"\n\n【上次代码被拒绝 — 必须避免】"
        f"上轮生成的 {language} 代码编译/运行失败（{category}），经过多次修复仍无法通过。"
        f"请完全放弃上一轮的代码思路，从零重新生成。"
        f"错误信息: {error_msg[:500]}"
        f"\n特别注意：确保代码是纯 {language} 语法，不要混入其他语言，不要引入不可用的库。"
    )
    question["preferred_lang"] = language

    settings = ctx["settings"]
    try:
        result = solve_lab(
            settings["api_key"],
            settings.get("provider", "deepseek"),
            settings.get("model", "deepseek-chat"),
            question,
            custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
            include_uml=False,
            format_spec=ctx.get("format_spec"),
        )
    except Exception as e:
        return _degrade_run_code(ctx, params, category, f"regenerate failed: {e}")

    ctx.setdefault("module_results", {})["solve_lab"] = _ok_result(
        "solve_lab", result, params
    )
    mark_dirty_from_revise(ctx, changed_fields=["code", "language"], scope=["code"])

    # Re-run the regenerated code
    code_files = result.get("code_files") or []
    main_file = result.get("main_file") or ""
    code = result.get("code") or ""
    new_lang = result.get("language") or language
    try:
        if code_files:
            output, is_error = execute_multi_file(code_files, new_lang, main_file)
        else:
            output, is_error = execute_code(code, new_lang)
        if not is_error:
            return _ok_result(
                "fix_code",
                {"fixed": True, "language": new_lang, "retries": retry_count + 1,
                 "regenerated": True},
                params,
            )
        # Still failing after regeneration → degrade
        from modules.run_code import classify_run_error
        new_class = classify_run_error(output, "")
        return _degrade_run_code(
            ctx, params,
            new_class.get("category", category),
            f"regenerated still fails: {output[:200]}",
        )
    except Exception as e:
        return _degrade_run_code(ctx, params, category, f"regenerated run error: {e}")


def _fix_and_retry(ctx: dict, params: dict, language: str,
                   error_msg: str, *, code: str = "",
                   code_files: list[dict] | None = None,
                   main_file: str = "",
                   category: str = "", pattern: str = "",
                   retry_count: int = 0,
                   same_error_count: int = 0) -> ModuleResult:
    """Fix code → retry → regenerate → degrade loop.

    When the same error category persists through 2 fix_code rounds,
    incremental patching is abandoned in favour of a fresh solve_lab
    with the error context injected as a hard constraint.
    """
    from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
    from modules.run_code import execute_code, execute_multi_file

    MAX_FIX_RETRIES = 3
    REGEN_THRESHOLD = 2  # Same error category × N consecutive rounds → regenerate

    if retry_count >= MAX_FIX_RETRIES:
        return _degrade_run_code(ctx, params, category, error_msg)

    # Same error keeps coming back — patching is making things worse
    if same_error_count >= REGEN_THRESHOLD:
        return _regenerate_code(ctx, params, language, error_msg, category, retry_count)

    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    solve_data = dict(solve_mr.get("data") or {})
    files = code_files or []
    old_code = code or (files[0].get("code", "") if files else "")

    try:
        fix = fix_code_from_error(
            ctx["settings"],
            code=code,
            code_files=files if files else None,
            main_file=main_file,
            language=language,
            error_output=str(error_msg),
            report_excerpt=ctx.get("planner_input_text") or ctx.get("report_text") or "",
            category=category,
            pattern=pattern,
        )
        new_code = fix.get("code") or old_code
        new_files = fix.get("code_files") or []
        new_main = fix.get("main_file") or main_file
        new_lang = fix.get("language") or language

        is_multi = bool(new_files)

        # If fix didn't actually change code → count as same error
        if new_code.strip() == old_code.strip() and not new_files and retry_count > 0:
            return _fix_and_retry(ctx, params, language, error_msg,
                                  code=code, code_files=files, main_file=main_file,
                                  category=category, pattern=pattern,
                                  retry_count=retry_count + 1,
                                  same_error_count=same_error_count + 1)

        updated = apply_fix_to_solve_data(solve_data, fix)
        ctx.setdefault("module_results", {})["solve_lab"] = _ok_result(
            "solve_lab", updated, params
        )
        mark_dirty_from_revise(ctx, changed_fields=["code", "language"], scope=["code"])

        # Re-run with fixed code
        try:
            if is_multi:
                output, is_error = execute_multi_file(new_files, new_lang, new_main)
            else:
                output, is_error = execute_code(new_code, new_lang)
            if not is_error:
                return _ok_result(
                    "fix_code",
                    {"fixed": True, "language": new_lang, "retries": retry_count + 1},
                    params,
                )
            # Still failing → check if same error, then retry or regenerate
            from modules.run_code import classify_run_error
            new_class = classify_run_error(output, pattern)
            new_category = new_class.get("category", category)
            repeat = same_error_count + 1 if new_category == category else 0
            return _fix_and_retry(
                ctx, params, new_lang,
                f"{new_class.get('message', '')}: {output[:200]}",
                code=new_code, code_files=new_files, main_file=new_main,
                category=new_category,
                pattern=pattern,
                retry_count=retry_count + 1,
                same_error_count=repeat,
            )
        except Exception as e:
            return _fix_and_retry(ctx, params, new_lang, str(e),
                                  code=new_code, code_files=new_files,
                                  main_file=new_main,
                                  category=category, pattern=pattern,
                                  retry_count=retry_count + 1,
                                  same_error_count=same_error_count + 1)

    except Exception as e:
        if retry_count + 1 >= MAX_FIX_RETRIES:
            return _degrade_run_code(ctx, params, category, str(e))
        return _fix_and_retry(ctx, params, language, str(e),
                              code=code, code_files=files, main_file=main_file,
                              category=category, pattern=pattern,
                              retry_count=retry_count + 1,
                              same_error_count=same_error_count + 1)


def _degrade_run_code(ctx: dict, params: dict, category: str, error_msg: str) -> ModuleResult:
    """Final degradation: skip code execution, use expected_output as substitute."""
    solve = _get_solve_data(ctx)
    fallback_output = solve.get("parsed", {}).get("expected_output", "") or "(无输出)"
    logi("executor", f"degraded run_code: category={category} error={error_msg[:80]}")

    return _ok_result(
        "run_code",
        {
            "output": fallback_output,
            "error": False,
            "is_error": False,
            "degraded": True,
            "degraded_reason": f"代码执行失败({category}): {error_msg[:200]}",
            "error_category": category,
        },
        params,
    )


def _run_fix_code(ctx: dict, params: dict) -> ModuleResult:
    """LLM fix_code (standalone — called when fix_code is a separate plan step)."""
    from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error

    solve_mr = (ctx.get("module_results") or {}).get("solve_lab") or {}
    if not solve_mr.get("ok"):
        return _fail_result("fix_code", "无 solve_lab 结果可修复", params)

    solve_data = dict(solve_mr.get("data") or {})
    run_mr = (ctx.get("module_results") or {}).get("run_code") or {}
    err = (run_mr.get("data") or {}).get("output") or params.get("error") or "未知运行错误"
    code = solve_data.get("code") or ""
    code_files = solve_data.get("code_files") or []
    main_file = solve_data.get("main_file") or ""
    language = solve_data.get("language") or "java"
    if not code and not code_files:
        return _fail_result("fix_code", "无代码可修复", params)

    category = params.get("error_category") or ""

    try:
        from agent.prompts import record_prompt_version

        record_prompt_version(ctx, "fix_code")
        fix = fix_code_from_error(
            ctx["settings"],
            code=code,
            code_files=code_files if code_files else None,
            main_file=main_file,
            language=language,
            error_output=str(err),
            report_excerpt=ctx.get("planner_input_text") or ctx.get("report_text") or "",
            category=category,
        )
        updated = apply_fix_to_solve_data(solve_data, fix)
        ctx.setdefault("module_results", {})["solve_lab"] = _ok_result(
            "solve_lab", updated, params
        )
        mark_dirty_from_revise(ctx, changed_fields=["code", "language"], scope=["code"])
        return _ok_result(
            "fix_code",
            {"fixed": True, "language": updated.get("language")},
            params,
        )
    except Exception as e:
        return _fail_result("fix_code", str(e), params)
