"""Phase B — render_uml kind_stats and summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "python"))

from modules.uml import diagram_kind_stats, format_render_summary


def test_diagram_kind_stats_counts():
    diagrams = [
        {"kind": "usecase", "title": "用例图", "plantuml": "@startuml\n@enduml"},
        {"kind": "er", "title": "ER", "plantuml": "@startuml\n@enduml"},
        {"kind": "deployment", "title": "部署", "plantuml": "@startuml\n@enduml"},
    ]
    stats = diagram_kind_stats(diagrams)
    assert stats == {"usecase": 1, "er": 1, "deployment": 1}


def test_format_render_summary_with_kinds():
    data = {
        "images_b64": ["a", "b", "c"],
        "kind_stats": {"usecase": 1, "er": 1, "deployment": 1},
    }
    summary = format_render_summary(data)
    assert "共 3 张" in summary
    assert "用例图×1" in summary
    assert "ER图×1" in summary
    assert "部署图×1" in summary


def test_format_render_summary_skipped():
    assert "跳过" in format_render_summary({"skipped": True, "images_b64": []})
