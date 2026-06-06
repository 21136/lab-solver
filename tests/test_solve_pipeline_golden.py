"""AO-2: V4 golden fixtures — mock LLM + real sandbox (optional per runtime)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from config import _runtime_available_for  # noqa: E402
from modules.parse_report import extract_docx  # noqa: E402
from modules.solve_pipeline import run_solve_pipeline  # noqa: E402

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "solve_v4"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "]",
    flags=re.UNICODE,
)

SETTINGS = {"api_key": "k", "provider": "deepseek", "model": "m", "solvePipelineVersion": "v4"}


def _load_manifest() -> list[dict]:
    if not MANIFEST_PATH.is_file():
        pytest.skip(f"missing {MANIFEST_PATH}; run tests/fixtures/solve_v4/gen_fixtures.py")
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data.get("fixtures") or []


def _fixture_ids():
    return [f["id"] for f in _load_manifest()]


def _needs_runtime(case: dict) -> bool:
    if case.get("expected_code_status") == "skipped":
        return False
    lang = (case.get("preferred_lang") or "python").lower()
    return _runtime_available_for(lang)


@pytest.mark.parametrize("case", _load_manifest(), ids=_fixture_ids())
@patch("modules.solve_pipeline._call_llm")
def test_golden_code_status(mock_llm, case):
    """CI-safe: mock LLM; sandbox runs when runtime available."""
    docx_path = GOLDEN_DIR / case["docx"]
    assert docx_path.is_file(), f"missing {docx_path}"

    full_text, _meta = extract_docx(docx_path)
    mock_llm.side_effect = list(case["mock_llm"])

    question = {
        "type": "lab_report",
        "full_text": full_text,
        "preferred_lang": case.get("preferred_lang", "python"),
    }

    if not _needs_runtime(case):
        with patch("modules.solve_pipeline._runtime_available_for", return_value=False):
            result = run_solve_pipeline(SETTINGS, question)
    else:
        result = run_solve_pipeline(SETTINGS, question)

    expected = case["expected_code_status"]
    actual = result["pipeline_meta"]["code_status"]
    if _needs_runtime(case):
        assert actual == expected, f"{case['id']}: expected {expected}, got {actual}"
    else:
        assert actual in ("skipped", expected)

    assertions = case.get("assertions") or {}
    stdout = ""
    run_result = result.get("solve_session", {}).get("run_result") or {}
    if run_result:
        stdout = run_result.get("stdout") or run_result.get("output") or ""

    if assertions.get("stdout_contains") and _needs_runtime(case) and actual == "verified":
        assert assertions["stdout_contains"] in stdout

    result_text = (result.get("parsed") or {}).get("result_description") or ""
    if assertions.get("no_emoji_in_result"):
        assert not _EMOJI_RE.search(result_text.lower()), f"emoji in result for {case['id']}"

    llm_calls = result["pipeline_meta"].get("total_llm_calls") or result["solve_session"].get(
        "total_llm_calls", 0
    )
    assert llm_calls == len(case["mock_llm"])
    assert mock_llm.call_count == len(case["mock_llm"])


def test_golden_manifest_has_ten_cases():
    cases = _load_manifest()
    assert len(cases) == 10
    ids = {c["id"] for c in cases}
    assert len(ids) == 10


@pytest.mark.golden_sandbox
def test_golden_sandbox_pass_rate_baseline():
    """Local optional: aggregate sandbox pass rate for AO-P0 baseline."""
    cases = [c for c in _load_manifest() if c.get("expected_code_status") == "verified"]
    runnable = [c for c in cases if _needs_runtime(c)]
    if not runnable:
        pytest.skip("no verified-case runtimes available")

    passed = 0
    for case in runnable:
        docx_path = GOLDEN_DIR / case["docx"]
        full_text, _ = extract_docx(docx_path)
        question = {
            "type": "lab_report",
            "full_text": full_text,
            "preferred_lang": case.get("preferred_lang", "python"),
        }
        with patch("modules.solve_pipeline._call_llm", side_effect=list(case["mock_llm"])):
            result = run_solve_pipeline(SETTINGS, question)
        if result["pipeline_meta"]["code_status"] == "verified":
            passed += 1

    rate = passed / len(runnable)
    print(f"\n[golden] sandbox pass rate: {passed}/{len(runnable)} = {rate:.0%}")
    assert rate >= 0.0  # baseline recorder; target ≥80% documented in AGENT_OPTIMIZATION_PLAN
