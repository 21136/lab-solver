"""Toolbox mode backend tests — 9 /api/tool/* routes + helpers."""
import base64
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock, patch

import pytest
from docx import Document

from server import app, _tool_ok, _tool_err, _tool_settings


def _make_minimal_docx(text="实验报告内容"):
    """Create a minimal .docx file for testing, returns Path."""
    doc = Document()
    doc.add_paragraph(text)
    tmp = NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(tmp.name)
    return Path(tmp.name)


# ── Helpers ──


class TestToolHelpers:
    def test_tool_ok_returns_correct_shape(self):
        with app.app_context():
            resp = _tool_ok({"key": "val"})
            data = resp.get_json()
        assert data["ok"] is True
        assert data["data"] == {"key": "val"}

    def test_tool_err_returns_correct_shape(self):
        with app.app_context():
            resp, status = _tool_err("something broke", 422)
            data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "something broke"
        assert status == 422

    def test_tool_err_default_status(self):
        with app.app_context():
            resp, status = _tool_err("bad request")
            assert status == 400
            data = resp.get_json()
        assert data["ok"] is False

    def test_tool_settings_extracts_all_fields(self):
        result = _tool_settings({
            "api_key": "sk-abc",
            "provider": "openai",
            "model": "gpt-4",
            "custom_url": "https://api.example.com",
        })
        assert result["api_key"] == "sk-abc"
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4"
        assert result["custom_url"] == "https://api.example.com"

    def test_tool_settings_camelcase_fallback(self):
        result = _tool_settings({
            "api_key": "sk-xyz",
            "customUrl": "https://custom.example.com",
        })
        assert result["custom_url"] == "https://custom.example.com"

    def test_tool_settings_defaults(self):
        result = _tool_settings({})
        assert result["api_key"] == ""
        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-v4-flash"
        assert result["custom_url"] == ""


# ── 1. Parse ──


class TestToolParse:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()
        self.cleanup_paths = []

    def teardown_method(self):
        for p in self.cleanup_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def _make_b64_docx(self, text="实验一 Java多线程程序设计"):
        path = _make_minimal_docx(text)
        self.cleanup_paths.append(path)
        data = path.read_bytes()
        return base64.b64encode(data).decode()

    def test_missing_file_data(self):
        resp = self.client.post("/api/tool/parse", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "file_data" in data["error"]

    def test_invalid_base64(self):
        resp = self.client.post("/api/tool/parse", json={
            "file_data": "!!!not-base64!!!",
            "file_name": "test.docx",
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    def test_legacy_doc_warns_not_rejected(self):
        """Legacy .doc is no longer rejected — it goes through conversion.
        If conversion fails, the warning is returned alongside the result."""
        with patch("server.build_question_from_document") as mock_build:
            mock_build.return_value = (
                {"id": 0, "type": "lab_report", "title": "old", "full_text": "",
                 "metadata": {}, "placeholder": "", "image_assets": [], "image_bundle_meta": {}},
                {},
                "",
                [{"code": "legacy_doc", "message": "旧版 .doc 无法转换，请安装 LibreOffice"}],
            )
            resp = self.client.post("/api/tool/parse", json={
                "file_data": base64.b64encode(b"fake").decode(),
                "file_name": "old.doc",
            })
        data = resp.get_json()
        assert data["ok"] is True
        inner = data.get("data") or {}
        assert any(w.get("code") == "legacy_doc" for w in (inner.get("warnings") or []))

    def test_successful_parse(self):
        b64 = self._make_b64_docx("实验一 Java多线程程序设计\n一、实验目的\n1. 掌握线程创建")
        with patch("server.detect_docx_sections") as mock_detect, \
             patch("server.build_question_from_document") as mock_build:
            mock_detect.return_value = {
                "sections_detected": [
                    {"heading": "一、实验目的", "semantic": "objective", "index": 0},
                    {"heading": "三、实验步骤", "semantic": "steps", "index": 1},
                ],
                "section_map": {"steps": {"heading": "三、实验步骤"}},
            }
            mock_build.return_value = (
                {"type": "lab_report", "full_text": "实验一..."},
                {"course": "Java程序设计"},
                "实验一 Java多线程程序设计",
                [],
            )

            resp = self.client.post("/api/tool/parse", json={
                "file_data": b64,
                "file_name": "report.docx",
            })
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["ok"] is True
            assert "full_text" in data["data"]
            assert "sections" in data["data"]
            assert "section_map" in data["data"]
            assert "metadata" in data["data"]
            assert data["data"]["char_count"] > 0


# ── 2. Solve ──


class TestToolSolve:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_text(self):
        resp = self.client.post("/api/tool/solve", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    def test_missing_api_key(self):
        resp = self.client.post("/api/tool/solve", json={
            "text": "实验一 Java多线程",
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "Key" in data["error"]

    @patch("server.solve_lab")
    def test_successful_solve(self, mock_solve):
        mock_solve.return_value = {
            "answer": "完整答案...",
            "code": "public class Main {}",
            "language": "java",
            "parsed": {
                "steps_analysis": "步骤分析...",
                "result_description": "结果描述...",
                "summary": "总结...",
                "code": "public class Main {}",
                "diagrams": [{"title": "类图", "plantuml": "@startuml\n@enduml"}],
            },
            "tokens": 1234,
        }
        resp = self.client.post("/api/tool/solve", json={
            "api_key": "sk-test",
            "text": "实验一 Java多线程",
            "language": "java",
            "include_uml": True,
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["code"] == "public class Main {}"
        assert data["data"]["language"] == "java"
        assert len(data["data"]["diagrams"]) == 1
        assert data["data"]["tokens"] == 1234

    @patch("server.solve_lab", side_effect=RuntimeError("LLM timeout"))
    def test_solve_handles_exception(self, _mock_solve):
        resp = self.client.post("/api/tool/solve", json={
            "api_key": "sk-test",
            "text": "实验一",
        })
        data = resp.get_json()
        assert resp.status_code == 500
        assert data["ok"] is False
        assert "LLM timeout" in data["error"]


# ── 3. Run ──


class TestToolRun:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_code(self):
        resp = self.client.post("/api/tool/run", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    @patch("modules.preflight._check_execution_pattern")
    def test_blocked_by_preflight(self, mock_check):
        mock_check.return_value = {"ok": False, "message": "禁止执行危险操作", "pattern": "dangerous"}
        resp = self.client.post("/api/tool/run", json={
            "code": "import os; os.system('rm -rf /')",
            "language": "python",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["blocked_by_preflight"] is True
        assert "危险" in data["data"]["stdout"]

    @patch("modules.preflight._check_execution_pattern")
    @patch("server.execute_code")
    def test_successful_run(self, mock_exec, mock_check):
        mock_check.return_value = {"ok": True}
        mock_exec.return_value = ("Hello World\n", False)
        resp = self.client.post("/api/tool/run", json={
            "code": "print('Hello World')",
            "language": "python",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["stdout"] == "Hello World\n"
        assert data["data"]["exit_code"] == 0

    @patch("modules.preflight._check_execution_pattern")
    @patch("server.execute_code")
    def test_run_with_error(self, mock_exec, mock_check):
        mock_check.return_value = {"ok": True}
        mock_exec.return_value = ("NameError: name 'x' is not defined\n", True)
        resp = self.client.post("/api/tool/run", json={
            "code": "print(x)",
            "language": "python",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["exit_code"] == 1
        assert data["data"]["is_error"] is True


# ── 4. UML ──


class TestToolUml:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    @patch("server.UML_RENDER_OK", False)
    def test_uml_not_available(self):
        resp = self.client.post("/api/tool/uml", json={
            "plantuml_src": "@startuml\nA -> B\n@enduml",
        })
        data = resp.get_json()
        assert resp.status_code == 500
        assert data["ok"] is False

    def test_missing_plantuml(self):
        resp = self.client.post("/api/tool/uml", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "diagrams" in data["error"] or "plantuml" in data["error"]

    @patch("server.render_uml_diagrams")
    def test_successful_uml(self, mock_render):
        mock_render.return_value = {
            "images_b64": ["uml_base64_string"],
            "errors": [],
        }
        resp = self.client.post("/api/tool/uml", json={
            "plantuml_src": "@startuml\nClassA -> ClassB\n@enduml",
            "title": "类图",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["image_b64"] == "uml_base64_string"
        assert data["data"]["images_b64"] == ["uml_base64_string"]

    @patch("server.render_uml_diagrams")
    def test_uml_with_errors(self, mock_render):
        mock_render.return_value = {
            "images_b64": [],
            "errors": ["Syntax error in PlantUML"],
        }
        resp = self.client.post("/api/tool/uml", json={
            "plantuml_src": "@startuml\nbad syntax\n@enduml",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["errors"] == ["Syntax error in PlantUML"]

    @patch("server.render_uml_diagrams")
    def test_uml_diagrams_array_with_dfd(self, mock_render):
        mock_render.return_value = {
            "images_b64": ["dfd_b64"],
            "titles": ["顶层图"],
            "kind_stats": {"dfd": 1},
            "summary": "UML 渲染完成，共 1 张（DFD×1）",
            "errors": [],
        }
        diagrams = [{
            "kind": "dfd",
            "title": "顶层图",
            "dfd_json": {
                "level": "顶层",
                "externals": [{"id": "user", "name": "用户"}],
                "processes": [{"id": "p0", "name": "0 系统"}],
                "stores": [],
                "flows": [
                    {"from": "user", "to": "p0", "label": "请求"},
                    {"from": "p0", "to": "user", "label": "响应"},
                ],
            },
        }]
        resp = self.client.post("/api/tool/uml", json={"diagrams": diagrams})
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["kind_stats"] == {"dfd": 1}
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0][0]["kind"] == "dfd"


# ── 6. Fill ──


class TestToolFill:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()
        self.cleanup_paths = []

    def teardown_method(self):
        for p in self.cleanup_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def _make_b64_docx(self):
        path = _make_minimal_docx("实验报告内容 实验步骤...")
        self.cleanup_paths.append(path)
        return base64.b64encode(path.read_bytes()).decode()

    def test_missing_answer_json(self):
        resp = self.client.post("/api/tool/fill", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    @patch("server.do_fill")
    @patch("server.document_format", return_value="docx")
    def test_dict_answer_normalized_to_list(self, _mock_fmt, mock_fill):
        tmp_docx = _make_minimal_docx("filled content")
        self.cleanup_paths.append(tmp_docx)
        mock_fill.return_value = str(tmp_docx)
        b64 = self._make_b64_docx()
        resp = self.client.post("/api/tool/fill", json={
            "answer_json": {"steps_analysis": "test", "code": "x=1"},
            "file_data": b64,
            "file_name": "report.docx",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        # Verify do_fill was called with a list (dict wrapped)
        call_args = mock_fill.call_args[0]
        answers_arg = call_args[1]
        assert isinstance(answers_arg, list)
        assert answers_arg[0]["steps_analysis"] == "test"

    @patch("server.do_fill")
    @patch("server.document_format", return_value="docx")
    def test_fill_without_file_data(self, _mock_fmt, mock_fill):
        tmp_docx = _make_minimal_docx("filled")
        self.cleanup_paths.append(tmp_docx)
        mock_fill.return_value = str(tmp_docx)
        resp = self.client.post("/api/tool/fill", json={
            "answer_json": [{"steps_analysis": "test"}],
            "file_name": "report.docx",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["output_path"]


# ── 7. Fix ──


class TestToolFix:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_code(self):
        resp = self.client.post("/api/tool/fix", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    def test_missing_api_key(self):
        resp = self.client.post("/api/tool/fix", json={
            "code": "pritn('hello')",
            "error_output": "NameError: name 'pritn' is not defined",
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "Key" in data["error"]

    @patch("server.fix_code_from_error")
    def test_successful_fix(self, mock_fix):
        mock_fix.return_value = {
            "code": "print('hello')",
            "code_files": [{"name": "main.py", "code": "print('hello')"}],
            "main_file": "main.py",
            "language": "python",
            "parsed": {"code": "print('hello')"},
            "category": "syntax",
        }
        resp = self.client.post("/api/tool/fix", json={
            "api_key": "sk-test",
            "code": "pritn('hello')",
            "language": "python",
            "error_output": "NameError",
            "report_excerpt": "实验一",
            "category": "syntax",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["code"] == "print('hello')"
        assert data["data"]["category"] == "syntax"


# ── 8. Verify ──


class TestToolVerify:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_answer_json(self):
        resp = self.client.post("/api/tool/verify", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    @patch("server.verify_answer")
    def test_successful_verify_passed(self, mock_verify):
        mock_verify.return_value = {
            "passed": True,
            "checks": [
                {"id": "schema_complete", "label": "结构完整", "passed": True},
                {"id": "no_placeholder", "label": "无占位符", "passed": True},
            ],
            "suggested_actions": [],
        }
        resp = self.client.post("/api/tool/verify", json={
            "answer_json": {"steps_analysis": "...", "code": "x=1"},
            "answer_template_text": "",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["passed"] is True
        assert len(data["data"]["checks"]) == 2

    @patch("server.verify_answer")
    def test_successful_verify_failed(self, mock_verify):
        mock_verify.return_value = {
            "passed": False,
            "checks": [
                {"id": "fill_ready", "label": "可填表", "passed": False, "detail": "缺少 summary"},
            ],
            "suggested_actions": ["revise_full"],
        }
        resp = self.client.post("/api/tool/verify", json={
            "answer_json": {"steps_analysis": "..."},
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["passed"] is False
        assert "revise_full" in data["data"]["suggested_actions"]


# ── 9. Revise ──


class TestToolRevise:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_answer_json(self):
        resp = self.client.post("/api/tool/revise", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False

    def test_missing_feedback(self):
        resp = self.client.post("/api/tool/revise", json={
            "answer_json": {"steps_analysis": "...", "code": "x=1"},
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "反馈" in data["error"] or "feedback" in data.get("error", "")

    @patch("server.revise_answer")
    def test_successful_revise(self, mock_revise):
        mock_revise.return_value = {
            "parsed": {
                "steps_analysis": "改进后的步骤...",
                "code": "print('fixed')",
            },
            "changed_fields": ["steps_analysis", "code"],
        }
        resp = self.client.post("/api/tool/revise", json={
            "api_key": "sk-test",
            "answer_json": {"steps_analysis": "原始步骤", "code": "x=1"},
            "feedback": "代码太简单，需要增加错误处理",
            "scope": ["code", "steps_analysis"],
            "report_excerpt": "实验一",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["data"]["parsed"]["steps_analysis"] == "改进后的步骤..."
        assert data["data"]["changed_fields"] == ["steps_analysis", "code"]

    @patch("server.revise_answer")
    def test_missing_api_key(self, mock_revise):
        resp = self.client.post("/api/tool/revise", json={
            "answer_json": {"code": "x=1"},
            "feedback": "改进",
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert data["ok"] is False
        assert "Key" in data["error"]
