"""V4/V5 multi-phase solve pipeline — code first, internal validation, then report text."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from agent.prompts import render_code_only_prompt, render_write_report_prompt
from config import _runtime_available_for
from llm_client import chat
from log_util import logi
from modules.fix_code import apply_fix_to_solve_data, fix_code_from_error
from modules.lab_parse import complete_lab_parsed, parse_lab_json
from modules.preflight import _check_code_syntax, _check_execution_pattern
from modules.run_code import classify_run_error, execute_code, execute_multi_file
from modules.user_constraints import (
    build_constraints_prompt_block,
    has_disallowed_external_imports,
    normalize_user_constraints,
    should_skip_validation,
)

PhaseCallback = Callable[[dict[str, Any]], None]

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


def pipeline_version(settings: dict | None) -> str:
    env = (os.environ.get("SOLVE_PIPELINE") or "").strip().lower()
    if env in ("v1", "v4"):
        return env
    ver = (settings or {}).get("solvePipelineVersion") or (settings or {}).get(
        "solve_pipeline_version"
    )
    return (ver or "v4").strip().lower()


def should_use_pipeline(settings: dict | None) -> bool:
    return pipeline_version(settings) != "v1"


@dataclass
class SolveSession:
    session_id: str = ""
    pipeline_version: str = "v4"
    brief: dict = field(default_factory=dict)
    code_files: list = field(default_factory=list)
    main_file: str = ""
    language: str = "python"
    run_result: dict | None = None
    code_attempts: int = 0
    code_status: str = "pending"  # pending | verified | degraded | skipped
    steps_analysis: str = ""
    result_description: str = ""
    expected_output: str = ""
    summary: str = ""
    notes: str = ""
    diagrams: list = field(default_factory=list)
    constraints_applied: list = field(default_factory=list)
    phases: list = field(default_factory=list)
    total_llm_calls: int = 0

    def to_solve_lab_data(self, *, answer: str = "") -> dict[str, Any]:
        code_single = ""
        if self.code_files:
            for f in self.code_files:
                if f.get("name") == self.main_file or not code_single:
                    code_single = f.get("code") or f.get("content") or ""
        parsed = {
            "language": self.language,
            "steps_analysis": self.steps_analysis,
            "result_description": self.result_description,
            "expected_output": self.expected_output,
            "summary": self.summary,
            "notes": self.notes,
            "code": code_single,
            "code_files": self.code_files,
            "main_file": self.main_file,
            "diagrams": self.diagrams,
        }
        return {
            "answer": answer,
            "code": code_single,
            "code_files": self.code_files,
            "main_file": self.main_file,
            "language": self.language,
            "type": "lab_report",
            "parsed": parsed,
            "pipeline_meta": {
                "version": self.pipeline_version,
                "phases": self.phases,
                "code_status": self.code_status,
                "total_llm_calls": self.total_llm_calls,
                "constraints_applied": self.constraints_applied,
            },
            "solve_session": asdict(self),
        }


def _emit(on_phase: PhaseCallback | None, phase_id: str, status: str, detail: str = "") -> None:
    if on_phase:
        on_phase({"phase": phase_id, "status": status, "detail": detail})


def _record_phase(session: SolveSession, phase_id: str, status: str, *, llm_calls: int = 0, ms: int = 0) -> None:
    session.phases.append(
        {
            "id": phase_id,
            "status": status,
            "llm_calls": llm_calls,
            "duration_ms": ms,
        }
    )
    session.total_llm_calls += llm_calls


def _combined_code(session: SolveSession) -> str:
    return "\n\n".join(
        (f.get("code") or f.get("content") or "")
        for f in session.code_files
        if (f.get("code") or f.get("content") or "").strip()
    )


def _understand_brief(question: dict, language: str, constraints: list[str]) -> dict:
    full_text = (question.get("full_text") or question.get("content") or "").strip()
    text_lower = full_text.lower()
    needs_code = any(k in full_text or k in text_lower for k in _CODE_KEYWORDS)
    if question.get("include_code") is False:
        needs_code = False
    brief_constraints = list(constraints)
    if "no_external_jar" in constraints:
        brief_constraints.append("无外部 jar，仅 JDK 标准库")
    if "single_file" in constraints:
        brief_constraints.append("单文件源码")
    return {
        "task_summary": full_text[:400] or "实验报告",
        "language": language,
        "needs_code": needs_code,
        "needs_uml": bool(question.get("include_uml")),
        "execution_profile": "cli_script",
        "constraints": brief_constraints,
        "risks": [],
    }


def _call_llm(settings: dict, prompt: str, *, phase: str, max_tokens: int = 4000) -> str:
    result = chat(
        settings.get("api_key", ""),
        settings.get("provider", "deepseek"),
        settings.get("model", "deepseek-chat"),
        prompt,
        custom_url=settings.get("custom_url") or settings.get("customUrl") or "",
        phase=phase,
        max_tokens=max_tokens,
    )
    return (result.get("content") or "").strip()


def _solve_code(settings: dict, session: SolveSession, question: dict) -> None:
    prompt = render_code_only_prompt(
        session.brief.get("task_summary") or question.get("full_text") or "",
        language=session.language,
        constraints_block=build_constraints_prompt_block(session.constraints_applied),
        format_constraints=question.get("format_constraints") or "",
    )
    t0 = time.monotonic()
    answer = _call_llm(settings, prompt, phase="solve_code", max_tokens=4000)
    parsed = complete_lab_parsed(parse_lab_json(answer), answer)
    session.code_files = parsed.get("code_files") or []
    session.main_file = parsed.get("main_file") or ""
    session.language = parsed.get("language") or session.language
    if not session.code_files and (parsed.get("code") or "").strip():
        ext = {"python": "main.py", "java": "Main.java", "c": "main.c", "cpp": "main.cpp", "javascript": "main.js"}
        fname = session.main_file or ext.get(session.language.lower(), "main.txt")
        session.code_files = [{"name": fname, "code": parsed.get("code") or ""}]
        session.main_file = fname
    if "single_file" in session.constraints_applied and len(session.code_files) > 1:
        session.code_files = [session.code_files[0]]
        session.main_file = session.code_files[0].get("name") or session.main_file
    session.code_attempts += 1
    _record_phase(session, "solve_code", "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))


def _run_sandbox(session: SolveSession, *, skip_run: bool) -> None:
    if skip_run:
        session.code_status = "skipped"
        session.run_result = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "is_error": False,
            "skipped": True,
            "reason": "skip_validation",
        }
        _record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    combined = _combined_code(session)
    if not combined.strip():
        session.code_status = "skipped"
        session.run_result = {"stdout": "", "stderr": "", "exit_code": 0, "is_error": False, "skipped": True}
        _record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    if not _runtime_available_for(session.language):
        session.code_status = "skipped"
        session.run_result = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "is_error": False,
            "skipped": True,
            "reason": "no_runtime",
        }
        _record_phase(session, "run_code_sandbox", "skipped", llm_calls=0)
        return

    if "no_external_jar" in session.constraints_applied and has_disallowed_external_imports(
        combined, session.language
    ):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": "代码含非 JDK 第三方 import（用户约束 no_external_jar）",
            "exit_code": 1,
            "is_error": True,
            "pattern": "external_jar",
        }
        _record_phase(session, "run_code_sandbox", "failed", llm_calls=0)
        return

    t0 = time.monotonic()
    syntax = _check_code_syntax(combined, session.language)
    if not syntax.get("ok"):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": syntax.get("message") or "语法检查失败",
            "exit_code": 1,
            "is_error": True,
            "pattern": "syntax",
        }
        _record_phase(session, "preflight_code", "failed", llm_calls=0, ms=int((time.monotonic() - t0) * 1000))
        return
    _record_phase(session, "preflight_code", "ok", llm_calls=0, ms=int((time.monotonic() - t0) * 1000))

    pattern = _check_execution_pattern(combined, session.language)
    if not pattern.get("ok"):
        session.code_status = "degraded"
        session.run_result = {
            "stdout": "",
            "stderr": pattern.get("message") or "预检未通过",
            "exit_code": 1,
            "is_error": True,
            "pattern": pattern.get("pattern"),
        }
        _record_phase(session, "run_code_sandbox", "failed", llm_calls=0)
        return

    t1 = time.monotonic()
    try:
        if len(session.code_files) > 1:
            output, is_error = execute_multi_file(
                session.code_files, session.language, session.main_file
            )
        else:
            output, is_error = execute_code(combined, session.language)
    except Exception as e:
        output, is_error = str(e), True

    classified = classify_run_error(output, pattern.get("pattern") or "")
    session.run_result = {
        "stdout": output if not is_error else "",
        "stderr": output if is_error else "",
        "output": output,
        "exit_code": 1 if is_error else 0,
        "is_error": is_error,
        "error_category": classified.get("category"),
        "pattern": pattern.get("pattern"),
    }
    if is_error:
        session.code_status = "degraded"
        _record_phase(session, "run_code_sandbox", "failed", llm_calls=0, ms=int((time.monotonic() - t1) * 1000))
    else:
        session.code_status = "verified"
        _record_phase(session, "run_code_sandbox", "ok", llm_calls=0, ms=int((time.monotonic() - t1) * 1000))


def _fix_code_narrow(settings: dict, session: SolveSession, question: dict) -> bool:
    run = session.run_result or {}
    err = run.get("stderr") or run.get("output") or ""
    if not err.strip():
        return False
    solve_stub = {
        "language": session.language,
        "code_files": session.code_files,
        "main_file": session.main_file,
        "parsed": {"code_files": session.code_files, "main_file": session.main_file},
    }
    t0 = time.monotonic()
    fix = fix_code_from_error(
        settings,
        solve_stub,
        err,
        report_excerpt=(question.get("full_text") or "")[:1500],
        category=run.get("error_category") or "",
        pattern=run.get("pattern") or "",
    )
    updated = apply_fix_to_solve_data(solve_stub, fix)
    session.code_files = updated.get("code_files") or session.code_files
    session.main_file = updated.get("main_file") or session.main_file
    session.language = updated.get("language") or session.language
    session.code_attempts += 1
    _record_phase(session, "fix_code_narrow", "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))
    return True


def _write_report_text(settings: dict, session: SolveSession, question: dict) -> None:
    stdout = ""
    if session.run_result and not session.run_result.get("is_error"):
        stdout = session.run_result.get("stdout") or session.run_result.get("output") or ""
    degraded = session.code_status == "degraded"
    prompt = render_write_report_prompt(
        task_summary=session.brief.get("task_summary") or "",
        language=session.language,
        code_summary=_combined_code(session)[:2000],
        sample_stdout=stdout,
        code_status=session.code_status,
        degraded=degraded,
        format_constraints=question.get("format_constraints") or "",
    )
    t0 = time.monotonic()
    answer = _call_llm(settings, prompt, phase="write_report_text", max_tokens=4000)
    parsed = parse_lab_json(answer)
    session.steps_analysis = parsed.get("steps_analysis") or ""
    session.result_description = parsed.get("result_description") or ""
    session.summary = parsed.get("summary") or ""
    session.notes = parsed.get("notes") or ""
    session.expected_output = stdout or parsed.get("expected_output") or ""
    if degraded and "未能运行" not in session.result_description:
        session.result_description = (
            "（代码未能通过内化验证，以下为预期行为说明）\n" + session.result_description
        ).strip()
    _record_phase(session, "write_report_text", "ok", llm_calls=1, ms=int((time.monotonic() - t0) * 1000))


def run_solve_pipeline(
    settings: dict,
    question: dict,
    *,
    include_uml: bool = False,
    format_spec: dict | None = None,
    tier: str = "standard",
    user_constraints: list[str] | None = None,
    on_phase: PhaseCallback | None = None,
) -> dict[str, Any]:
    """Run V4 pipeline; returns legacy solve_lab-shaped dict + pipeline_meta."""
    del format_spec  # reserved for V4-1 format injection
    question = dict(question or {})
    if include_uml:
        question["include_uml"] = True

    constraints = normalize_user_constraints(user_constraints)
    skip_run = should_skip_validation(constraints)
    max_fix = {"fast": 1, "standard": 2, "thorough": 3}.get((tier or "standard").lower(), 2)

    language = (
        question.get("preferred_lang")
        or question.get("language")
        or (settings.get("profile") or {}).get("default_language")
        or "python"
    )

    session = SolveSession(
        session_id=f"sess_{uuid.uuid4().hex[:12]}",
        pipeline_version="v4",
        language=language,
        constraints_applied=constraints,
    )

    _emit(on_phase, "understand_brief", "running", "读题对齐")
    t0 = time.monotonic()
    session.brief = _understand_brief(question, language, constraints)
    _record_phase(session, "understand_brief", "ok", llm_calls=0, ms=int((time.monotonic() - t0) * 1000))
    _emit(on_phase, "understand_brief", "ok")

    if not session.brief.get("needs_code"):
        session.code_status = "skipped"
        _emit(on_phase, "write_report_text", "running", "纯理论题，撰写报告")
        _write_report_text(settings, session, question)
        _emit(on_phase, "write_report_text", "ok")
        data = session.to_solve_lab_data()
        logi("pipeline", f"theory-only session={session.session_id} llm={session.total_llm_calls}")
        return data

    _emit(on_phase, "solve_code", "running", "生成代码")
    _solve_code(settings, session, question)
    _emit(on_phase, "solve_code", "ok")

    fix_rounds = 0
    while True:
        _emit(on_phase, "run_code_sandbox", "running", "内化验证")
        _run_sandbox(session, skip_run=skip_run)
        if session.code_status == "verified" or skip_run:
            break
        if fix_rounds >= max_fix:
            break
        if session.code_status != "degraded":
            break
        _emit(on_phase, "fix_code_narrow", "running", "修复代码")
        if not _fix_code_narrow(settings, session, question):
            break
        fix_rounds += 1
        _emit(on_phase, "fix_code_narrow", "ok")

    _emit(on_phase, "write_report_text", "running", "撰写报告")
    _write_report_text(settings, session, question)
    _emit(on_phase, "write_report_text", "ok")

    _record_phase(session, "assemble_answer", "ok", llm_calls=0)
    data = session.to_solve_lab_data()
    logi(
        "pipeline",
        f"session={session.session_id} code_status={session.code_status} llm={session.total_llm_calls}",
    )
    return data
