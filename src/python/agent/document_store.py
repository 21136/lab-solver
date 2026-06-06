"""
In-memory parsed document cache (document_ids — no base64 re-upload on run).
"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from config import TEMP_DIR
from log_util import logi
_MAX_ENTRIES = 32
_TTL_SEC = 3600

_store: dict[str, dict[str, Any]] = {}


def _evict_old():
    if len(_store) <= _MAX_ENTRIES:
        return
    now = time.time()
    stale = [k for k, v in _store.items() if now - v.get("created_at", 0) > _TTL_SEC]
    for k in stale:
        _store.pop(k, None)
    while len(_store) > _MAX_ENTRIES:
        oldest = min(_store, key=lambda k: _store[k].get("created_at", 0))
        _store.pop(oldest, None)


def put_bundle(bundle: dict[str, Any]) -> str:
    """Store a parsed document bundle; returns document_id."""
    doc_id = bundle.get("document_id") or str(uuid.uuid4())
    bundle["document_id"] = doc_id
    bundle["created_at"] = bundle.get("created_at") or time.time()
    _store[doc_id] = bundle
    _evict_old()
    return doc_id


def store_from_file_bytes(
    file_bytes: bytes,
    file_name: str,
    *,
    needs_uml: bool = False,
    role: str = "fill_target",
) -> tuple[str, dict[str, Any]]:
    """Parse docx and cache; returns (document_id, parsed bundle)."""
    from agent.parse_documents import parse_single_file

    bundle = parse_single_file(
        file_bytes,
        file_name,
        role=role,
        needs_uml=needs_uml,
    )
    doc_id = put_bundle(bundle)
    logi("document_store", f"stored {doc_id} file={file_name} len={len(bundle.get('report_text', ''))}")
    return doc_id, bundle


def store_from_text(
    report_text: str,
    *,
    metadata: Optional[dict] = None,
    question: Optional[dict] = None,
    file_name: str = "inline.txt",
) -> tuple[str, dict[str, Any]]:
    doc_id = str(uuid.uuid4())
    text = (report_text or "").strip()
    bundle = {
        "document_id": doc_id,
        "role": "fill_target",
        "layout": "fill_only",
        "file_name": file_name,
        "file_path": "",
        "report_text": text,
        "planner_input_text": text,
        "full_text": text,
        "fill_body_text": text,
        "assignment_text": "",
        "metadata": metadata or {},
        "question": question
        or {"type": "lab_report", "content": text, "full_text": text},
        "warnings": [],
        "needs_uml": False,
        "split_idx": None,
        "created_at": time.time(),
    }
    put_bundle(bundle)
    return doc_id, bundle


def get_document(document_id: str) -> Optional[dict[str, Any]]:
    rec = _store.get(document_id)
    if not rec:
        return None
    if time.time() - rec.get("created_at", 0) > _TTL_SEC:
        _store.pop(document_id, None)
        return None
    return rec


def store_parsed_batch(bundles: list[dict[str, Any]]) -> list[str]:
    ids = []
    for b in bundles:
        ids.append(put_bundle(b))
    return ids


def resolve_agent_context(document_ids: list[str]) -> dict[str, Any]:
    """
    Rebuild multi-document agent fields from cached bundles.
    """
    if not document_ids:
        raise ValueError("缺少 document_ids")

    bundles = []
    for did in document_ids:
        rec = get_document(did)
        if not rec:
            raise ValueError(f"文档缓存已过期或不存在: {did}")
        bundles.append(rec)

    fill_targets = [b for b in bundles if b.get("role") == "fill_target"]
    if not fill_targets:
        fill_targets = [bundles[0]]
    if len(fill_targets) > 1:
        raise ValueError("只能有一份待填报告 (fill_target)")

    primary = fill_targets[0]
    assignments = [
        (b.get("full_text") or b.get("report_text") or "")
        for b in bundles
        if b.get("role") == "assignment"
    ]
    assignment_parts = [t for t in assignments if t.strip()]
    if primary.get("assignment_text"):
        assignment_parts.insert(0, primary["assignment_text"])
    assignment_text = "\n\n".join(assignment_parts)

    references = [
        (b.get("full_text") or "")[:3000]
        for b in bundles
        if b.get("role") == "reference"
    ]

    from agent.parse_documents import build_planner_input_text

    planner_input = build_planner_input_text(
        assignment_text=assignment_text,
        fill_body_text=primary.get("fill_body_text") or primary.get("report_text") or "",
        reference_excerpts=references,
        layout=primary.get("layout") or "fill_only",
    )

    warnings: list[str] = []
    for b in bundles:
        for w in b.get("warnings") or []:
            if isinstance(w, dict):
                warnings.append(w.get("message", str(w)))
            else:
                warnings.append(str(w))

    format_spec = None
    tpl_bundles = [b for b in bundles if b.get("role") == "answer_template"]
    if tpl_bundles:
        cached = tpl_bundles[0].get("format_spec")
        if cached:
            format_spec = cached
        else:
            tpl_path = tpl_bundles[0].get("file_path")
            if tpl_path:
                from pathlib import Path

                from modules.parse_answer_template import parse_answer_template

                p = Path(tpl_path)
                if p.exists():
                    format_spec = parse_answer_template(
                        p.read_bytes(),
                        tpl_bundles[0].get("file_name") or "template.docx",
                        assignment_metadata=primary.get("metadata"),
                        assignment_text=assignment_text or planner_input,
                    )
                    tpl_bundles[0]["format_spec"] = format_spec

    from document.pdf_export import resolve_fill_target_info

    fill_target_info = resolve_fill_target_info(bundles, primary)

    return {
        "document_ids": document_ids,
        "documents": bundles,
        "format_spec": format_spec,
        "fill_target": {
            "id": primary["document_id"],
            "file_name": primary.get("file_name"),
            "file_path": primary.get("file_path"),
            "metadata": primary.get("metadata") or {},
            "full_text": primary.get("fill_body_text") or primary.get("report_text"),
            "source_format": fill_target_info.get("source_format")
            or (primary.get("metadata") or {}).get("source_format", "docx"),
            "layout": primary.get("layout"),
            "split_idx": primary.get("split_idx"),
            "split_at_heading": primary.get("split_at_heading"),
            "export_format": "docx",
            "fill_docx_from": fill_target_info.get("from"),
            "fill_docx_path": fill_target_info.get("path") or "",
            "export_message": fill_target_info.get("message") or "",
        },
        "fill_target_info": fill_target_info,
        "assignment_text": assignment_text,
        "planner_input_text": planner_input,
        "report_text": primary.get("report_text") or "",
        "metadata": dict(primary.get("metadata") or {}),
        "question": primary.get("question") or {},
        "warnings": warnings,
        "needs_uml": any(b.get("needs_uml") for b in bundles),
        "split_idx": primary.get("split_idx"),
        "layout": primary.get("layout"),
        "primary_bundle": primary,
    }


def resolve_documents(document_ids: list[str]) -> tuple[str, dict, dict, list[str]]:
    """
    Legacy merge: primary fill-target text + metadata + question + warnings.
    """
    ctx = resolve_agent_context(document_ids)
    return (
        ctx["report_text"],
        ctx["metadata"],
        ctx["question"],
        ctx["warnings"],
    )


def store_from_request_payload(data: dict) -> tuple[list[str], dict[str, Any]]:
    """
    Accept documents[], file_data, report_text, or document_ids.
    Returns (document_ids, primary_bundle_or_context).
    """
    existing = data.get("document_ids") or []
    if existing:
        ids = [str(x) for x in existing]
        ctx = resolve_agent_context(ids)
        return ids, ctx

    documents = data.get("documents")
    if documents:
        from agent.parse_documents import parse_documents_list

        parsed = parse_documents_list(
            documents,
            default_needs_uml=bool(data.get("include_uml") or data.get("includeUml")),
        )
        ids = store_parsed_batch(parsed["_bundles"])
        parsed["document_ids"] = ids
        return ids, parsed

    file_data = data.get("file_data")
    if file_data:
        file_name = data.get("file_name", "report.docx")
        file_bytes = base64.b64decode(file_data)
        needs_uml = bool(data.get("include_uml") or data.get("includeUml"))
        layout = data.get("layout")
        split_at_heading = data.get("split_at_heading")
        if layout or split_at_heading:
            from agent.parse_documents import parse_single_file

            bundle = parse_single_file(
                file_bytes,
                file_name,
                role=data.get("role") or "fill_target",
                layout_override=layout,
                split_at_heading=split_at_heading,
                needs_uml=needs_uml,
            )
            doc_id = put_bundle(bundle)
            return [doc_id], bundle
        doc_id, bundle = store_from_file_bytes(file_bytes, file_name, needs_uml=needs_uml)
        return [doc_id], bundle

    report_text = (data.get("report_text") or data.get("full_text") or "").strip()
    if report_text:
        doc_id, bundle = store_from_text(
            report_text,
            metadata=data.get("metadata"),
            question=data.get("question"),
            file_name=data.get("file_name", "inline.txt"),
        )
        return [doc_id], bundle

    raise ValueError("缺少 report_text、file_data、documents 或 document_ids")


def clear_run_temp(run_id: str) -> None:
    """Best-effort cleanup of run-scoped temp artifacts (policy: keep document cache)."""
    prefix = f"run_{run_id}_"
    for p in TEMP_DIR.glob(f"{prefix}*"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
