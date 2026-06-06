"""
Golden regression for Phase 1.2 — parse fixtures without LLM; solve path counts LLM calls.

Usage (from repo root):
  python tests/run_golden_regression.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SRC = ROOT / "src" / "python"
sys.path.insert(0, str(PYTHON_SRC))

from llm_client import get_llm_call_count, reset_llm_call_count  # noqa: E402
from modules.parse_report import build_question_from_docx  # noqa: E402
from modules.run_code import execute_code  # noqa: E402
from modules.solve_lab import solve_lab  # noqa: E402

FIXTURES = [
    ("programming_lab.docx", "Java"),
    ("theory_lab.docx", "TCP"),
    ("combined_lab.docx", "需求"),
]


def ensure_fixtures():
    import subprocess

    fixtures_dir = Path(__file__).parent / "fixtures"
    missing = [name for name, _ in FIXTURES if not (fixtures_dir / name).exists()]
    if missing:
        gen_script = Path(__file__).parent / "generate_fixtures.py"
        subprocess.run([sys.executable, str(gen_script)], check=True, cwd=str(ROOT))
    return fixtures_dir


def test_parse_fixtures(fixtures_dir: Path):
    reset_llm_call_count()
    for name, keyword in FIXTURES:
        path = fixtures_dir / name
        question, metadata, full_text, warnings = build_question_from_docx(path, name)
        assert question["type"] == "lab_report", name
        assert len(full_text) > 100, f"{name}: body too short"
        assert keyword in full_text or keyword in str(metadata), f"{name}: missing {keyword}"
        assert isinstance(warnings, list), name
    assert get_llm_call_count() == 0, "parse must not call LLM"
    print(f"parse: OK ({len(FIXTURES)} fixtures, llm_calls=0)")


def test_run_code_smoke():
    reset_llm_call_count()
    out, err = execute_code('print("golden_ok")', "python")
    assert not err, out
    assert "golden_ok" in out
    assert get_llm_call_count() == 0
    print("run_code: OK (llm_calls=0)")


def test_solve_llm_count():
    fixtures_dir = ensure_fixtures()
    path = fixtures_dir / "programming_lab.docx"
    question, _, _, _ = build_question_from_docx(path, path.name)

    reset_llm_call_count()
    fake = {
        "answer": '{"sections":[]}',
        "code": 'public class Main { public static void main(String[] a) {} }',
        "type": "lab_report",
        "parsed": {},
        "language": "java",
    }

    def fake_call_ai(*_args, **_kwargs):
        import llm_client as lc

        lc._llm_call_count += 1
        return fake

    reset_llm_call_count()
    with patch("llm_client.call_ai", side_effect=fake_call_ai):
        result = solve_lab("fake-key", "deepseek", "deepseek-chat", question)
        assert result["language"] == "java"

    assert get_llm_call_count() == 1, "solve_lab should invoke LLM exactly once"
    print("solve_lab: OK (llm_calls=1 with mock)")


def main():
    fixtures_dir = ensure_fixtures()
    test_parse_fixtures(fixtures_dir)
    test_run_code_smoke()
    test_solve_llm_count()
    print("\nAll golden regression checks passed.")


if __name__ == "__main__":
    main()
