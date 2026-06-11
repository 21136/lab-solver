"""IR-19: Per-phase contract tests for V4 solve_pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.solve_phases import (  # noqa: E402
    SolvePhaseContext,
    run_brief_phase,
    run_code_phase,
    run_diagrams_phase,
    run_fix_narrow_phase,
    run_report_phase,
    run_sandbox_phase,
)
from modules.solve_pipeline import SolveSession, tier_limits  # noqa: E402

SETTINGS = {"api_key": "k", "provider": "deepseek", "model": "m"}


def _ctx(
    question: dict,
    *,
    session: SolveSession | None = None,
    constraints: list[str] | None = None,
    skip_run: bool = False,
) -> SolvePhaseContext:
    sess = session or SolveSession(language=question.get("preferred_lang", "python"))
    return SolvePhaseContext(
        settings=SETTINGS,
        question=question,
        session=sess,
        constraints=list(constraints or []),
        limits=tier_limits("standard"),
        skip_run=skip_run,
    )


class TestBriefPhase:
    def test_theory_question_needs_no_code(self):
        question = {
            "full_text": "简述操作系统进程与线程的区别，不少于200字。",
            "include_code": False,
        }
        ctx = _ctx(question)
        result = run_brief_phase(ctx)
        assert result.phase_id == "understand_brief"
        assert result.status == "ok"
        assert ctx.session.brief.get("needs_code") is False

    def test_programming_question_needs_code(self):
        question = {"full_text": "用 Python 编写程序打印斐波那契数列前10项。"}
        ctx = _ctx(question)
        run_brief_phase(ctx)
        assert ctx.session.brief.get("needs_code") is True
        assert ctx.session.phases[-1]["id"] == "understand_brief"


class TestCodePhase:
    @patch("modules.solve_pipeline._call_llm")
    def test_populates_code_files(self, mock_llm):
        mock_llm.return_value = (
            '{"code_files":[{"name":"main.py","code":"print(1)"}],'
            '"main_file":"main.py","language":"python"}'
        )
        question = {"full_text": "Python 打印实验", "preferred_lang": "python"}
        ctx = _ctx(question)
        ctx.session.brief = {"task_summary": "Python 打印实验", "needs_code": True}
        result = run_code_phase(ctx)
        assert result.phase_id == "solve_code"
        assert result.llm_calls == 1
        assert ctx.session.code_files[0]["name"] == "main.py"
        assert ctx.session.code_attempts == 1


class TestSandboxPhase:
    @patch("modules.solve_pipeline.execute_code", return_value=("42\n", False))
    @patch("modules.solve_pipeline._check_execution_pattern", return_value={"ok": True, "pattern": "script"})
    @patch("modules.solve_pipeline._check_code_syntax", return_value={"ok": True})
    @patch("modules.solve_pipeline._runtime_available_for", return_value=True)
    def test_verified_on_success(self, _rt, _syn, _pat, _run):
        session = SolveSession(
            language="python",
            code_files=[{"name": "main.py", "code": "print(42)"}],
            main_file="main.py",
        )
        ctx = _ctx({"full_text": "x"}, session=session)
        result = run_sandbox_phase(ctx)
        assert result.status == "ok"
        assert ctx.session.code_status == "verified"
        assert "42" in (ctx.session.run_result or {}).get("stdout", "")

    def test_skip_validation_skips_subprocess(self):
        session = SolveSession(
            language="python",
            code_files=[{"name": "main.py", "code": "print(1)"}],
            main_file="main.py",
        )
        ctx = _ctx({"full_text": "x"}, session=session, skip_run=True)
        with patch("modules.solve_pipeline.execute_code") as mock_run:
            run_sandbox_phase(ctx)
            mock_run.assert_not_called()
        assert ctx.session.code_status == "skipped"
        assert ctx.session.run_result.get("reason") == "skip_validation"

    @patch("modules.solve_pipeline._runtime_available_for", return_value=True)
    @patch("modules.solve_pipeline._check_code_syntax", return_value={"ok": False, "message": "syntax err"})
    def test_degraded_on_syntax_failure(self, _syn, _rt):
        session = SolveSession(
            language="python",
            code_files=[{"name": "main.py", "code": "print(("}],
            main_file="main.py",
        )
        ctx = _ctx({"full_text": "x"}, session=session)
        run_sandbox_phase(ctx)
        assert ctx.session.code_status == "degraded"
        assert ctx.session.run_result.get("pattern") == "syntax"

    @patch("modules.solve_pipeline._runtime_available_for", return_value=True)
    def test_missing_jar_pauses_java_validation(self, _rt):
        java_code = (
            'import org.h2.Driver;\n'
            'public class Main { public static void main(String[] a) { System.out.println("ok"); } }'
        )
        session = SolveSession(
            language="java",
            code_files=[{"name": "Main.java", "code": java_code}],
            main_file="Main.java",
            constraints_applied=["allow_curated_jars"],
        )
        ctx = _ctx(
            {"full_text": "Java H2", "preferred_lang": "java"},
            session=session,
            constraints=["allow_curated_jars"],
        )
        with patch("modules.java_jars.is_jar_installed", return_value=False):
            with patch("modules.solve_pipeline.execute_code") as mock_run:
                run_sandbox_phase(ctx)
                mock_run.assert_not_called()
        assert ctx.session.code_status == "skipped"
        assert ctx.session.run_result.get("reason") == "missing_jar"


class TestFixNarrowPhase:
    def test_returns_skipped_when_no_error_text(self):
        session = SolveSession(
            language="python",
            run_result={"stderr": "", "output": ""},
        )
        ctx = _ctx({"full_text": "x"}, session=session)
        result = run_fix_narrow_phase(ctx)
        assert result.status == "skipped"
        assert result.llm_calls == 0

    @patch("modules.solve_pipeline.fix_code_from_error")
    @patch("modules.solve_pipeline.apply_fix_to_solve_data")
    def test_applies_fix_when_error_present(self, mock_apply, mock_fix):
        mock_fix.return_value = {"code_files": [{"name": "main.py", "code": "print(2)"}]}
        mock_apply.return_value = {
            "code_files": [{"name": "main.py", "code": "print(2)"}],
            "main_file": "main.py",
            "language": "python",
        }
        session = SolveSession(
            language="python",
            code_files=[{"name": "main.py", "code": "print(1)"}],
            main_file="main.py",
            run_result={"stderr": "NameError", "error_category": "name", "pattern": "script"},
        )
        ctx = _ctx({"full_text": "x"}, session=session)
        result = run_fix_narrow_phase(ctx)
        assert result.status == "ok"
        assert ctx.session.code_files[0]["code"] == "print(2)"


class TestReportPhase:
    @patch("modules.solve_pipeline._call_llm")
    def test_expected_output_from_stdout(self, mock_llm):
        mock_llm.return_value = (
            '{"steps_analysis":"步骤","result_description":"结果","summary":"总结"}'
        )
        session = SolveSession(
            language="python",
            brief={"task_summary": "实验"},
            code_status="verified",
            run_result={"stdout": "99\n", "is_error": False},
            code_files=[{"name": "main.py", "code": "print(99)"}],
            main_file="main.py",
        )
        ctx = _ctx({"full_text": "x"}, session=session)
        run_report_phase(ctx)
        assert ctx.session.expected_output.strip() == "99"
        assert ctx.session.steps_analysis == "步骤"


class TestDiagramsPhase:
    @patch("modules.solve_pipeline._call_llm")
    def test_thorough_tier_populates_diagrams(self, mock_llm):
        mock_llm.return_value = '{"diagrams":[{"kind":"uml","source":"@startuml\\nA\\n@enduml"}]}'
        session = SolveSession(
            language="python",
            brief={"needs_uml": True, "task_summary": "画类图"},
        )
        ctx = _ctx({"full_text": "设计类图实验"}, session=session)
        result = run_diagrams_phase(ctx)
        assert result.phase_id == "solve_diagrams"
        assert len(ctx.session.diagrams) == 1

    def test_skips_when_needs_uml_false(self):
        session = SolveSession(language="python", brief={"needs_uml": False})
        ctx = _ctx({"full_text": "无图"}, session=session)
        with patch("modules.solve_pipeline._call_llm") as mock_llm:
            result = run_diagrams_phase(ctx)
            mock_llm.assert_not_called()
        assert result.status == "skipped"
        assert ctx.session.diagrams == []
