"""Standard DFD: structured JSON validation and Graphviz DOT generation."""
from __future__ import annotations

import json
import re
from typing import Any

VALID_LEVELS = frozenset({"顶层", "0层", "1层", "top", "level0", "level1"})
NODE_PREFIX = {
    "external": "E",
    "process": "P",
    "store": "D",
}

_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s\-·.()（）]{0,30}$")


def extract_dfd_json(diagram: dict) -> dict | None:
    """Parse dfd_json from diagram dict (object, JSON string, or source field)."""
    if not isinstance(diagram, dict):
        return None
    raw = diagram.get("dfd_json")
    if raw is None:
        src = diagram.get("source")
        if isinstance(src, str) and src.strip().startswith("{"):
            raw = src
        elif isinstance(src, dict):
            raw = src
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, dict) else None


def _norm_level(level: Any) -> str:
    text = str(level or "0层").strip()
    mapping = {"top": "顶层", "level0": "0层", "level1": "1层"}
    return mapping.get(text.lower(), text)


def _node_map(data: dict) -> dict[str, tuple[str, str]]:
    """id -> (category, display_name)."""
    nodes: dict[str, tuple[str, str]] = {}
    for cat, key in (
        ("external", "externals"),
        ("process", "processes"),
        ("store", "stores"),
    ):
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            nid = str(item.get("id") or "").strip()
            name = str(item.get("name") or nid).strip()
            if nid:
                nodes[nid] = (cat, name or nid)
    return nodes


def validate_dfd(data: dict) -> list[str]:
    """Return validation error messages (empty if OK)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["dfd_json 必须是对象"]

    level = _norm_level(data.get("level"))
    if level and level not in VALID_LEVELS:
        errors.append(f"level 非法: {level!r}（应为 顶层/0层/1层）")

    nodes = _node_map(data)
    if not nodes:
        errors.append("dfd_json 至少包含一个外部实体、处理或数据存储")

    for cat, key, label in (
        ("external", "externals", "外部实体"),
        ("process", "processes", "处理"),
        ("store", "stores", "数据存储"),
    ):
        seen: set[str] = set()
        for i, item in enumerate(data.get(key) or []):
            if not isinstance(item, dict):
                errors.append(f"{label}{i + 1}: 必须是对象")
                continue
            nid = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not nid:
                errors.append(f"{label}{i + 1}: 缺少 id")
                continue
            if not _ID_RE.match(nid):
                errors.append(f"{label}{i + 1}: id={nid!r} 格式非法（字母/数字/下划线）")
            if nid in seen:
                errors.append(f"{label}{i + 1}: id={nid!r} 重复")
            seen.add(nid)
            if name and not _NAME_RE.match(name):
                errors.append(f"{label}{i + 1}: name={name!r} 命名不规范")
            if cat == "process" and name and not re.search(r"[\d.]|处理|加工|系统", name):
                # coarse: process names often numbered like "1.0 系统" or contain 处理
                if len(name) < 2:
                    errors.append(f"处理 {nid}: 名称过短")

    flows = data.get("flows") or []
    if not flows:
        errors.append("缺少 flows 数据流定义")
    for i, flow in enumerate(flows):
        if not isinstance(flow, dict):
            errors.append(f"数据流{i + 1}: 必须是对象")
            continue
        src = str(flow.get("from") or flow.get("source") or "").strip()
        dst = str(flow.get("to") or flow.get("target") or "").strip()
        label = str(flow.get("label") or flow.get("name") or "").strip()
        if not src or not dst:
            errors.append(f"数据流{i + 1}: 缺少 from/to 端点")
            continue
        if src not in nodes:
            errors.append(f"数据流{i + 1}: from={src!r} 不存在")
        if dst not in nodes:
            errors.append(f"数据流{i + 1}: to={dst!r} 不存在")
        if not label:
            errors.append(f"数据流{i + 1}: 缺少 label（数据流名称）")
        elif src in nodes and dst in nodes:
            sc, _ = nodes[src]
            dc, _ = nodes[dst]
            if sc == "store" and dc == "store":
                errors.append(f"数据流{i + 1}: 数据存储之间不能直接相连")
            if sc == "external" and dc == "external":
                errors.append(f"数据流{i + 1}: 外部实体之间不能直接相连")

    # coarse balance: each process should have at least one in/out flow
    proc_ids = {nid for nid, (cat, _) in nodes.items() if cat == "process"}
    if proc_ids and flows:
        in_count = {p: 0 for p in proc_ids}
        out_count = {p: 0 for p in proc_ids}
        for flow in flows:
            if not isinstance(flow, dict):
                continue
            src = str(flow.get("from") or flow.get("source") or "").strip()
            dst = str(flow.get("to") or flow.get("target") or "").strip()
            if src in proc_ids:
                out_count[src] += 1
            if dst in proc_ids:
                in_count[dst] += 1
        for pid in proc_ids:
            if in_count[pid] == 0 and out_count[pid] == 0:
                pname = nodes[pid][1]
                errors.append(f"处理 {pid}({pname}): 无数据流连接（平衡性粗检）")

    return errors


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _node_dot_id(nid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", nid)
    if safe and safe[0].isdigit():
        safe = f"n_{safe}"
    return safe or "node"


def dfd_to_dot(data: dict, title: str = "") -> str:
    """Generate Graphviz DOT with standard DFD shapes."""
    level = _norm_level(data.get("level"))
    graph_title = title or f"DFD {level}"
    lines = [
        "digraph DFD {",
        '  graph [rankdir=LR, splines=true, overlap=false, fontname="Microsoft YaHei"];',
        '  node [fontname="Microsoft YaHei", fontsize=11];',
        '  edge [fontname="Microsoft YaHei", fontsize=10];',
        f'  label="{_dot_escape(graph_title)}"; labelloc=t; fontsize=14;',
    ]

    id_map: dict[str, str] = {}

    for item in data.get("externals") or []:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        name = str(item.get("name") or nid).strip()
        if not nid:
            continue
        gid = _node_dot_id(nid)
        id_map[nid] = gid
        lines.append(
            f'  {gid} [shape=box, label="{_dot_escape(name)}", '
            f'tooltip="外部实体 {nid}"];'
        )

    for item in data.get("processes") or []:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        name = str(item.get("name") or nid).strip()
        if not nid:
            continue
        gid = _node_dot_id(nid)
        id_map[nid] = gid
        lines.append(
            f'  {gid} [shape=circle, fixedsize=true, width=1.3, height=1.3, '
            f'label="{_dot_escape(name)}", tooltip="处理 {nid}"];'
        )

    for item in data.get("stores") or []:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        name = str(item.get("name") or nid).strip()
        if not nid:
            continue
        gid = _node_dot_id(nid)
        id_map[nid] = gid
        # open-ended rectangle (DFD data store): record with open side
        lines.append(
            f'  {gid} [shape=record, label="{{{_dot_escape(name)}|}}", '
            f'tooltip="数据存储 {nid}"];'
        )

    for flow in data.get("flows") or []:
        if not isinstance(flow, dict):
            continue
        src = str(flow.get("from") or flow.get("source") or "").strip()
        dst = str(flow.get("to") or flow.get("target") or "").strip()
        label = str(flow.get("label") or flow.get("name") or "").strip()
        if src not in id_map or dst not in id_map:
            continue
        lines.append(
            f'  {id_map[src]} -> {id_map[dst]} [label="{_dot_escape(label)}"];'
        )

    lines.append("}")
    return "\n".join(lines)
