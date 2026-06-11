"""Phase E / R6 + E+: code_cloze answer normalize, scoring, reference blanks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.code_cloze import (  # noqa: E402
    match_cloze_answer,
    normalize_cloze_answer,
    normalize_reference_blanks,
)
from modules.deliverable import build_deliverable  # noqa: E402


def test_normalize_cloze_answer_trims_and_collapses_spaces():
    assert normalize_cloze_answer("  abstract class  ") == "abstract class"
    assert normalize_cloze_answer("  fo.read(  fileName )  ") == "fo.read( fileName )"
    assert normalize_cloze_answer("") == ""
    assert normalize_cloze_answer("   ") == ""


def test_match_cloze_answer_primary():
    assert match_cloze_answer("abstract class", "abstract class")
    assert match_cloze_answer("  abstract   class ", "abstract class")
    assert not match_cloze_answer("", "abstract class")
    assert not match_cloze_answer("abstract", "abstract class")


def test_match_cloze_answer_alt():
    primary = "fo.read(fileName)"
    alts = ["fo.read( fileName )"]
    assert match_cloze_answer("fo.read( fileName )", primary, alts)
    assert match_cloze_answer("  fo.read(  fileName )  ", primary, alts)
    assert not match_cloze_answer("fo.read(x)", primary, alts)


def test_match_cloze_answer_extended_facade_alt():
    assert match_cloze_answer(
        "new ExtendedFacade()",
        "new XMLFacade()",
        ["new ExtendedFacade()"],
    )
    assert not match_cloze_answer("new Other()", "new XMLFacade()", ["new ExtendedFacade()"])


def test_normalize_reference_blanks_dict_and_list():
    by_dict = normalize_reference_blanks(
        {
            "1": {"answer": "abstract class", "answer_alt": []},
            "2": {"answer": "fo.read(fileName)", "answer_alt": ["fo.read( fileName )"]},
        }
    )
    assert by_dict["1"]["answer"] == "abstract class"
    assert by_dict["2"]["answer_alt"] == ["fo.read( fileName )"]

    by_list = normalize_reference_blanks(
        [
            {"n": 1, "answer": "static", "answer_alt": [], "explanation": "类变量"},
        ]
    )
    assert by_list["1"]["answer"] == "static"
    assert by_list["1"]["brief"] == "类变量"


def test_build_deliverable_passes_reference_blanks():
    ctx = {
        "metadata": {
            "reference_blanks": {
                "1": {"answer": "abstract class"},
                "2": {"answer": "fo.read(fileName)", "answer_alt": ["fo.read( fileName )"]},
            }
        },
        "module_results": {
            "solve_code_cloze": {
                "ok": True,
                "data": {
                    "type": "code_cloze",
                    "parsed": {
                        "type": "code_cloze",
                        "blanks": {
                            "1": {"answer": "abstract class", "brief": ""},
                            "2": {"answer": "fo.read(fileName)", "brief": ""},
                        },
                    },
                },
            },
        },
    }
    dlv = build_deliverable(ctx)
    assert dlv["type"] == "code_cloze"
    ref = dlv["code_cloze"]["reference_blanks"]
    assert ref["2"]["answer_alt"] == ["fo.read( fileName )"]
    assert match_cloze_answer(
        dlv["code_cloze"]["blanks"]["2"]["answer"],
        ref["2"]["answer"],
        ref["2"]["answer_alt"],
    )
