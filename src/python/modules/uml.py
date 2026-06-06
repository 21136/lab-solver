"""UML diagram extraction and rendering."""

import base64
import json
from pathlib import Path
from typing import Any

from config import TEMP_DIR, UML_RENDER_OK
from modules.uml_consistency import check_uml_code_consistency

MAX_DIAGRAMS = 12

KIND_LABELS = {
    "class": "类图", "sequence": "时序图", "usecase": "用例图",
    "activity": "活动图", "state": "状态图", "er": "ER图",
    "deployment": "部署图", "component": "构件图", "package": "包图",
    "flowchart": "流程图", "dfd": "DFD",
}

VALID_DIAGRAM_KINDS = frozenset({
    "class", "sequence", "usecase", "activity", "state", "er", "deployment",
    "component", "package", "flowchart", "dfd",
})

if UML_RENDER_OK:
    from uml_render import render_diagrams, is_plantuml_error_png


def diagram_kind_stats(diagrams) -> dict[str, int]:
    """Count diagrams by kind for render summaries."""
    stats: dict[str, int] = {}
    for d in diagrams or []:
        if not isinstance(d, dict):
            continue
        kind = (d.get("kind") or "unknown").lower()
        stats[kind] = stats.get(kind, 0) + 1
    return stats


def format_render_summary(data: dict) -> str:
    """Human-readable render_uml result line (kind breakdown when available)."""
    if data.get("skipped"):
        return "UML 渲染跳过（无 diagrams）"
    imgs = data.get("images_b64") or []
    kind_stats = data.get("kind_stats") or {}
    if kind_stats:
        parts = [
            f"{KIND_LABELS.get(k, k)}×{n}"
            for k, n in sorted(kind_stats.items())
        ]
        return f"UML 渲染完成，共 {len(imgs)} 张（{', '.join(parts)}）"
    return f"UML 渲染完成，共 {len(imgs)} 张"


def _diagram_has_source(item: dict) -> bool:
    if item.get("plantuml") or item.get("dfd_json"):
        return True
    src = item.get("source")
    if isinstance(src, str) and src.strip():
        return True
    if isinstance(src, dict):
        return True
    return False


def extract_diagrams(parsed) -> list:
    """从 parsed 取出可渲染的 diagram 列表。"""
    d = (parsed or {}).get("diagrams")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except Exception:
            d = []
    if not isinstance(d, list):
        return []
    out = []
    for item in d:
        if isinstance(item, dict) and _diagram_has_source(item):
            out.append(item)
    return out[:MAX_DIAGRAMS]


def render_uml_diagrams(
    diagrams,
    allow_online: bool = True,
    *,
    code: str = "",
    language: str = "java",
) -> dict[str, Any]:
    """Render PlantUML diagrams to base64 PNG list."""
    if not UML_RENDER_OK:
        raise RuntimeError("uml_render 模块不可用")

    rendered = render_diagrams(diagrams, TEMP_DIR / "uml", allow_online=allow_online)
    images_b64 = []
    titles = []
    sources = []
    errors = []
    for r in rendered:
        if r.get("path") and Path(r["path"]).is_file():
            raw = Path(r["path"]).read_bytes()
            if is_plantuml_error_png(raw):
                errors.append(f"{r.get('title', '图')}: 渲染结果为错误占位图")
                continue
            images_b64.append(base64.b64encode(raw).decode())
            titles.append(r.get("title", ""))
        elif r.get("error"):
            errors.append(f"{r.get('title', '图')}: {r['error']}")
    for d in diagrams or []:
        if isinstance(d, dict):
            src = (d.get("plantuml") or d.get("source") or "").strip()
            if src:
                sources.append(src)

    consistency = None
    if code and diagrams:
        consistency = check_uml_code_consistency(code, diagrams, language=language)

    kind_stats = diagram_kind_stats(diagrams)

    from modules.diagram_verify import verify_diagrams

    validation = verify_diagrams(
        {"parsed": {"diagrams": diagrams}, "code": code, "language": language},
        render_result={
            "images_b64": images_b64,
            "errors": errors,
        },
        include_consistency=bool(code and diagrams),
    )

    out = {
        "success": len(images_b64) > 0 and validation.get("ok", False),
        "images_b64": images_b64,
        "titles": titles,
        "sources": sources,
        "errors": errors,
        "consistency": consistency,
        "kind_stats": kind_stats,
        "validation": validation,
        "suggested_actions": validation.get("suggested_actions") or [],
    }
    out["summary"] = format_render_summary(out)
    return out
