"""IR-23: golden table for executor_dirty revise / verify / reuse semantics."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from agent.executor_dirty import (
    apply_revise_to_module_results,
    downstream_modules_for_groups,
    groups_for_changed_fields,
    mark_dirty_from_revise,
    mark_dirty_from_verify,
    modules_to_rerun_from_verify,
    note_module_reused,
    should_rerun_module,
)


def _ctx_lab(*, verified: bool = False) -> dict[str, Any]:
    pipeline = {"code_status": "verified"} if verified else {}
    return {
        "pipeline_meta": pipeline,
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {"pipeline_meta": pipeline, "parsed": {}},
            }
        },
        "dirty_modules": [],
    }


def _ctx_cloze() -> dict[str, Any]:
    return {
        "confirmed_steps": [{"module": "solve_code_cloze", "default_checked": True}],
        "module_results": {
            "solve_code_cloze": {"ok": True, "data": {"type": "code_cloze"}},
        },
        "dirty_modules": [],
    }


@dataclass(frozen=True)
class VerifyModulesCase:
    id: str
    actions: list[str]
    ctx: dict[str, Any]
    expected: list[str]


VERIFY_MODULES_GOLDEN: tuple[VerifyModulesCase, ...] = (
    VerifyModulesCase(
        "fix_code_unverified",
        ["fix_code"],
        _ctx_lab(verified=False),
        ["fix_code", "run_code"],
    ),
    VerifyModulesCase(
        "fix_code_verified_skipped",
        ["fix_code"],
        _ctx_lab(verified=True),
        [],
    ),
    VerifyModulesCase(
        "fix_diagrams",
        ["fix_diagrams"],
        _ctx_lab(),
        ["fix_diagrams", "render_uml"],
    ),
    VerifyModulesCase(
        "render_uml_only",
        ["render_uml"],
        _ctx_lab(),
        ["render_uml"],
    ),
    VerifyModulesCase(
        "revise_full_unverified_lab",
        ["revise_full"],
        _ctx_lab(verified=False),
        ["solve_lab"],
    ),
    VerifyModulesCase(
        "revise_full_verified",
        ["revise_full"],
        _ctx_lab(verified=True),
        ["revise_answer"],
    ),
    VerifyModulesCase(
        "revise_full_code_cloze",
        ["revise_full"],
        _ctx_cloze(),
        ["solve_code_cloze"],
    ),
    VerifyModulesCase(
        "revise_section_verified",
        ["revise_section:summary"],
        _ctx_lab(verified=True),
        ["revise_answer"],
    ),
    VerifyModulesCase(
        "revise_section_unverified",
        ["revise_section:result"],
        _ctx_lab(verified=False),
        ["fill_report"],
    ),
    VerifyModulesCase(
        "verified_blocks_fix_but_keeps_revise",
        ["revise_full", "fix_code"],
        _ctx_lab(verified=True),
        ["revise_answer"],
    ),
)


@pytest.mark.parametrize("case", VERIFY_MODULES_GOLDEN, ids=lambda c: c.id)
def test_modules_to_rerun_from_verify_golden(case: VerifyModulesCase):
    got = modules_to_rerun_from_verify(case.actions, case.ctx)
    assert got == case.expected


@dataclass(frozen=True)
class MarkVerifyCase:
    id: str
    actions: list[str]
    ctx_factory: Callable[[], dict[str, Any]]
    expected_modules: list[str]
    expected_dirty_fields: dict[str, list[str]] | None = None
    fill_sections: list[str] | None | type(...) = ...


_SKIP = object()


MARK_VERIFY_GOLDEN: tuple[MarkVerifyCase, ...] = (
    MarkVerifyCase(
        "revise_full_verified_fields",
        ["revise_full"],
        lambda: _ctx_lab(verified=True),
        ["revise_answer"],
        {"solve_lab": ["steps_analysis", "result_description", "summary", "expected_output"]},
        None,
    ),
    MarkVerifyCase(
        "revise_full_cloze_unverified",
        ["revise_full"],
        _ctx_cloze,
        ["solve_code_cloze"],
        {"solve_code_cloze": ["full"]},
        None,
    ),
    MarkVerifyCase(
        "fix_code_dirty_fields",
        ["fix_code"],
        lambda: _ctx_lab(verified=False),
        ["fix_code", "run_code"],
        {"solve_lab": ["code"]},
        _SKIP,
    ),
    MarkVerifyCase(
        "fix_diagrams_fields",
        ["fix_diagrams"],
        lambda: _ctx_lab(),
        ["fix_diagrams", "render_uml"],
        {"solve_lab": ["diagrams"]},
        _SKIP,
    ),
)


@pytest.mark.parametrize("case", MARK_VERIFY_GOLDEN, ids=lambda c: c.id)
def test_mark_dirty_from_verify_golden(case: MarkVerifyCase):
    ctx = case.ctx_factory()
    modules = mark_dirty_from_verify(ctx, case.actions)
    assert modules == case.expected_modules
    assert ctx["dirty_modules"] == case.expected_modules
    if case.expected_dirty_fields is not None:
        assert ctx.get("dirty_fields") == case.expected_dirty_fields
    if case.fill_sections is not _SKIP:
        assert ctx.get("fill_sections") == case.fill_sections


@dataclass(frozen=True)
class ReviseDirtyCase:
    id: str
    changed_fields: list[str]
    scope: list[str] | str | None
    expect_modules: list[str]
    expect_fill_sections: list[str] | None


REVISE_DIRTY_GOLDEN: tuple[ReviseDirtyCase, ...] = (
    ReviseDirtyCase(
        "summary_only",
        ["summary"],
        ["summary"],
        ["fill_report"],
        ["summary"],
    ),
    ReviseDirtyCase(
        "code_group",
        ["code"],
        ["code"],
        ["fix_code", "fill_report", "run_code"],
        None,
    ),
    ReviseDirtyCase(
        "full_scope",
        [],
        "full",
        ["fill_report", "fix_code", "render_uml", "run_code"],
        None,
    ),
)


@pytest.mark.parametrize("case", REVISE_DIRTY_GOLDEN, ids=lambda c: c.id)
def test_mark_dirty_from_revise_golden(case: ReviseDirtyCase):
    ctx: dict[str, Any] = {"dirty_modules": []}
    modules = mark_dirty_from_revise(
        ctx,
        changed_fields=case.changed_fields,
        scope=case.scope,
    )
    assert sorted(modules) == sorted(case.expect_modules)
    groups = groups_for_changed_fields(case.changed_fields, case.scope)
    assert sorted(downstream_modules_for_groups(groups)) == sorted(case.expect_modules)
    if case.expect_fill_sections is not None:
        assert ctx.get("fill_sections") == case.expect_fill_sections


def test_should_rerun_and_note_reused():
    ctx = {"dirty_modules": ["fill_report"], "module_results": {"fill_report": {"ok": True}}}
    assert should_rerun_module(ctx, "fill_report") is True
    note_module_reused(ctx, "fill_report")
    assert should_rerun_module(ctx, "fill_report") is False


def test_apply_revise_preserves_ok_run_code_when_summary_changes():
    solve = {
        "type": "lab_report",
        "parsed": {
            "steps_analysis": "a",
            "result_description": "b",
            "summary": "old",
            "code": "print(1)",
            "language": "python",
        },
        "code": "print(1)",
        "language": "python",
    }
    ctx: dict[str, Any] = {
        "module_results": {
            "solve_lab": {"ok": True, "data": copy.deepcopy(solve)},
            "run_code": {"ok": True, "data": {}},
        },
        "dirty_modules": [],
    }
    solve2 = copy.deepcopy(solve)
    solve2["parsed"]["summary"] = "new summary text"
    apply_revise_to_module_results(ctx, solve2, changed_fields=["summary"])
    mark_dirty_from_revise(ctx, changed_fields=["summary"], scope=["summary"])
    assert should_rerun_module(ctx, "run_code") is False
    assert should_rerun_module(ctx, "fill_report") is True
