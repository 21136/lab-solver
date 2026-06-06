"""User generation constraints (V5-1)."""

from __future__ import annotations

import re
from typing import Any

KNOWN_CONSTRAINTS = frozenset(
    {
        "skip_validation",
        "no_external_jar",
        "single_file",
        "no_gui",
        "provenance_label",
        "allow_curated_jars",
    }
)

_CONSTRAINT_LABELS = {
    "skip_validation": "不内化验证代码（仅生成）",
    "no_external_jar": "禁止第三方 jar / 非 JDK 包",
    "single_file": "仅单文件源码",
    "no_gui": "不要图形界面",
    "provenance_label": "导出时加诚信标注",
    "allow_curated_jars": "允许白名单 jar（H2/SQLite）",
}


def normalize_user_constraints(raw: Any) -> list[str]:
    """Normalize constraint ids from request body or settings."""
    if not raw:
        return []
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, dict):
        items = [k for k, v in raw.items() if v and str(k).strip()]
    else:
        return []
    out: list[str] = []
    for item in items:
        key = item.lower().replace("-", "_")
        if key in KNOWN_CONSTRAINTS and key not in out:
            out.append(key)
    if "no_external_jar" in out and "allow_curated_jars" in out:
        out.remove("allow_curated_jars")
    return out


def constraints_from_ctx(ctx: dict) -> list[str]:
    """Read constraints from agent context or nested settings."""
    direct = normalize_user_constraints(ctx.get("user_constraints"))
    if direct:
        return direct
    settings = ctx.get("settings") or {}
    from_settings = normalize_user_constraints(settings.get("user_constraints"))
    if from_settings:
        return from_settings
    return normalize_user_constraints(settings.get("userConstraints"))


def should_skip_validation(constraints: list[str]) -> bool:
    return "skip_validation" in constraints


def build_constraints_prompt_block(constraints: list[str]) -> str:
    """Inject into LLM prompts."""
    if not constraints:
        return ""
    lines = ["【用户约束（必须遵守）】"]
    for cid in constraints:
        label = _CONSTRAINT_LABELS.get(cid, cid)
        lines.append(f"- {label} ({cid})")
    if "no_external_jar" in constraints:
        lines.append(
            "- 仅使用 JDK 标准库（java.*）；禁止 import org.*、com.* 等第三方包；"
            "数据库类实验请用内存模拟或 Java SE 集合代替。"
        )
    if "single_file" in constraints:
        lines.append("- code_files 数组长度必须为 1。")
    if "skip_validation" in constraints:
        lines.append("- 用户不要求内化验证，但仍须生成完整可运行风格的代码。")
    if "allow_curated_jars" in constraints:
        lines.append(
            "- 允许使用白名单 jar（H2、SQLite JDBC）进行内化验证；"
            "仅可使用已安装或用户同意下载的库，禁止假设其他 Maven 依赖。"
        )
    return "\n".join(lines) + "\n"


def allows_curated_jars(constraints: list[str]) -> bool:
    return "allow_curated_jars" in constraints and "no_external_jar" not in constraints


_JDK_JAVA_PREFIXES = ("java.", "javax.")


def has_disallowed_external_imports(code: str, language: str) -> bool:
    """True when code violates no_external_jar (Java)."""
    if (language or "").lower() != "java":
        return False
    for m in re.finditer(r"^\s*import\s+([\w.]+)\s*;", code or "", re.MULTILINE):
        pkg = m.group(1)
        if pkg.endswith(".*"):
            pkg = pkg[:-2]
        if not any(pkg == p.rstrip(".") or pkg.startswith(p) for p in _JDK_JAVA_PREFIXES):
            return True
    return False
