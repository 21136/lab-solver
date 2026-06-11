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

from pathlib import Path

from config import APP_DATA

_REPO_ROOT = Path(__file__).resolve().parents[3]
AI_INSIGHTS_PATH = _REPO_ROOT / "docs" / "reference" / "AI_INSIGHTS.md"
PROMOTED_SKILLS_PATH = APP_DATA / "promoted_skills.json"


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


def _match_context_summary(match_ctx: dict) -> str:
    lang = match_ctx.get("language") or ""
    text = (match_ctx.get("full_text") or match_ctx.get("report_text") or "")[:120]
    return f"language={lang}; text_snippet={text!r}"


def _audit_skill_matches(
    agent_ctx: dict,
    matched: list[dict[str, Any]],
    match_ctx: dict,
    source: str,
) -> None:
    from agent.decision_log import append_decision

    evidence = _match_context_summary(match_ctx)
    if matched:
        for skill in matched:
            append_decision(
                agent_ctx,
                agent="skill_store",
                decision="skill_matched",
                source=source,
                target=str(skill.get("id") or ""),
                reason=str(skill.get("description") or skill.get("id") or ""),
                evidence=evidence,
            )
    else:
        append_decision(
            agent_ctx,
            agent="skill_store",
            decision="skill_no_match",
            source=source,
            target="",
            reason="no skills matched context triggers",
            evidence=evidence,
        )


def match_skills(
    ctx: dict,
    *,
    agent_ctx: dict | None = None,
    audit_source: str = "",
) -> list[dict[str, Any]]:
    """Return all skills whose trigger matches the given context."""
    matched = [s for s in SKILLS if s["trigger"](ctx)]
    if agent_ctx is not None and audit_source:
        _audit_skill_matches(agent_ctx, matched, ctx, audit_source)
    return matched


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


def _trigger_from_suggested(suggested: str):
    """Build a trigger_fn from candidate suggested_trigger string."""
    spec = (suggested or "").strip()

    def _fn(ctx: dict) -> bool:
        if spec.startswith("run_code.error_category="):
            cat = spec.split("=", 1)[1]
            for _mod, mr in (ctx.get("module_results") or {}).items():
                if not isinstance(mr, dict):
                    continue
                data = mr.get("data") or {}
                err = data.get("error_category")
                if isinstance(err, dict):
                    err = err.get("category")
                if str(err or "") == cat:
                    return True
            return False
        if spec.startswith("solve_lab.notes_hash="):
            want = spec.split("=", 1)[1]
            solve = (ctx.get("module_results") or {}).get("solve_lab") or {}
            notes = ((solve.get("data") or {}).get("parsed") or {}).get("notes") or ""
            return bool(notes) and _notes_hash(notes) == want
        return False

    return _fn


def _load_promoted_skills_file() -> list[dict[str, Any]]:
    if not PROMOTED_SKILLS_PATH.exists():
        return []
    try:
        raw = json.loads(PROMOTED_SKILLS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = raw.get("skills")
            return list(items) if isinstance(items, list) else []
        if isinstance(raw, list):
            return raw
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return []


def _save_promoted_skills_file(skills: list[dict[str, Any]]) -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    PROMOTED_SKILLS_PATH.write_text(
        json.dumps({"skills": skills}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _register_promoted_skill(entry: dict[str, Any]) -> None:
    skill_id = str(entry.get("id") or "").strip()
    if not skill_id or any(s.get("id") == skill_id for s in SKILLS):
        return
    inject = str(entry.get("inject") or "").strip()
    if not inject:
        return
    _register(
        skill_id,
        str(entry.get("description") or entry.get("source") or skill_id),
        _trigger_from_suggested(str(entry.get("suggested_trigger") or "")),
        inject,
    )


def load_promoted_skills() -> list[dict[str, Any]]:
    """Load user-promoted skills from disk and register triggers."""
    skills = _load_promoted_skills_file()
    for entry in skills:
        if isinstance(entry, dict):
            _register_promoted_skill(entry)
    return skills


load_promoted_skills()

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


def _audit_skill_candidates(
    agent_ctx: dict,
    signals: list[tuple[str, str]],
    *,
    source: str = "run_finalize",
) -> None:
    from agent.decision_log import append_decision

    if not signals:
        append_decision(
            agent_ctx,
            agent="skill_store",
            decision="skill_candidate_skipped",
            source=source,
            target="",
            reason="no run signals for skill candidates",
            evidence="",
        )
        return
    for kind, key in signals:
        cid = _candidate_id(kind, key)
        append_decision(
            agent_ctx,
            agent="skill_store",
            decision="skill_candidate_recorded",
            source=source,
            target=cid,
            reason=f"{kind}:{key}",
            evidence=_suggested_trigger(kind, key),
        )


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

    _audit_skill_candidates(ctx, signals)

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


def list_skill_candidates(*, status: str | None = "pending") -> list[dict[str, Any]]:
    """Return skill candidates, optionally filtered by status."""
    items = [c for c in _load_skill_candidates() if isinstance(c, dict)]
    if status:
        return [c for c in items if (c.get("status") or "pending") == status]
    return items


def _append_ai_insights_promote_note(
    skill_id: str,
    source: str,
    inject: str,
    suggested_trigger: str,
) -> bool:
    """Append promote record to docs/reference/AI_INSIGHTS.md when writable."""
    path = AI_INSIGHTS_PATH
    if not path.is_file():
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (
        f"\n## {stamp}\n\n"
        f"### Promoted skill: `{skill_id}`\n\n"
        f"**来源候选**: {source}\n\n"
        f"**触发器**: `{suggested_trigger}`\n\n"
        f"**注入文本**:\n\n{inject}\n"
    )
    try:
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
        return True
    except OSError:
        return False


def promote_skill_candidate(
    candidate_id: str,
    *,
    inject: str = "",
    description: str = "",
) -> dict[str, Any]:
    """
    Promote a pending candidate into promoted_skills.json and register at runtime.

    Returns the promoted skill entry or raises ValueError.
    """
    cid = (candidate_id or "").strip()
    if not cid:
        raise ValueError("缺少 candidate id")

    candidates = _load_skill_candidates()
    entry = next((c for c in candidates if c.get("id") == cid), None)
    if not entry:
        raise ValueError(f"未找到候选: {cid}")
    if entry.get("status") == "promoted":
        raise ValueError(f"候选已 promote: {cid}")

    inject_text = (inject or entry.get("suggested_inject") or "").strip()
    if not inject_text:
        inject_text = (
            f"【技能候选 {cid}】根据历史运行经验，请注意与此触发相关的常见错误模式。"
        )

    skill_entry = {
        "id": cid,
        "description": description or f"Promoted from {entry.get('source', cid)}",
        "source": entry.get("source") or cid,
        "suggested_trigger": entry.get("suggested_trigger") or "",
        "inject": inject_text,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }

    promoted = _load_promoted_skills_file()
    promoted = [s for s in promoted if s.get("id") != cid]
    promoted.append(skill_entry)
    _save_promoted_skills_file(promoted)
    _register_promoted_skill(skill_entry)

    entry["status"] = "promoted"
    entry["promoted_at"] = skill_entry["promoted_at"]
    entry["suggested_inject"] = inject_text
    _save_skill_candidates(candidates)

    insights_updated = _append_ai_insights_promote_note(
        cid,
        str(entry.get("source") or ""),
        inject_text,
        str(entry.get("suggested_trigger") or ""),
    )

    return {**skill_entry, "insights_updated": insights_updated}


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
