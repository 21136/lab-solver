"""Tests for PlantUML render helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "python"))

from modules.uml import MAX_DIAGRAMS, VALID_DIAGRAM_KINDS, extract_diagrams
from uml_render import (
    detect_diagram_needs,
    detect_needs_uml,
    is_plantuml_error_png,
    normalize_plantuml,
    render_diagrams,
    _encode_plantuml_hex,
)


def test_is_plantuml_error_png_detects_bad_url():
    data = b"\x89PNG\r\n\x1a\n" + b"The plugin you are using seems to generated a bad URL"
    assert is_plantuml_error_png(data) is True


def test_is_plantuml_error_png_valid_header_only():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300
    assert is_plantuml_error_png(data) is False


def test_hex_encoding_prefix():
    text = normalize_plantuml("@startuml\nclass A\n@enduml")
    encoded = _encode_plantuml_hex(text)
    assert encoded.startswith("~h")
    assert "407374617274756d6c" in encoded  # @startuml in hex


def test_max_diagrams_is_12():
    assert MAX_DIAGRAMS == 12


def test_extract_diagrams_caps_at_12():
    parsed = {
        "diagrams": [
            {"kind": "class", "title": f"图{i}", "plantuml": "@startuml\n@enduml"}
            for i in range(20)
        ]
    }
    assert len(extract_diagrams(parsed)) == 12


def test_detect_diagram_needs_design_patterns():
    text = "请用 PlantUML 画出六个设计模式的类图，并补充一个时序图说明交互。"
    needs = detect_diagram_needs(text)
    assert needs["needs_uml"] is True
    assert "类图" in needs["kinds"]
    assert needs["evidence"]


def test_detect_diagram_needs_dfd_flag():
    text = "绘制图书管理系统的数据流图（DFD），包含顶层图与 0 层展开。"
    needs = detect_diagram_needs(text)
    assert needs["needs_dfd"] is True
    assert needs["needs_uml"] is True
    assert "数据流图" in needs["kinds"]


def test_detect_needs_uml_returns_dict():
    result = detect_needs_uml("画 ER 图和部署图")
    assert isinstance(result, dict)
    assert result["needs_uml"] is True
    assert "ER图" in result["kinds"] or "部署图" in result["kinds"]


def test_valid_diagram_kinds_include_phase_a_types():
    for kind in ("class", "sequence", "state", "er", "deployment", "dfd"):
        assert kind in VALID_DIAGRAM_KINDS


def test_render_diagrams_processes_seven_design_pattern_diagrams(tmp_path):
    """验收：6 类图 + 1 时序图共 7 张可一次提交渲染（上限 12）。"""
    diagrams = []
    for i, title in enumerate(
        ["简单工厂", "工厂方法", "抽象工厂", "单例", "建造者", "原型"], start=1
    ):
        diagrams.append(
            {
                "kind": "class",
                "title": f"{title}模式类图",
                "plantuml": (
                    f"@startuml\nclass {title}产品 {{\n  +操作()\n}}\n"
                    f"class {title}工厂 {{\n  +创建()\n}}\n@enduml"
                ),
            }
        )
    diagrams.append(
        {
            "kind": "sequence",
            "title": "创建产品时序图",
            "plantuml": (
                "@startuml\nactor 客户端\nparticipant 工厂\nparticipant 产品\n"
                "客户端 -> 工厂: 创建()\n工厂 --> 产品: new\n@enduml"
            ),
        }
    )
    assert len(diagrams) == 7
    assert len(extract_diagrams({"diagrams": diagrams})) == 7

    rendered = render_diagrams(diagrams, tmp_path / "uml_batch", allow_online=False)
    assert len(rendered) == 7
    ok_paths = [r for r in rendered if r.get("path")]
    if not ok_paths:
        import pytest

        pytest.skip("本地 Java/PlantUML 不可用，跳过集成渲染断言")
    assert len(ok_paths) == 7
