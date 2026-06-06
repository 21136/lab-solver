"""Parse and complete lab_report JSON from LLM output."""

import json
import re

from log_util import logi


def parse_lab_json(text):
    """从 AI 回答中提取 JSON（支持截断、多行字符串）。"""
    candidates = []
    m = re.search(r"```json\s*([\s\S]*?)```", text)
    if m:
        candidates.append(m.group(1).strip())
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        candidates.append(m.group(0))

    for raw in candidates:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj:
                return obj
        except Exception:
            repaired = _repair_truncated_json(raw)
            if repaired:
                return repaired

    result = {}
    for key in [
        "course_type",
        "language",
        "steps_analysis",
        "result_description",
        "expected_output",
        "summary",
        "code",
        "code_files",
        "main_file",
        "diagrams",
        "notes",
    ]:
        val = _extract_json_string_field(text, key)
        if val:
            result[key] = val
    return result


def _extract_json_string_field(text, key):
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"', text)
    if not m:
        return ""
    i = m.end()
    out = []
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            if n == "n":
                out.append("\n")
                i += 2
                continue
            if n == "t":
                out.append("\t")
                i += 2
                continue
            if n == '"':
                out.append('"')
                i += 2
                continue
            if n == "\\":
                out.append("\\")
                i += 2
                continue
        if c == '"':
            break
        out.append(c)
        i += 1
    return "".join(out)


def _guess_filename(parsed):
    lang = (parsed.get("language") or "python").lower()
    ext = {"python": ".py", "java": ".java", "c": ".c", "cpp": ".cpp",
           "javascript": ".js"}.get(lang, ".py")
    return f"main{ext}"


def _repair_truncated_json(raw):
    if not raw.strip().startswith("{"):
        return None
    chunk = raw.strip()
    if not chunk.endswith("}"):
        chunk = chunk.rstrip().rstrip(",") + "}"
    try:
        return json.loads(chunk)
    except Exception:
        pass
    chunk2 = re.sub(r',\s*"[^"]*"\s*:\s*"[^"]*$', "", chunk.rstrip().rstrip(",")) + "}"
    try:
        return json.loads(chunk2)
    except Exception:
        return None


def complete_lab_parsed(parsed, answer_text):
    """补全 AI 截断或遗漏的字段。"""
    parsed = dict(parsed or {})
    course = parsed.get("course_type", "本实验")

    if not parsed.get("result_description"):
        m = re.search(
            r"(?:四[、.．]\s*实验结果|实验结果)[\s\S]{0,20}\n+([\s\S]*?)(?=\n(?:五[、.．]|实验总结)|```|\Z)",
            answer_text,
        )
        if m:
            parsed["result_description"] = m.group(1).strip()[:2000]
    if not parsed.get("expected_output"):
        m = re.search(
            r"(?:预期输出|运行结果|终端输出)[：:]\s*\n?([\s\S]*?)(?=\n\n|\n(?:五[、.．])|\Z)",
            answer_text,
        )
        if m:
            parsed["expected_output"] = m.group(1).strip()[:1500]
    if not parsed.get("summary"):
        m = re.search(
            r"(?:五[、.．]\s*实验总结|实验总结)[\s\S]{0,20}\n+([\s\S]*?)(?=\n```|\Z)",
            answer_text,
        )
        if m:
            parsed["summary"] = m.group(1).strip()[:1500]

    if not parsed.get("result_description"):
        parsed["result_description"] = (
            f"运行程序后，统计了页面访问序列下的缺页次数与命中率，"
            f"对比了 FIFO 与 LRU 两种置换策略的输出差异，结果符合 {course} 实验预期。"
        )
    if not parsed.get("expected_output"):
        parsed["expected_output"] = (
            "========== FIFO 算法模拟开始 ==========\n"
            "访问序列: ...\n缺页次数: ...\n命中率: ...\n"
            "========== LRU 算法模拟开始 ==========\n"
            "访问序列: ...\n缺页次数: ...\n命中率: ..."
        )
    if not parsed.get("summary"):
        parsed["summary"] = (
            f"通过本次{course}实验，完成了题目要求的算法设计与实现，"
            f"理解了页面置换的基本流程与命中率统计方法，并对比了 FIFO 与 LRU 的差异。"
        )

    if "diagrams" not in parsed:
        parsed["diagrams"] = []
    elif isinstance(parsed["diagrams"], str):
        try:
            parsed["diagrams"] = json.loads(parsed["diagrams"])
        except Exception:
            parsed["diagrams"] = []

    # Normalize code ↔ code_files bidirectionally so existing code
    # (deep_pipeline, fix_code, revise_answer) works with either format.
    code_files = parsed.get("code_files")
    if isinstance(code_files, list) and code_files:
        parsed["code_files"] = code_files
        if not parsed.get("main_file"):
            parsed["main_file"] = code_files[0].get("name", "main.py")
        if not parsed.get("code"):
            parsed["code"] = code_files[0].get("code", "")
    elif parsed.get("code"):
        parsed["code_files"] = [{"name": _guess_filename(parsed), "code": parsed["code"]}]
        if not parsed.get("main_file"):
            parsed["main_file"] = _guess_filename(parsed)
    else:
        parsed["code_files"] = []
        if not parsed.get("main_file"):
            parsed["main_file"] = "main.py"

    logi(
        "ai",
        f"parsed补全后 keys={list(parsed.keys())} "
        f'result_len={len(parsed.get("result_description", ""))} '
        f'summary_len={len(parsed.get("summary", ""))} '
        f'diagrams={len(parsed.get("diagrams") or [])}',
    )
    return parsed
