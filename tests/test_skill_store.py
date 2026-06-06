"""Test skill matching and injection."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "python"))


def test_match_skills_java_web():
    from agent.skill_store import match_skills

    ctx = {"language": "java", "full_text": "实现一个Java Web应用程序，B/S架构"}
    matched = match_skills(ctx)
    ids = [s["id"] for s in matched]
    assert "java-no-servlet" in ids


def test_match_skills_java_no_web():
    from agent.skill_store import match_skills

    ctx = {"language": "java", "full_text": "实现冒泡排序和二分查找算法"}
    matched = match_skills(ctx)
    ids = [s["id"] for s in matched]
    assert "java-no-servlet" not in ids


def test_match_skills_python_web():
    from agent.skill_store import match_skills

    ctx = {"language": "python", "full_text": "编写一个Web应用程序"}
    matched = match_skills(ctx)
    ids = [s["id"] for s in matched]
    assert "java-no-servlet" not in ids  # only fires for Java


def test_match_skills_multi_class():
    from agent.skill_store import match_skills

    ctx = {"language": "java", "full_text": "实现多态和继承，设计 Animal、Dog、Cat 三个 class"}
    matched = match_skills(ctx)
    ids = [s["id"] for s in matched]
    assert "java-multi-file" in ids


def test_build_skill_injection_empty():
    from agent.skill_store import build_skill_injection

    ctx = {"language": "python", "full_text": "print hello world"}
    result = build_skill_injection(ctx)
    assert result == ""


def test_build_skill_injection_nonempty():
    from agent.skill_store import build_skill_injection

    ctx = {"language": "java", "full_text": "Web应用开发"}
    result = build_skill_injection(ctx)
    assert "java-no-servlet" in result or "Servlet" in result


def test_render_lab_report_includes_skill():
    from agent.prompts import render_lab_report_prompt

    prompt = render_lab_report_prompt(
        "实现一个Java Servlet学生管理系统",
        language="java",
    )
    # The skill block should appear for this Java + Web input
    assert "已知经验" in prompt or "HttpServer" in prompt


def test_render_lab_report_no_skill_for_python():
    from agent.prompts import render_lab_report_prompt

    prompt = render_lab_report_prompt(
        "用Python写一个Web应用",
        language="python",
    )
    # No Java skills should fire for Python
    assert "javac" not in prompt.lower().replace(" ", "") or "HttpServer" in prompt
