"""Legacy POST /api/solve — code_cloze branch (R3 / BF52)."""
from unittest.mock import patch

import pytest

from server import app

SAMPLE_CLOZE_TEXT = """
public class MainControllerCenter {
    ( 1 ) MainControllerCenter instance;
    private ( 2 ) MainControllerCenter() {}
    public static MainControllerCenter getInstance() {
        if (instance == null) {
            instance = ( 3 ) MainControllerCenter();
        }
        return instance;
    }
}
""".strip()

LAB_REPORT_TEXT = "实验一 Java多线程程序设计\n一、实验目的\n1. 掌握线程创建"


class TestApiSolve:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = app.test_client()

    def test_missing_api_key(self):
        resp = self.client.post("/api/solve", json={
            "question": {"full_text": LAB_REPORT_TEXT},
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert "error" in data

    @patch("server.solve_lab")
    def test_lab_report_branch(self, mock_solve):
        mock_solve.return_value = {
            "answer": "完整答案...",
            "code": "public class Main {}",
            "language": "java",
            "parsed": {
                "steps_analysis": "步骤分析...",
                "code": "public class Main {}",
            },
            "tokens": 1234,
        }
        resp = self.client.post("/api/solve", json={
            "api_key": "sk-test",
            "question": {"full_text": LAB_REPORT_TEXT, "type": "lab_report"},
            "code_language": "java",
            "include_code": True,
            "include_uml": False,
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["type"] == "lab_report"
        assert data["include_code"] is True
        assert data["include_uml"] is False
        assert data["code"] == "public class Main {}"
        mock_solve.assert_called_once()

    @patch("server.call_ai")
    @patch("server.solve_lab")
    def test_code_cloze_branch(self, mock_solve, mock_call_ai):
        mock_call_ai.return_value = {
            "answer": '{"type":"code_cloze","blanks":{"1":{"answer":"static"}}}',
            "type": "code_cloze",
            "language": "java",
            "parsed": {
                "type": "code_cloze",
                "blanks": {
                    "1": {"answer": "static", "brief": "类变量"},
                    "2": {"answer": "private", "brief": "构造器私有"},
                    "3": {"answer": "new", "brief": "懒汉式实例化"},
                },
                "completed_code": "public class MainControllerCenter { ... }",
                "pattern_note": "Singleton 单例模式",
            },
        }
        resp = self.client.post("/api/solve", json={
            "api_key": "sk-test",
            "question": {"full_text": SAMPLE_CLOZE_TEXT, "type": "lab_report"},
            "code_language": "java",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["type"] == "code_cloze"
        assert data["blanks"]["1"]["answer"] == "static"
        assert data["parsed"]["blanks"]["3"]["answer"] == "new"
        assert data["pattern_note"] == "Singleton 单例模式"
        assert data["code_cloze_detected"]["is_code_cloze"] is True
        assert data["code_cloze_detected"]["blank_count"] >= 2
        assert "include_code" not in data
        mock_call_ai.assert_called_once()
        mock_solve.assert_not_called()
        call_question = mock_call_ai.call_args[0][3]
        assert call_question["type"] == "code_cloze"

    @patch("server.call_ai")
    @patch("server.solve_lab")
    def test_top_level_text_fallback(self, mock_solve, mock_call_ai):
        mock_call_ai.return_value = {
            "answer": "{}",
            "parsed": {"blanks": {"1": {"answer": "static"}}},
        }
        resp = self.client.post("/api/solve", json={
            "api_key": "sk-test",
            "text": SAMPLE_CLOZE_TEXT,
            "question": {},
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["type"] == "code_cloze"
        mock_call_ai.assert_called_once()
        mock_solve.assert_not_called()
