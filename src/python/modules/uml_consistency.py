"""Cross-check PlantUML class diagrams against source code (zero LLM)."""

from __future__ import annotations

import re
from typing import Any

_JAVA_TYPE_RE = re.compile(
    r"(?:public\s+|private\s+|protected\s+)?(?:static\s+|abstract\s+|final\s+)*"
    r"(?:class|interface|enum)\s+([A-Za-z_]\w*)",
    re.MULTILINE,
)
_PY_TYPE_RE = re.compile(
    r"^class\s+([A-Za-z_]\w*)",
    re.MULTILINE,
)
_PUML_TYPE_RE = re.compile(
    r"(?:abstract\s+)?(?:class|interface|enum)\s+([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_PUML_ENTITY_RE = re.compile(
    r'entity\s+(?:"([^"]+)"|([^\s{]+))',
    re.IGNORECASE,
)
_PUML_STATE_DECL_RE = re.compile(
    r'\bstate\s+(?:"([^"]+)"|([^\s"{]+))',
    re.IGNORECASE,
)
_PUML_STATE_TRANSITION_RE = re.compile(
    r'(?:"([^"]+)"|([^\s\[\]:]+))\s*--+>\s*(?:"([^"]+)"|([^\s\[\]:]+))',
)

_SKIP_NAMES = frozenset({
    "Object", "String", "System", "Exception", "RuntimeException",
    "Integer", "Boolean", "void", "main", "note", "package", "skinparam",
    "startuml", "enduml", "title", "left", "right", "top", "bottom",
})


def extract_code_types(code: str, language: str = "java") -> set[str]:
    """Extract user-defined type names from source code."""
    if not (code or "").strip():
        return set()
    lang = (language or "java").lower()
    if lang == "python":
        found = _PY_TYPE_RE.findall(code)
    else:
        found = _JAVA_TYPE_RE.findall(code)
    return {n for n in found if n not in _SKIP_NAMES}


def extract_plantuml_types(plantuml: str) -> set[str]:
    """Extract type names declared in PlantUML source."""
    if not (plantuml or "").strip():
        return set()
    found = _PUML_TYPE_RE.findall(plantuml)
    return {n for n in found if n not in _SKIP_NAMES}


def extract_er_entities(plantuml: str) -> set[str]:
    """Extract entity names from PlantUML ER diagram ``entity`` declarations."""
    if not (plantuml or "").strip():
        return set()
    names: set[str] = set()
    for quoted, bare in _PUML_ENTITY_RE.findall(plantuml):
        name = (quoted or bare or "").strip()
        if name and name.lower() not in _SKIP_NAMES:
            names.add(name)
    return names


def extract_state_names(plantuml: str) -> set[str]:
    """Rough extraction of state names from PlantUML state diagrams."""
    if not (plantuml or "").strip():
        return set()
    names: set[str] = set()
    for quoted, bare in _PUML_STATE_DECL_RE.findall(plantuml):
        name = (quoted or bare or "").strip()
        if name and name not in ("[*]", "start", "end"):
            names.add(name)
    for g1q, g1b, g2q, g2b in _PUML_STATE_TRANSITION_RE.findall(plantuml):
        for raw in (g1q, g1b, g2q, g2b):
            name = (raw or "").strip().strip('"')
            if not name or name in ("[*]", "start", "end"):
                continue
            if name.lower() in _SKIP_NAMES:
                continue
            names.add(name)
    return names


def check_uml_code_consistency(
    code: str,
    diagrams: list,
    *,
    language: str = "java",
    min_coverage: float = 0.6,
) -> dict[str, Any]:
    """
    Compare code types vs UML types across all diagrams.

    Returns {ok, message, code_types, uml_types, missing_in_uml, extra_in_uml, coverage}.
    """
    code_types = extract_code_types(code, language)
    uml_types: set[str] = set()
    for d in diagrams or []:
        if not isinstance(d, dict):
            continue
        src = d.get("plantuml") or d.get("source") or ""
        uml_types |= extract_plantuml_types(src)

    if not code_types:
        return {
            "ok": True,
            "message": "代码中未提取到类/接口，跳过 UML 对照",
            "code_types": [],
            "uml_types": sorted(uml_types),
            "missing_in_uml": [],
            "extra_in_uml": [],
            "coverage": 1.0,
        }
    if not uml_types:
        return {
            "ok": False,
            "message": "有代码类但未找到 UML 类定义",
            "code_types": sorted(code_types),
            "uml_types": [],
            "missing_in_uml": sorted(code_types),
            "extra_in_uml": [],
            "coverage": 0.0,
        }

    missing = sorted(code_types - uml_types)
    extra = sorted(uml_types - code_types)
    matched = len(code_types & uml_types)
    coverage = matched / max(len(code_types), 1)

    if not missing:
        msg = f"UML 已覆盖全部 {len(code_types)} 个代码类型"
        if extra:
            msg += f"（UML 另有 {len(extra)} 个未在代码出现的类型: {', '.join(extra[:6])}）"
        return {
            "ok": True,
            "message": msg,
            "code_types": sorted(code_types),
            "uml_types": sorted(uml_types),
            "missing_in_uml": [],
            "extra_in_uml": extra,
            "coverage": coverage,
        }

    if coverage >= min_coverage:
        msg = (
            f"UML 覆盖 {matched}/{len(code_types)} 个类型（{coverage:.0%}），"
            f"未出现在类图: {', '.join(missing[:8])}"
        )
        return {
            "ok": True,
            "message": msg,
            "code_types": sorted(code_types),
            "uml_types": sorted(uml_types),
            "missing_in_uml": missing,
            "extra_in_uml": extra,
            "coverage": coverage,
        }

    msg = (
        f"UML 仅覆盖 {matched}/{len(code_types)} 个类型（{coverage:.0%}），"
        f"缺失: {', '.join(missing[:8])}"
    )
    return {
        "ok": False,
        "message": msg,
        "code_types": sorted(code_types),
        "uml_types": sorted(uml_types),
        "missing_in_uml": missing,
        "extra_in_uml": extra,
        "coverage": coverage,
    }
