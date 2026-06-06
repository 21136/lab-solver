"""Tests for standard DFD layout and portable Graphviz rendering."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from dfd_layout import dfd_to_dot, extract_dfd_json, validate_dfd  # noqa: E402
from dfd_render import DOT_MISSING_MSG, _find_dot, probe_graphviz, render_dfd_png  # noqa: E402
from modules.preflight import _check_uml, run_preflight  # noqa: E402
from uml_render import render_diagrams  # noqa: E402


SAMPLE_TOP = {
    "level": "顶层",
    "externals": [{"id": "reader", "name": "读者"}],
    "processes": [{"id": "p0", "name": "0 图书管理系统"}],
    "stores": [],
    "flows": [
        {"from": "reader", "to": "p0", "label": "借还请求"},
        {"from": "p0", "to": "reader", "label": "借阅结果"},
    ],
}

SAMPLE_L0 = {
    "level": "0层",
    "externals": [{"id": "reader", "name": "读者"}],
    "processes": [
        {"id": "p1", "name": "1.0 借还处理"},
        {"id": "p2", "name": "2.0 查询处理"},
    ],
    "stores": [{"id": "d1", "name": "D1 图书信息"}],
    "flows": [
        {"from": "reader", "to": "p1", "label": "借还请求"},
        {"from": "p1", "to": "d1", "label": "更新库存"},
        {"from": "d1", "to": "p2", "label": "检索"},
        {"from": "p2", "to": "reader", "label": "查询结果"},
    ],
}


def test_extract_dfd_json_from_source_string():
    diagram = {
        "kind": "dfd",
        "title": "顶层",
        "source": json.dumps(SAMPLE_TOP, ensure_ascii=False),
    }
    data = extract_dfd_json(diagram)
    assert data["level"] == "顶层"
    assert len(data["externals"]) == 1


def test_validate_dfd_ok():
    assert validate_dfd(SAMPLE_TOP) == []
    assert validate_dfd(SAMPLE_L0) == []


def test_validate_dfd_invalid_flow_endpoint():
    bad = dict(SAMPLE_TOP)
    bad["flows"] = [{"from": "reader", "to": "missing", "label": "x"}]
    errors = validate_dfd(bad)
    assert any("不存在" in e for e in errors)


def test_validate_dfd_external_to_external():
    bad = {
        "level": "顶层",
        "externals": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "processes": [],
        "stores": [],
        "flows": [{"from": "a", "to": "b", "label": "直连"}],
    }
    errors = validate_dfd(bad)
    assert any("外部实体" in e for e in errors)


def test_dfd_to_dot_shapes():
    dot = dfd_to_dot(SAMPLE_L0, title="0 层图")
    assert "shape=box" in dot
    assert "shape=circle" in dot
    assert "shape=record" in dot
    assert "借还请求" in dot


def test_preflight_dfd_valid():
    diagrams = [
        {"kind": "dfd", "title": "顶层", "dfd_json": SAMPLE_TOP},
        {"kind": "dfd", "title": "0层", "dfd_json": SAMPLE_L0},
    ]
    result = _check_uml(diagrams)
    assert result["ok"] is True


def test_preflight_dfd_missing_json():
    pf = run_preflight(
        {
            "parsed": {
                "steps_analysis": "s",
                "result_description": "r",
                "summary": "u",
                "code": "public class Main {}",
                "diagrams": [{"kind": "dfd", "title": "空"}],
            },
            "code": "public class Main {}",
            "language": "java",
        }
    )
    assert pf["ok"] is False
    assert "uml_schema" in pf["failed_ids"]


def test_probe_missing_portable_message():
    with patch("dfd_render._portable_dot_path", return_value=None):
        info = probe_graphviz(portable_only=True)
    assert info["ok"] is False
    assert "assets/graphviz" in info["message"] or "assets\\graphviz" in info.get("assets_dir", "")


def test_find_dot_missing_when_no_portable_and_no_path(monkeypatch):
    monkeypatch.setattr("dfd_render._portable_dot_path", lambda: None)
    monkeypatch.setattr("dfd_render.shutil.which", lambda _name: None)
    assert _find_dot() is None


def test_render_dfd_missing_graphviz_error(tmp_path):
    diagram = {"kind": "dfd", "title": "顶层", "dfd_json": SAMPLE_TOP}
    with patch("dfd_render._find_dot", return_value=None):
        with pytest.raises(RuntimeError) as exc:
            render_dfd_png(diagram, tmp_path / "x.png")
    msg = str(exc.value)
    assert "assets/graphviz" in msg
    assert "graphviz.org" not in msg.lower()


def test_render_dfd_png_portable(tmp_path):
    gv = probe_graphviz(portable_only=True)
    if not gv.get("ok"):
        pytest.skip("便携 Graphviz 未安装，跳过集成渲染")

    out = tmp_path / "dfd.png"
    render_dfd_png({"kind": "dfd", "title": "顶层", "dfd_json": SAMPLE_TOP}, out)
    assert out.is_file()
    assert out.stat().st_size > 100
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_diagrams_routes_dfd(tmp_path):
    gv = probe_graphviz(portable_only=True)
    if not gv.get("ok"):
        pytest.skip("便携 Graphviz 未安装，跳过集成渲染")

    diagrams = [{"kind": "dfd", "title": "顶层", "dfd_json": SAMPLE_TOP}]
    rendered = render_diagrams(diagrams, tmp_path / "dfd_out", allow_online=False)
    assert len(rendered) == 1
    assert rendered[0].get("path")
    assert Path(rendered[0]["path"]).stat().st_size > 100


def test_config_diagram_tools_status():
    from config import get_diagram_tools_status

    status = get_diagram_tools_status()
    assert "graphviz_ok" in status
    assert "plantuml_jar_ok" in status
    assert "java_ok" in status
