"""
Phase 2b B4: profile + template (no LLM).

Usage:
  python tests/test_phase2b_b4.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from agent.user_profile import (  # noqa: E402
    DEFAULT_PROFILE,
    merge_profile,
    normalize_profile,
    to_prompt_block,
)
from agent.template_analyzer import (  # noqa: E402
    align_sections,
    analyze_template_text,
    build_section_map_from_text,
    to_format_constraints,
)
from agent.prompts import render_lab_report_prompt, render_plan_prompt  # noqa: E402


SAMPLE_TEMPLATE = """
三、实验步骤
1. 编写 Java 程序；
public class Main {
  public static void main(String[] args) { }
}
四、实验结果
运行截图如图1所示，输出正确。
五、实验总结
通过本实验我掌握了基本语法。
"""


def test_normalize_profile_defaults():
    p = normalize_profile({})
    assert p["default_language"] == DEFAULT_PROFILE["default_language"]
    assert p["screenshot_style"] == "ide"


def test_merge_profile_overlay():
    p = merge_profile({"default_language": "java"}, {"default_language": "python"})
    assert p["default_language"] == "python"


def test_to_prompt_block():
    block = to_prompt_block({"default_language": "python", "prefer_uml": True})
    assert "python" in block
    assert "UML" in block or "uml" in block.lower()


def test_build_section_map():
    sm = build_section_map_from_text(SAMPLE_TEMPLATE)
    assert "steps" in sm
    assert "result" in sm
    assert sm["steps"].get("code_in_section") is True


def test_analyze_template_text():
    spec = analyze_template_text(SAMPLE_TEMPLATE, template_type="user_sample")
    assert spec["template_type"] == "user_sample"
    assert spec.get("section_map")
    assert spec.get("summary")


def test_align_sections_partial():
    spec = analyze_template_text(SAMPLE_TEMPLATE)
    aligned = align_sections(spec, {"section_map": {"steps": "三、实验步骤"}}, "")
    assert "steps" in aligned["aligned_section_map"]
    assert "result" in aligned.get("dropped_sections", [])


def test_to_format_constraints_nonempty():
    spec = analyze_template_text(SAMPLE_TEMPLATE)
    block = to_format_constraints(spec)
    assert "格式约束" in block
    assert "实验步骤" in block


def test_render_plan_includes_format_when_spec():
    spec = analyze_template_text(SAMPLE_TEMPLATE)
    p = render_plan_prompt("实验报告", {"default_language": "java"}, format_spec=spec)
    assert "格式" in p or "模版" in p or "模版" in p


def test_render_lab_prompt_backward_compat():
    p = render_lab_report_prompt("实验正文", include_uml=False)
    assert "实验正文" in p
    assert "{format_constraints}" not in p


def test_render_lab_prompt_with_constraints():
    spec = analyze_template_text(SAMPLE_TEMPLATE)
    block = to_format_constraints(spec)
    p = render_lab_report_prompt("实验正文", format_constraints=block)
    assert "格式约束" in p


if __name__ == "__main__":
    test_normalize_profile_defaults()
    test_merge_profile_overlay()
    test_to_prompt_block()
    test_build_section_map()
    test_analyze_template_text()
    test_align_sections_partial()
    test_to_format_constraints_nonempty()
    test_render_plan_includes_format_when_spec()
    test_render_lab_prompt_backward_compat()
    test_render_lab_prompt_with_constraints()
    print("test_phase2b_b4: OK")
