"""Diagram verify and fix loop tests."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.executor_dirty import modules_to_rerun_from_verify  # noqa: E402
from modules.diagram_verify import verify_diagrams  # noqa: E402


SAMPLE_DFD = {
    "kind": "dfd",
    "title": "顶层",
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
}

BAD_DFD = {
    "kind": "dfd",
    "title": "坏图",
    "dfd_json": {
        "level": "顶层",
        "externals": [{"id": "user", "name": "用户"}],
        "processes": [],
        "stores": [],
        "flows": [{"from": "user", "to": "missing", "label": "x"}],
    },
}


def test_verify_diagrams_schema_fail_suggests_fix():
    report = verify_diagrams({"parsed": {"diagrams": [BAD_DFD]}})
    assert report["ok"] is False
    assert "fix_diagrams" in report["suggested_actions"]
    assert any(i["type"] == "schema" for i in report["issues"])


def test_verify_diagrams_render_partial():
    report = verify_diagrams(
        {"parsed": {"diagrams": [SAMPLE_DFD, BAD_DFD]}},
        render_result={
            "images_b64": ["abc"],
            "errors": ["坏图: DFD 校验失败"],
        },
    )
    assert report["ok"] is False
    assert "fix_diagrams" in report["suggested_actions"]
    assert "render_uml" in report["suggested_actions"]


def test_verify_infra_error_suggests_render_only():
    report = verify_diagrams(
        {"parsed": {"diagrams": [SAMPLE_DFD]}},
        render_result={
            "images_b64": [],
            "errors": ["未找到便携 Graphviz，请检查 assets/graphviz 是否完整"],
        },
    )
    assert report["ok"] is False
    assert report["suggested_actions"] == ["render_uml"]


def test_modules_to_rerun_maps_fix_diagrams():
    mods = modules_to_rerun_from_verify(["fix_diagrams", "render_uml"])
    assert mods == ["fix_diagrams", "render_uml"]


def test_render_uml_fails_when_validation_fails():
    from modules.uml import render_uml_diagrams

    with patch("modules.uml.render_diagrams") as mock_render:
        mock_render.return_value = [
            {"title": "坏图", "kind": "dfd", "error": "DFD 校验失败: flow"},
        ]
        out = render_uml_diagrams([BAD_DFD], allow_online=False)
    assert out["success"] is False
    assert out["validation"]["ok"] is False
    assert "fix_diagrams" in out["suggested_actions"]
