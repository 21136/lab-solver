"""V5-1 SolvePipeline skeleton + internal validation tests."""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.deliverable import build_deliverable  # noqa: E402
from modules.solve_pipeline import (  # noqa: E402
    SolveSession,
    resolve_solve_quality_tier,
    retry_pipeline_validation,
    run_solve_pipeline,
    should_use_pipeline,
    tier_limits,
)
from modules.user_constraints import (  # noqa: E402
    allows_curated_jars,
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


def test_resolve_solve_quality_tier():
    assert resolve_solve_quality_tier({"solveQualityTier": "fast"}) == "fast"
    assert resolve_solve_quality_tier({"solveQualityTier": "bogus"}) == "standard"
    assert tier_limits("fast")["force_skip_validation"] is True
    assert tier_limits("thorough")["max_fix"] == 3


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline.execute_code")
def test_fast_tier_skips_sandbox(mock_run, mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(1)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "用 Python 实现打印实验",
        "preferred_lang": "python",
    }
    result = run_solve_pipeline(settings, question, tier="fast")
    assert result["pipeline_meta"]["code_status"] == "skipped"
    assert result["pipeline_meta"]["tier"] == "fast"
    mock_run.assert_not_called()


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
@patch("modules.solve_pipeline._runtime_available_for", return_value=True)
def test_allow_curated_jars_missing_pauses_validation(mock_rt, mock_llm):
    java_code = (
        'import org.h2.Driver;\n'
        'public class Main { public static void main(String[] a) { System.out.println("ok"); } }'
    )
    mock_llm.side_effect = [
        (
            '{"code_files":[{"name":"Main.java","code":'
            + json.dumps(java_code)
            + '}],"main_file":"Main.java","language":"java"}'
        ),
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    with patch("modules.java_jars.is_jar_installed", return_value=False):
        settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
        question = {
            "type": "lab_report",
            "full_text": "Java H2 数据库实验",
            "preferred_lang": "java",
        }
        with patch("modules.solve_pipeline.execute_code") as mock_run:
            result = run_solve_pipeline(
                settings,
                question,
                user_constraints=["allow_curated_jars"],
            )
            mock_run.assert_not_called()
    assert result["pipeline_meta"]["code_status"] == "skipped"
    assert result["solve_session"]["run_result"]["reason"] == "missing_jar"


@patch("modules.solve_pipeline._fix_code_narrow", return_value=False)
@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline._runtime_available_for", return_value=True)
def test_no_external_jar_does_not_pause_for_missing_jar(mock_rt, mock_llm, _mock_fix):
    java_code = "import org.h2.Driver;\npublic class Main {}"
    mock_llm.side_effect = [
        (
            '{"code_files":[{"name":"Main.java","code":'
            + json.dumps(java_code)
            + '}],"main_file":"Main.java","language":"java"}'
        ),
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "Java 实验",
        "preferred_lang": "java",
    }
    with patch("modules.solve_pipeline.execute_code") as mock_run:
        result = run_solve_pipeline(
            settings,
            question,
            user_constraints=["no_external_jar"],
        )
        mock_run.assert_not_called()
    assert result["pipeline_meta"]["code_status"] == "degraded"
    assert result["solve_session"]["run_result"]["pattern"] == "external_jar"


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline._runtime_available_for", return_value=True)
@patch("modules.solve_pipeline.execute_code", return_value=("h2 ok\n", False))
def test_retry_validation_after_jar_download(mock_run, mock_rt, mock_llm):
    java_code = (
        'import org.h2.Driver;\n'
        'public class Main { public static void main(String[] a) { System.out.println("h2 ok"); } }'
    )
    session = SolveSession(
        language="java",
        code_files=[{"name": "Main.java", "code": java_code}],
        main_file="Main.java",
        code_status="skipped",
        constraints_applied=["allow_curated_jars"],
        brief={"task_summary": "H2", "needs_code": True},
        run_result={"reason": "missing_jar", "missing_jars": [{"id": "h2", "label": "H2"}]},
    )
    mock_llm.return_value = '{"steps_analysis":"s","result_description":"r","summary":"u"}'
    jar_path = "/fake/h2.jar"
    with patch("modules.solve_pipeline.prepare_validation_jars", return_value=([jar_path], None)):
        result = retry_pipeline_validation(
            {"api_key": "k", "provider": "deepseek", "model": "m"},
            asdict(session),
            {"full_text": "H2 实验", "preferred_lang": "java"},
            approved_jar_ids=["h2"],
        )
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs.get("java_classpath_jars") == [jar_path]
    assert result["pipeline_meta"]["code_status"] == "verified"


def test_allows_curated_jars_helper():
    assert allows_curated_jars(["allow_curated_jars"])
    assert not allows_curated_jars(["no_external_jar", "allow_curated_jars"])


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


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline.execute_code", return_value=("ok\n", False))
def test_thorough_tier_runs_solve_diagrams_phase(mock_run, mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"Main.java","code":"public class Main { public static void main(String[] a) { System.out.println(1); } }"}],"main_file":"Main.java","language":"java"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
        '{"diagrams":[{"kind":"class","title":"类图","plantuml":"@startuml\\nclass A\\n@enduml"}]}',
    ]
    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "面向对象实验 编写 Java 程序 绘制类图 UML",
        "preferred_lang": "java",
        "include_uml": True,
    }
    result = run_solve_pipeline(settings, question, include_uml=True, tier="thorough")
    phases = [p["id"] for p in result["pipeline_meta"]["phases"]]
    assert "solve_diagrams" in phases
    assert len(result["parsed"]["diagrams"]) == 1
    assert mock_llm.call_count == 3


@patch("modules.solve_pipeline._call_llm")
@patch("modules.solve_pipeline.execute_code", return_value=("ok\n", False))
def test_fast_tier_skips_solve_diagrams(mock_run, mock_llm):
    mock_llm.side_effect = [
        '{"code_files":[{"name":"main.py","code":"print(1)"}],"main_file":"main.py","language":"python"}',
        '{"steps_analysis":"s","result_description":"r","summary":"u"}',
    ]
    settings = {"api_key": "k", "provider": "deepseek", "model": "m"}
    question = {
        "type": "lab_report",
        "full_text": "Python 编程实验 绘制类图 UML 设计",
        "preferred_lang": "python",
        "include_uml": True,
    }
    result = run_solve_pipeline(settings, question, include_uml=True, tier="fast")
    phases = [p["id"] for p in result["pipeline_meta"]["phases"]]
    assert "solve_diagrams" not in phases
    assert mock_llm.call_count == 2
