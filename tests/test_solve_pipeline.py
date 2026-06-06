"""V5-1 SolvePipeline skeleton + internal validation tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.deliverable import build_deliverable  # noqa: E402
from modules.solve_pipeline import (  # noqa: E402
    SolveSession,
    run_solve_pipeline,
    should_use_pipeline,
)
from modules.user_constraints import (  # noqa: E402
    has_disallowed_external_imports,
    normalize_user_constraints,
    should_skip_validation,
)


def test_normalize_user_constraints():
    assert normalize_user_constraints(["skip_validation", "no_external_jar"]) == [
        "skip_validation",
        "no_external_jar",
    ]
    assert normalize_user_constraints("skip_validation,no_external_jar") == [
        "skip_validation",
        "no_external_jar",
    ]
    assert normalize_user_constraints(["unknown"]) == []


def test_should_skip_validation():
    assert should_skip_validation(["skip_validation"])
    assert not should_skip_validation(["no_external_jar"])


def test_no_external_jar_detects_org_import():
    code = "import org.h2.Driver;\npublic class Main {}"
    assert has_disallowed_external_imports(code, "java")
    assert not has_disallowed_external_imports("import java.util.List;\n", "java")


def test_should_use_pipeline_default_v4():
    assert should_use_pipeline({})
    assert should_use_pipeline({"solvePipelineVersion": "v4"})
    assert not should_use_pipeline({"solvePipelineVersion": "v1"})


def test_solve_session_to_solve_lab_data():
    session = SolveSession(
        language="python",
        code_files=[{"name": "main.py", "code": "print(1)"}],
        main_file="main.py",
        code_status="verified",
        run_result={"stdout": "1\n", "is_error": False},
        steps_analysis="步骤",
        result_description="输出 1",
        summary="总结",
        expected_output="1\n",
    )
    data = session.to_solve_lab_data(answer="")
    assert data["parsed"]["steps_analysis"] == "步骤"
    assert data["parsed"]["expected_output"] == "1\n"
    assert data["pipeline_meta"]["code_status"] == "verified"


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline.execute_code")
def test_pipeline_verified_writes_stdout(mock_run, mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(42)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    mock_run.return_value = ("42\n", False)

    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "用 Python 实现打印 42 的实验",
        "preferred_lang": "python",
    }
    result = run_solve_pipeline(settings, question, user_constraints=[])

    assert result["pipeline_meta"]["code_status"] == "verified"
    assert result["parsed"]["expected_output"].strip() == "42"
    mock_run.assert_called_once()


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline.execute_code")
def test_skip_validation_no_subprocess(mock_run, mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(99)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]

    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "Python 打印 99 实验代码",
        "preferred_lang": "python",
    }
    result = run_solve_pipeline(settings, question, user_constraints=["skip_validation"])

    assert result["pipeline_meta"]["code_status"] == "skipped"
    assert result["solve_session"]["run_result"]["reason"] == "skip_validation"
    mock_run.assert_not_called()


@patch("modules.solve_pipeline._call_llm")
def test_deliverable_shows_validation_from_session(mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(7)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"步骤","result_description":"七","summary":"总结"}',
    ]
    with patch("modules.solve_pipeline.execute_code", return_value=("7\n", False)):
        settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
        question = {
            "type": "lab_report",
            "full_text": "Python 打印数字实验",
            "preferred_lang": "python",
        }
        solve_data = run_solve_pipeline(settings, question)

    ctx = {
        "output_mode": "deliverable",
        "user_constraints": [],
        "solve_session": solve_data["solve_session"],
        "module_results": {"solve_lab": {"ok": True, "data": solve_data}},
    }
    dlv = build_deliverable(ctx)
    assert dlv["execution"]["validation_status"] == "verified"
    assert "7" in (dlv["execution"].get("sample_stdout") or "")


@patch("modules.solve_pipeline._call_llm")
def test_deliverable_skip_validation_not_requested(mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(1)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {"type": "lab_report", "full_text": "Python 代码实验", "preferred_lang": "python"}
    with patch("modules.solve_pipeline.execute_code") as mock_run:
        solve_data = run_solve_pipeline(
            settings, question, user_constraints=["skip_validation"]
        )
        mock_run.assert_not_called()

    ctx = {
        "output_mode": "deliverable",
        "user_constraints": ["skip_validation"],
        "solve_session": solve_data["solve_session"],
        "module_results": {"solve_lab": {"ok": True, "data": solve_data}},
    }
    dlv = build_deliverable(ctx)
    assert dlv["execution"]["validation_status"] == "not_requested"
    assert "skip_validation" in dlv["constraints_applied"]
