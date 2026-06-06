"""Preflight checks for expanded diagram kinds."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.preflight import _check_uml, run_preflight  # noqa: E402


def _base_parsed(**extra):
    return {
        "steps_analysis": "步骤",
        "result_description": "结果",
        "summary": "总结",
        "code": "public class Main {}",
        **extra,
    }


def test_preflight_uml_valid_kinds():
    diagrams = [
        {"kind": "state", "title": "状态图", "plantuml": "@startuml\n[*] --> 待处理\n@enduml"},
        {"kind": "er", "title": "ER", "plantuml": "@startuml\nentity 学生 {}\n@enduml"},
        {"kind": "deployment", "title": "部署", "plantuml": "@startuml\nnode 服务器 {}\n@enduml"},
    ]
    result = _check_uml(diagrams)
    assert result["ok"] is True


def test_preflight_uml_invalid_kind():
    data = {
        "parsed": _base_parsed(
            diagrams=[
                {"kind": "invalid_kind", "title": "x", "plantuml": "@startuml\n@enduml"},
            ]
        ),
        "code": "public class Main {}",
        "language": "java",
    }
    pf = run_preflight(data)
    assert pf["ok"] is False
    assert "uml_schema" in pf["failed_ids"]


def test_preflight_uml_missing_startuml():
    data = {
        "parsed": _base_parsed(
            diagrams=[{"kind": "class", "title": "类图", "plantuml": "class A\n@enduml"}],
        ),
        "code": "public class Main {}",
        "language": "java",
    }
    pf = run_preflight(data)
    assert pf["ok"] is False
    assert "uml_schema" in pf["failed_ids"]


def test_preflight_dfd_invalid_flow():
    data = {
        "parsed": _base_parsed(
            diagrams=[
                {
                    "kind": "dfd",
                    "title": "坏图",
                    "dfd_json": {
                        "level": "顶层",
                        "externals": [{"id": "a", "name": "A"}],
                        "processes": [],
                        "stores": [],
                        "flows": [{"from": "a", "to": "nope", "label": "x"}],
                    },
                }
            ],
        ),
        "code": "public class Main {}",
        "language": "java",
    }
    pf = run_preflight(data)
    assert pf["ok"] is False
    assert "uml_schema" in pf["failed_ids"]
