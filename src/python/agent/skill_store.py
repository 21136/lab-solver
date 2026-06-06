"""Learned skills — prompt injections that fire on context-matched triggers.

Skills are promoted from AI_INSIGHTS.md when an insight is confirmed across
multiple runs. Each skill defines a `trigger` (what context it matches) and an
`inject` (what prompt text to inject).

Format in AI_INSIGHTS.md for auto-discovery (optional):
    <!-- skill: servlet-ban-v1 -->
    <!-- triggers: language=java, keywords=web|servlet|jsp|网页|网站 -->
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from config import APP_DATA


def _match_keywords(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in text (case-insensitive)."""
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


# ══════════════════════════════════════════════════════
# Skill Registry
# Each skill: {id, description, trigger_fn(ctx)->bool, inject(text)}
# ══════════════════════════════════════════════════════

SKILLS: list[dict[str, Any]] = []


def _register(
    skill_id: str,
    description: str,
    trigger_fn,
    inject: str,
):
    SKILLS.append({
        "id": skill_id,
        "description": description,
        "trigger": trigger_fn,
        "inject": inject,
    })


def match_skills(ctx: dict) -> list[dict[str, Any]]:
    """Return all skills whose trigger matches the given context."""
    return [s for s in SKILLS if s["trigger"](ctx)]


def build_skill_injection(ctx: dict) -> str:
    """Build a prompt block from all matching skills, or '' if none match."""
    matched = match_skills(ctx)
    if not matched:
        return ""
    lines = ["\n【已知经验（从过往解题中学习）】"]
    for i, s in enumerate(matched, 1):
        lines.append(f"{i}. {s['inject']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# Built-in skills
# ══════════════════════════════════════════════════════

def _java_web_keywords(ctx: dict) -> bool:
    """Fire when language is Java AND report mentions web/keywords."""
    lang = (ctx.get("language") or "").lower()
    if lang not in ("java", ""):
        return False
    text = (ctx.get("full_text") or ctx.get("report_text") or "").lower()
    triggers = ["servlet", "jsp", "网页", "网站", "浏览器", "b/s", "web应用", "browser"]
    return _match_keywords(text, triggers)


_register(
    "java-no-servlet",
    "Java 代码禁止 Servlet/JSP，只用 Java SE",
    _java_web_keywords,
    "⚠️ 报告提到了 Web/网页关键词，但运行环境是命令行 javac/java，没有 Servlet 容器。"
    "如果实验就是 Web 应用，请用 com.sun.net.httpserver.HttpServer（JDK 自带）+ 独立 HTML 文件入 code_files。"
    "如果是普通实验，生成纯 Java SE 命令行程序即可，不要引入任何 Servlet 代码。",
)


def _java_multi_class(ctx: dict) -> bool:
    """Fire when Java and multi-class project detected."""
    lang = (ctx.get("language") or "").lower()
    if lang != "java":
        return False
    text = (ctx.get("full_text") or ctx.get("report_text") or "")
    return text.count("class ") >= 3 or "多态" in text or "继承" in text


_register(
    "java-multi-file",
    "Java 多类项目应拆分文件",
    _java_multi_class,
    "该实验涉及多个 class，请将每个 public class 拆分为独立的 .java 文件放入 code_files 数组，"
    "main_file 指定含 main 方法的入口文件。文件名必须与 public class 名一致。",
)


def _java_python_mixup(ctx: dict) -> bool:
    """Fire when Java context but report/error contains Python code patterns."""
    lang = (ctx.get("language") or "").lower()
    if lang not in ("java", ""):
        return False
    text = (ctx.get("full_text") or ctx.get("report_text") or "").lower()
    return _match_keywords(text, ["def ", "elif ", "print(", "import math", "import random"])


_register(
    "java-no-python",
    "Java 文件中禁止混入 Python 语法",
    _java_python_mixup,
    "⚠️ 生成的 .java 文件中必须是纯 Java 代码。禁止使用 Python 语法（def 定义函数、# 注释、"
    "print()、elif、import math 等）。如果代码是 Python 写的，文件名必须以 .py 结尾，"
    "且 language 字段应设为 python。请逐一检查每个 code_file 的内容是否与文件扩展名一致。",
)

# ══════════════════════════════════════════════════════
# Placeholder — add more skills here as insights mature
# ══════════════════════════════════════════════════════

# ── Skill candidate queue (V3-4) ──

SKILL_CANDIDATES_PATH = APP_DATA / "skill_candidates.json"
SKILL_CANDIDATE_MIN_OCCURRENCES = 2
SKILL_CANDIDATE_WINDOW_DAYS = 7


def _notes_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())[:500]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _load_skill_candidates() -> list[dict[str, Any]]:
    if not SKILL_CANDIDATES_PATH.exists():
        return []
    try:
        raw = json.loads(SKILL_CANDIDATES_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = raw.get("candidates")
            return list(items) if isinstance(items, list) else []
        if isinstance(raw, list):
            return raw
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return []


def _save_skill_candidates(candidates: list[dict[str, Any]]) -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    SKILL_CANDIDATES_PATH.write_text(
        json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _candidate_id(kind: str, key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", key.strip().lower())[:48]
    return f"{kind}-{safe}"


def _suggested_trigger(kind: str, key: str) -> str:
    if kind == "error_category":
        return f"run_code.error_category={key}"
    if kind == "notes_hash":
        return f"solve_lab.notes_hash={key}"
    return f"{kind}={key}"


def record_skill_candidates_from_run(ctx: dict) -> list[dict[str, Any]]:
    """Append run signals; return newly promoted pending candidates."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=SKILL_CANDIDATE_WINDOW_DAYS)
    signals: list[tuple[str, str]] = []

    for _mod, mr in (ctx.get("module_results") or {}).items():
        if not isinstance(mr, dict):
            continue
        data = mr.get("data") or {}
        cat = data.get("error_category")
        if isinstance(cat, dict):
            cat = cat.get("category")
        if cat:
            signals.append(("error_category", str(cat)))

    solve = (ctx.get("module_results") or {}).get("solve_lab") or {}
    notes = ((solve.get("data") or {}).get("parsed") or {}).get("notes") or ""
    if isinstance(notes, str) and notes.strip():
        signals.append(("notes_hash", _notes_hash(notes)))

    if not signals:
        return []

    candidates = _load_skill_candidates()
    by_id = {c.get("id"): c for c in candidates if isinstance(c, dict) and c.get("id")}
    new_pending: list[dict[str, Any]] = []

    for kind, key in signals:
        cid = _candidate_id(kind, key)
        entry = by_id.get(cid)
        if not entry:
            entry = {
                "id": cid,
                "source": f"{kind}:{key}",
                "occurrences": 0,
                "events": [],
                "suggested_trigger": _suggested_trigger(kind, key),
                "suggested_inject": "",
                "status": "pending",
            }
            candidates.append(entry)
            by_id[cid] = entry

        events = [e for e in (entry.get("events") or []) if isinstance(e, dict)]
        events = [
            e
            for e in events
            if _parse_iso(e.get("at")) and _parse_iso(e.get("at")) >= cutoff
        ]
        events.append({"at": now.isoformat(), "run_id": ctx.get("run_id") or ""})
        entry["events"] = events[-20:]
        entry["occurrences"] = len(events)
        entry["last_seen"] = now.isoformat()
        entry.setdefault("first_seen", now.isoformat())

        if entry["occurrences"] >= SKILL_CANDIDATE_MIN_OCCURRENCES and entry.get("status") == "pending":
            if entry not in new_pending:
                new_pending.append(entry)

    _save_skill_candidates(candidates)
    return new_pending


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
