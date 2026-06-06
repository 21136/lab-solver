"""Tests for ReAct post-loop finalize pipeline."""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.orchestrator import _should_render_uml
from agent.react_finalize import react_finalize_pipeline


def test_should_render_uml_when_diagrams_present():
    ctx = {
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {"parsed": {"diagrams": [{"plantuml": "@startuml\n@enduml"}]}},
            }
        }
    }
    assert _should_render_uml(ctx) is True


def test_finalize_runs_missing_steps():
    ctx = {
        "run_id": "t1",
        "output_mode": "fill_original",
        "module_results": {
            "solve_lab": {
                "ok": True,
                "data": {
                    "parsed": {
                        "diagrams": [{"plantuml": "@startuml\nclass A\n@enduml"}],
                        "steps_analysis": "步骤",
                        "result_description": "结果",
                        "summary": "总结",
                        "code": "print(1)",
                    },
                    "code": "print(1)",
                    "language": "python",
                },
            }
        },
        "document_ids": [],
        "metadata": {"report_layout": "training_table"},
        "settings": {},
    }
    steps = [
        {"module": "render_uml", "default_checked": True},
        {"module": "fill_report", "default_checked": True},
    ]

    mocks = {
        "render_uml": lambda c, p: {"ok": True, "data": {"images_b64": ["aW1n"]}},
        "fill_report": lambda c, p: {"ok": True, "data": {"output_path": "/tmp/out.docx"}},
    }
    with patch.dict("agent.executor._MODULE_RUNNERS", mocks, clear=False):
        cycles = react_finalize_pipeline("t1", ctx, steps, max_rounds=12)

    assert len(cycles) == 2
    assert all(c.get("finalize") for c in cycles)
    assert ctx["module_results"]["render_uml"]["ok"]
    assert ctx["module_results"]["fill_report"]["ok"]


if __name__ == "__main__":
    test_should_render_uml_when_diagrams_present()
    test_finalize_runs_missing_steps()
    print("test_react_finalize: OK")
