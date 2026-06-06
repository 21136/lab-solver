"""Registry consistency tests (V3-1)."""

from agent.planner import _THIN_PLANNER_MODULES
from agent.react_tools import REACT_TOOL_SCHEMAS, tool_to_module
from agent.registry import (
    MODULE_REGISTRY,
    get_runner,
    known_module_ids,
    planner_module_catalog,
    react_action_to_module,
    react_tool_schemas,
)
from agent.types import KNOWN_MODULE_IDS
from agent.executor import _MODULE_RUNNERS


def test_known_module_ids_matches_registry():
    assert known_module_ids() == frozenset(MODULE_REGISTRY.keys())
    assert KNOWN_MODULE_IDS == known_module_ids()


def test_planner_catalog_matches_legacy_set():
    expected = frozenset(
        {
            "solve_lab",
            "solve_theory",
            "run_code",
            "screenshot_ide",
            "screenshot_terminal",
            "render_uml",
            "present_deliverable",
        }
    )
    assert "fill_report" not in planner_module_catalog()
    assert planner_module_catalog() == expected
    assert _THIN_PLANNER_MODULES == planner_module_catalog()


def test_react_tool_schemas_match_legacy():
    schemas = react_tool_schemas()
    assert schemas == REACT_TOOL_SCHEMAS
    assert set(schemas) == {
        "solve_lab",
        "fix_code",
        "fix_diagrams",
        "run_code",
        "screenshot",
        "fill_report",
        "render_uml",
        "finalize_report",
    }


def test_react_action_to_module_aliases():
    assert react_action_to_module("solve_lab") == "solve_lab"
    assert react_action_to_module("screenshot") == "screenshot_ide"
    assert react_action_to_module("finalize_report") == "finalize_report"
    assert react_action_to_module("unknown") == ""
    assert tool_to_module("RUN_CODE") == "run_code"


def test_executor_runners_registered():
    """Every executor runner has a registry entry with runner='executor'."""
    for module_id in _MODULE_RUNNERS:
        spec = MODULE_REGISTRY[module_id]
        assert spec.runner == "executor"
        assert get_runner(module_id) is _MODULE_RUNNERS[module_id]


def test_react_schema_modules_in_registry():
    for schema in REACT_TOOL_SCHEMAS.values():
        module_id = schema["module"]
        assert module_id in MODULE_REGISTRY
