"""
Rule-based verify_answer + plagiarism check (Phase 2b B3, zero LLM).
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Optional

from modules.diagram_verify import verify_diagrams
from modules.uml import extract_diagrams

_PLACEHOLDER_PATTERNS = [
    r"待填写",
    r"TODO",
    r"TBD",
    r"\.{3,}",
    r"（略）",
    r"此处填写",
]

_MIN_PLAGIARISM_CHUNK = 30
_PLAGIARISM_RATIO_THRESHOLD = 0.3


def extract_numbers(text: str) -> list[float]:
    """Pull numeric literals from text for output consistency checks."""
    if not text:
        return []
    found: list[float] = []
    for m in re.finditer(r"-?\d+(?:\.\d+)?", text):
        try:
            found.append(float(m.group(0)))
        except ValueError:
            continue
    return found


def check_plagiarism(
    generated: str,
    template_text: str,
    *,
    min_chunk: int = _MIN_PLAGIARISM_CHUNK,
    ratio_threshold: float = _PLAGIARISM_RATIO_THRESHOLD,
) -> dict[str, Any]:
    """
    difflib longest-match ratio vs template; warn if >= threshold.
    """
    gen = (generated or "").strip()
    tpl = (template_text or "").strip()
    if not gen or not tpl or len(gen) < min_chunk:
        return {"ok": True, "ratio": 0.0, "message": ""}

    matcher = difflib.SequenceMatcher(None, gen, tpl, autojunk=False)
    match_len = sum(triple[-1] for triple in matcher.get_matching_blocks())
    ratio = match_len / max(len(gen), 1)
    ok = ratio < ratio_threshold
    msg = ""
    if not ok:
        msg = f"与范文连续相似片段占比约 {ratio:.0%}（阈值 {ratio_threshold:.0%}）"
    return {"ok": ok, "ratio": round(ratio, 4), "message": msg}


def _parsed_text_blob(parsed: dict) -> str:
    parts = [
        parsed.get("steps_analysis") or "",
        parsed.get("result_description") or "",
        parsed.get("summary") or "",
        parsed.get("code") or "",
        parsed.get("expected_output") or "",
    ]
    return "\n".join(p for p in parts if p)


def _code_cloze_blob(solve: dict) -> str:
    parsed = solve.get("parsed") or {}
    blanks = parsed.get("blanks") or {}
    parts: list[str] = []
    if isinstance(blanks, dict):
        for key in sorted(blanks.keys(), key=lambda x: str(x)):
            item = blanks.get(key) or {}
            if isinstance(item, dict):
                parts.append(str(item.get("answer") or ""))
                parts.append(str(item.get("brief") or ""))
            else:
                parts.append(str(item))
    return "\n".join(p for p in parts if p).strip()


def _has_placeholders(text: str) -> Optional[str]:
    for pat in _PLACEHOLDER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return pat
    return None


def verify_teacher_rules(
    parsed: dict,
    teacher_constraints: Optional[dict],
    user_content: Optional[dict],
    *,
    sections_detected=None,
) -> list[dict[str, Any]]:
    """constraint_present / position checks for teacher rules."""
    checks: list[dict[str, Any]] = []
    rules = (teacher_constraints or {}).get("rules") or []
    if not rules:
        return checks

    section_fields = {
        "steps": parsed.get("steps_analysis") or "",
        "result": parsed.get("result_description") or "",
        "summary": parsed.get("summary") or "",
    }
    # Add non-core sections from sections_detected (content generated in fill stage, not in parsed)
    if sections_detected:
        for sec in sections_detected:
            semantic = sec.get("semantic")
            if semantic and semantic not in section_fields:
                section_fields[semantic] = ""
            elif not semantic:
                key = f"sec_{sec.get('index')}"
                if key not in section_fields:
                    section_fields[key] = ""
    uc = user_content or {}

    for rule in rules:
        text = (rule.get("text") or "").strip()
        if not text:
            continue
        sid = rule.get("section") or "summary"
        body = section_fields.get(sid, "") or uc.get(sid, "")
        if not body:
            checks.append(
                {
                    "id": "constraint_present",
                    "ok": False,
                    "message": f"节 [{sid}] 无内容，无法校验: {text[:40]}",
                }
            )
            continue
        present = text in body
        checks.append(
            {
                "id": "constraint_present",
                "ok": present,
                "message": "已包含老师要求" if present else f"缺少要求原文: {text[:60]}",
                "rule": text[:80],
            }
        )
        if present and rule.get("position") == "end":
            tail = body[-200:] if len(body) > 200 else body
            at_end = text in tail
            checks.append(
                {
                    "id": "constraint_position",
                    "ok": at_end,
                    "message": "要求位于节末" if at_end else "要求未出现在该节末尾 200 字内",
                    "rule": text[:80],
                }
            )
    return checks


def verify_answer(
    ctx: dict[str, Any],
    *,
    answer_template_text: str = "",
) -> dict[str, Any]:
    """
    Build verification_report from module_results and plan steps.
    """
    checks: list[dict[str, Any]] = []
    suggested: list[str] = []

    mr = ctx.get("module_results") or {}
    solve = (
        (mr.get("solve_lab") or {}).get("data")
        or (mr.get("solve_code_cloze") or {}).get("data")
        or (mr.get("solve_theory") or {}).get("data")
        or {}
    )
    parsed = solve.get("parsed") or {}
    steps = ctx.get("confirmed_steps") or (ctx.get("plan") or {}).get("steps") or []
    step_modules = {s.get("module") for s in steps if s.get("default_checked", True)}

    solve_type = solve.get("type")
    if solve_type == "code_cloze":
        blanks = (solve.get("parsed") or {}).get("blanks") or {}
        cloze_ok = isinstance(blanks, dict) and bool(blanks)
        checks.append(
            {
                "id": "code_cloze_schema",
                "ok": cloze_ok,
                "message": "代码完形结构完整" if cloze_ok else "缺少 blanks 结构化答案",
                "auto_fix": "revise_full" if not cloze_ok else None,
            }
        )
        if not cloze_ok:
            suggested.append("revise_full")
    elif solve.get("type") == "theory" or "solve_theory" in step_modules and "solve_lab" not in step_modules:
        required = ["answer"]
        missing = [k for k in required if not (solve.get(k) or solve.get("answer"))]
        schema_ok = not missing
        checks.append(
            {
                "id": "schema_complete",
                "ok": schema_ok,
                "message": "结构完整" if schema_ok else f"缺少字段: {', '.join(missing)}",
                "auto_fix": "revise_full" if not schema_ok else None,
            }
        )
        if not schema_ok:
            suggested.append("revise_full")
    else:
        required = ["steps_analysis", "result_description", "summary", "code"]
        missing = [k for k in required if not (parsed.get(k) or (k == "code" and solve.get("code")))]
        schema_ok = not missing
        checks.append(
            {
                "id": "schema_complete",
                "ok": schema_ok,
                "message": "结构完整" if schema_ok else f"缺少字段: {', '.join(missing)}",
                "auto_fix": "revise_full" if not schema_ok else None,
            }
        )
        if not schema_ok:
            suggested.append("revise_full")

    blob = _parsed_text_blob(parsed) or (solve.get("answer") or "")
    if solve_type == "code_cloze":
        blob = _code_cloze_blob(solve) or blob
    ph = _has_placeholders(blob)
    checks.append(
        {
            "id": "no_placeholder",
            "ok": ph is None,
            "message": "无占位符" if ph is None else f"检测到占位: {ph}",
        }
    )

    if "run_code" in step_modules:
        run_mr = mr.get("run_code") or {}
        run_data = run_mr.get("data") or {}
        is_err = run_data.get("is_error") or run_data.get("error")
        code_ok = run_mr.get("ok") and not is_err
        checks.append(
            {
                "id": "code_runs",
                "ok": code_ok,
                "message": "代码运行通过" if code_ok else (run_data.get("output") or "运行失败")[:200],
                "auto_fix": "fix_code" if not code_ok else None,
            }
        )
        if not code_ok:
            suggested.append("fix_code")

        expected = parsed.get("expected_output") or ""
        actual = run_data.get("output") or ""
        exp_nums = extract_numbers(expected)
        act_nums = extract_numbers(actual)
        if exp_nums and act_nums:
            matched = 0
            for en in exp_nums[:8]:
                for an in act_nums[:12]:
                    if en == 0 and an == 0:
                        matched += 1
                        break
                    base = max(abs(en), 1e-9)
                    if abs(an - en) / base <= 0.05:
                        matched += 1
                        break
            ratio = matched / len(exp_nums)
            if ratio >= 0.5:
                oc_ok, oc_msg = True, "输出数值与预期基本一致"
            elif ratio > 0:
                oc_ok, oc_msg = False, "部分数值与预期偏差较大"
                suggested.append("revise_section:result")
            else:
                oc_ok, oc_msg = False, "输出数值与预期差异明显"
                suggested.append("fix_code")
            checks.append({"id": "output_consistency", "ok": oc_ok, "message": oc_msg})
        elif expected and not actual:
            checks.append(
                {
                    "id": "output_consistency",
                    "ok": False,
                    "message": "有预期输出描述但运行输出为空",
                    "auto_fix": "fix_code",
                }
            )

    if "fill_report" in step_modules or "present_deliverable" in step_modules:
        if solve_type == "code_cloze":
            blanks = (solve.get("parsed") or {}).get("blanks") or {}
            content_ready = isinstance(blanks, dict) and bool(blanks)
        else:
            content_ready = bool(
                parsed.get("steps_analysis")
                and parsed.get("result_description")
                and parsed.get("summary")
            )
        if "present_deliverable" in step_modules:
            checks.append(
                {
                    "id": "deliverable_ready",
                    "ok": content_ready,
                    "message": "答案分节完整" if content_ready else "步骤/结果/总结有缺失",
                }
            )
        if "fill_report" in step_modules:
            checks.append(
                {
                    "id": "fill_ready",
                    "ok": content_ready,
                    "message": "可填表" if content_ready else "填表前三节内容不完整",
                }
            )

    diagrams = extract_diagrams(parsed)
    code_text = solve.get("code") or parsed.get("code") or ""
    language = solve.get("language") or parsed.get("language") or "java"

    uml_mr = mr.get("render_uml") or {}
    uml_data = uml_mr.get("data") or {}
    render_for_verify = None
    if uml_data.get("errors") is not None or uml_data.get("images_b64") is not None:
        render_for_verify = uml_data

    if diagrams:
        dverify = verify_diagrams(
            {"parsed": parsed, "code": code_text, "language": language},
            render_result=render_for_verify if render_for_verify is not None else None,
            include_consistency=bool(code_text),
        )
        for chk in dverify.get("checks") or []:
            cid = chk.get("id") or "diagram_check"
            entry = {
                "id": cid if cid != "uml_schema" else "diagram_schema",
                "ok": chk.get("ok", True),
                "message": chk.get("message", ""),
            }
            if cid == "uml_code_consistency":
                entry["id"] = "uml_code_consistency"
                entry["auto_fix"] = "fix_diagrams" if not chk.get("ok") else None
            elif cid == "diagram_render":
                entry["auto_fix"] = (
                    "render_uml"
                    if not chk.get("ok") and not dverify.get("suggested_actions")
                    else None
                )
            elif cid == "uml_schema":
                entry["auto_fix"] = "fix_diagrams" if not chk.get("ok") else None
            checks.append(entry)
            if not chk.get("ok"):
                for action in dverify.get("suggested_actions") or []:
                    if action not in suggested:
                        suggested.append(action)

    if "render_uml" in step_modules and diagrams:
        uml_imgs = uml_data.get("images_b64") or []
        uml_errors = uml_data.get("errors") or []
        validation = uml_data.get("validation") or {}
        render_ok = uml_mr.get("ok") and bool(uml_imgs) and validation.get("ok", not uml_errors)
        msg = validation.get("checks") and next(
            (c.get("message") for c in validation["checks"] if c.get("id") == "diagram_render"),
            None,
        )
        if not msg:
            msg = f"图表已渲染 {len(uml_imgs)} 张" if render_ok else (
                "; ".join(uml_errors[:3]) if uml_errors else "计划含图表但未生成图片"
            )
        checks.append(
            {
                "id": "uml_render_valid",
                "ok": render_ok,
                "message": msg,
                "auto_fix": (dverify.get("suggested_actions") or ["render_uml"])[0]
                if not render_ok
                else None,
            }
        )
        if not render_ok:
            for action in dverify.get("suggested_actions") or ["render_uml"]:
                if action not in suggested:
                    suggested.append(action)

    tpl = answer_template_text or ctx.get("answer_template_text") or ""
    if tpl:
        plag = check_plagiarism(blob, tpl)
        checks.append(
            {
                "id": "plagiarism_check",
                "ok": plag["ok"],
                "message": plag["message"] or "与范文相似度可接受",
                "ratio": plag.get("ratio"),
            }
        )
        if not plag["ok"]:
            suggested.append("revise_full")

    teacher_user_content = ctx.get("user_content")
    if solve_type == "code_cloze":
        # code_cloze has no report sections; map blank answers/brief into summary checks.
        teacher_user_content = {"summary": blob, **(teacher_user_content or {})}

    checks.extend(
        verify_teacher_rules(
            parsed,
            ctx.get("teacher_constraints"),
            teacher_user_content,
            sections_detected=ctx.get("sections_detected"),
        )
    )

    blocking_ids = {
        "no_placeholder",
        "code_runs",
        "constraint_present",
    }
    if solve_type == "code_cloze":
        blocking_ids.add("code_cloze_schema")
    else:
        blocking_ids.add("schema_complete")
    passed = not any(
        not c.get("ok") for c in checks if c.get("id") in blocking_ids
    )

    from agent.executor_dirty import modules_to_rerun_from_verify

    rerun_modules = modules_to_rerun_from_verify(suggested, ctx)

    return {
        "passed": passed,
        "checks": checks,
        "suggested_actions": list(dict.fromkeys(suggested)),
        "rerun_modules": rerun_modules,
    }
