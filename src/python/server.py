"""
解题能手 - Python后端服务 v2
"""

import argparse
import base64
import json
import traceback
from datetime import datetime, timezone
import urllib.request
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from config import APP_DATA, DOCX_OK, JRE_DIR, PIL_OK, TEMP_DIR, UML_RENDER_OK
from config import detect_needs_uml
from hosted_providers import (
    hosted_providers_status,
    is_hosted_configured,
    llm_settings_error,
    resolve_llm_settings,
    save_hosted_api_key,
)
from log_util import get_log_buffer, loge, logi
from model_registry import get_model_catalog, normalize_saved_model
from llm_client import call_ai
from modules.fill_report import do_fill
from modules.fix_code import fix_code_from_error
from modules.parse_report import build_question_from_document, detect_docx_sections, document_format
from settings_schema import SETTINGS_DEFAULTS, SETTINGS_SCHEMA_VERSION


def _solve_quality_tier_from_request(data: dict) -> str:
    tier = str(
        data.get("solveQualityTier") or data.get("solve_quality_tier") or "standard"
    ).strip().lower()
    return tier if tier in ("fast", "standard", "thorough") else "standard"


def _solve_quality_tier_explicit_from_request(data: dict) -> bool:
    if "solveQualityTierExplicit" in data:
        return bool(data.get("solveQualityTierExplicit"))
    if "solve_quality_tier_explicit" in data:
        return bool(data.get("solve_quality_tier_explicit"))
    return False


def _auto_fast_tier_from_request(data: dict) -> bool:
    if "autoFastTierForLightQuestions" in data:
        return bool(data.get("autoFastTierForLightQuestions"))
    if "auto_fast_tier_for_light_questions" in data:
        return bool(data.get("auto_fast_tier_for_light_questions"))
    return True


def _enable_parallel_steps_from_request(data: dict) -> bool:
    if "enableParallelModuleSteps" in data:
        return bool(data.get("enableParallelModuleSteps"))
    if "enable_parallel_module_steps" in data:
        return bool(data.get("enable_parallel_module_steps"))
    return True


def _apply_solve_quality_settings(settings: dict, data: dict) -> None:
    settings["solveQualityTier"] = _solve_quality_tier_from_request(data)
    settings["solveQualityTierExplicit"] = _solve_quality_tier_explicit_from_request(data)
    settings["autoFastTierForLightQuestions"] = _auto_fast_tier_from_request(data)
    settings["enableParallelModuleSteps"] = _enable_parallel_steps_from_request(data)


def _llm_settings_from_request(data: dict) -> tuple[dict | None, str | None]:
    settings = resolve_llm_settings(data or {})
    provider = settings.get("provider") or "deepseek"
    settings["model"] = normalize_saved_model(provider, settings.get("model") or "")
    err = llm_settings_error(settings)
    if err:
        return None, err
    return settings, None


from modules.run_code import execute_code, get_java_exe, java_status_info
from modules.solve_lab import solve_lab
from modules.uml import render_uml_diagrams
from agent.document_store import (
    resolve_agent_context,
    resolve_documents,
    store_from_request_payload,
    store_parsed_batch,
)
from agent.executor import retry_single_step, start_run_async
from agent.quality import verify_answer
from agent.understand_plan import understand_and_plan
from modules.revise_answer import revise_answer
from agent.parse_documents import parse_documents_list
from agent.plan_feedback import record_plan_feedback
from agent.planner import (
    apply_question_type_overrides,
    compute_plan_fingerprint,
    make_agent_context,
    plan_from_report,
    replan_with_answers,
    verify_plan_fingerprint,
)
from modules.code_cloze import detect_code_cloze
from agent.sections_config import normalize as normalize_sections_config
from agent.sections_config import parse_section_brief
from agent.run_control import (
    RunBusyError,
    RunQueueFullError,
    cancel_run,
    configure_run_events,
    get_active_run_id,
    get_run,
    get_run_events,
    iter_events,
    map_api_error,
    register_run_starter,
    release_run,
    respond_jar_consent,
    run_exists,
    try_acquire_or_queue,
)
from agent.user_profile import (
    compute_keep_rate_summary,
    load_profile,
    merge_profile,
    normalize_profile,
    record_behavior_outcome,
    record_revise_tags,
    save_profile,
)
from agent.template_analyzer import prepare_format_spec_for_session
from modules.parse_answer_template import parse_answer_template

app = Flask(__name__)


def _normalize_user_constraints_input(data: dict) -> list[str]:
    from modules.user_constraints import normalize_user_constraints

    return normalize_user_constraints(
        data.get("user_constraints") or data.get("userConstraints")
    )


def _auto_remediate_max_rounds_from_request(data: dict) -> int:
    raw = (
        data.get("auto_remediate_max_rounds")
        if "auto_remediate_max_rounds" in data
        else data.get("autoRemediateMaxRounds")
    )
    if raw is None:
        return 1
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(0, min(5, val))


def _max_replan_rounds_from_request(data: dict) -> int:
    raw = (
        data.get("max_replan_rounds")
        if "max_replan_rounds" in data
        else data.get("maxReplanRounds")
    )
    if raw is None:
        return 1
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(0, min(5, val))


def _run_queue_mode_from_request(data: dict) -> str:
    raw = data.get("run_queue_mode") or data.get("runQueueMode")
    if raw is None:
        return str(SETTINGS_DEFAULTS.get("runQueueMode", "reject"))
    mode = str(raw).lower().strip()
    return mode if mode in ("fifo", "reject") else "reject"


def _run_queue_max_depth_from_request(data: dict) -> int:
    raw = data.get("run_queue_max_depth") or data.get("runQueueMaxDepth")
    if raw is None:
        return int(SETTINGS_DEFAULTS.get("runQueueMaxDepth", 1))
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 1


def _configure_run_events_from_request(data: dict) -> None:
    persist = data.get("persist_run_events")
    if persist is None:
        persist = data.get("persistRunEvents")
    if persist is None:
        persist = SETTINGS_DEFAULTS.get("persistRunEvents", True)
    max_files = (
        data.get("run_events_max_files")
        or data.get("runEventsMaxFiles")
        or SETTINGS_DEFAULTS.get("runEventsMaxFiles", 30)
    )
    max_age = (
        data.get("run_events_max_age_days")
        or data.get("runEventsMaxAgeDays")
        or SETTINGS_DEFAULTS.get("runEventsMaxAgeDays", 7)
    )
    configure_run_events(
        persist=bool(persist),
        max_files=int(max_files),
        max_age_days=int(max_age),
    )


def _start_agent_run_from_queue(run_id: str, payload: dict) -> None:
    start_run_async(
        run_id,
        payload["ctx"],
        payload["steps_in"],
        use_fallback=payload.get("use_fallback", True),
        run_mode=payload.get("run_mode", "standard"),
    )


register_run_starter(_start_agent_run_from_queue)
configure_run_events(
    persist=bool(SETTINGS_DEFAULTS.get("persistRunEvents", True)),
    max_files=int(SETTINGS_DEFAULTS.get("runEventsMaxFiles", 30)),
    max_age_days=int(SETTINGS_DEFAULTS.get("runEventsMaxAgeDays", 7)),
)


def _session_format_spec(data: dict, bundle: dict | None = None) -> dict | None:
    """Resolve format_spec from request body or multi-doc parse bundle."""
    raw = data.get("format_spec")
    meta = (bundle or {}).get("metadata") if bundle else None
    assign = (bundle or {}).get("assignment_text") if bundle else ""
    if isinstance(bundle, dict) and bundle.get("planner_input_text"):
        assign = assign or bundle.get("planner_input_text")
    if raw and isinstance(raw, dict):
        return prepare_format_spec_for_session(
            raw,
            assignment_metadata=meta or data.get("metadata"),
            assignment_text=assign or data.get("assignment_text") or "",
        )
    if isinstance(bundle, dict) and bundle.get("format_spec"):
        return bundle["format_spec"]
    return None


def _build_agent_context_snapshot(
    *,
    document_ids: list[str],
    report_text: str,
    planner_input_text: str,
    metadata: dict | None,
    question: dict | None,
    split_idx,
    layout,
    assignment_text: str,
    fill_target,
    fill_target_info,
    format_spec: dict | None,
) -> dict:
    """Portable plan-time context for run-time stale document fallback."""
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "document_ids": [str(x) for x in (document_ids or []) if str(x)],
        "report_text": report_text or "",
        "planner_input_text": planner_input_text or report_text or "",
        "metadata": dict(metadata or {}),
        "question": dict(question or {}),
        "split_idx": split_idx,
        "layout": layout,
        "assignment_text": assignment_text or "",
        "fill_target": fill_target,
        "fill_target_info": fill_target_info,
        "format_spec": format_spec or None,
    }


def _doc_ctx_from_snapshot(snapshot: dict | None) -> dict | None:
    """Best-effort run context reconstruction when document cache is stale."""
    if not isinstance(snapshot, dict):
        return None
    report_text = (snapshot.get("report_text") or "").strip()
    planner_input_text = (snapshot.get("planner_input_text") or report_text).strip()
    if not report_text and not planner_input_text:
        return None
    metadata = snapshot.get("metadata") or {}
    question = snapshot.get("question") or {}
    if not isinstance(metadata, dict) or not isinstance(question, dict):
        return None
    return {
        "document_ids": [str(x) for x in (snapshot.get("document_ids") or []) if str(x)],
        "report_text": report_text or planner_input_text,
        "planner_input_text": planner_input_text or report_text,
        "metadata": dict(metadata),
        "question": dict(question),
        "split_idx": snapshot.get("split_idx"),
        "layout": snapshot.get("layout"),
        "assignment_text": snapshot.get("assignment_text") or "",
        "fill_target": snapshot.get("fill_target"),
        "fill_target_info": snapshot.get("fill_target_info"),
        "format_spec": snapshot.get("format_spec"),
        "warnings": [],
        "needs_uml": bool(snapshot.get("needs_uml")),
    }


def _maybe_save_insight(parsed: dict) -> None:
    """Auto-save LLM self-reported notes to AI_INSIGHTS.md."""
    notes = (parsed or {}).get("notes", "").strip()
    if not notes:
        return
    try:
        insights_path = Path(__file__).resolve().parent.parent.parent / "docs" / "AI_INSIGHTS.md"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = f"\n## {today}\n\n### 自动记录（来自 AI 解题 notes）\n\n{notes}\n"
        with open(insights_path, "a", encoding="utf-8") as f:
            f.write(entry)
        logi("insight", f"已保存 {len(notes)} 字 LLM 自述到 AI_INSIGHTS.md")
    except Exception:
        pass  # 静默失败，不影响主流程


CORS(app)

# ══════════════════════════════════════════════════════
# 健康 & 日志接口
# ══════════════════════════════════════════════════════


@app.route("/api/health")
def health():
    logi("health", "ping")
    return jsonify(
        {
            "status": "ok",
            "docx": DOCX_OK,
            "pil": PIL_OK,
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/profile", methods=["GET"])
def get_profile():
    profile = load_profile()
    return jsonify({"profile": profile, "schema_version": SETTINGS_SCHEMA_VERSION})


@app.route("/api/profile", methods=["PUT"])
def put_profile():
    data = request.json or {}
    body = data.get("profile") if isinstance(data.get("profile"), dict) else data
    if not isinstance(body, dict):
        return jsonify({"error": "需要 profile 对象"}), 400
    saved = save_profile(body)
    return jsonify({"profile": saved, "schema_version": SETTINGS_SCHEMA_VERSION})


@app.route("/api/profile/behavior-outcome", methods=["POST"])
def post_behavior_outcome():
    """Record local C2 outcome event (copy / export / revise) for Keep rate."""
    data = request.json or {}
    event = (data.get("event") or "").strip()
    if not event:
        return jsonify({"error": "缺少 event"}), 400
    profile = merge_profile(load_profile(), data.get("profile"))
    updated = record_behavior_outcome(
        profile,
        event,
        section=(data.get("section") or "").strip(),
        run_id=(data.get("run_id") or data.get("runId") or "").strip(),
        format=(data.get("format") or "").strip(),
    )
    saved = save_profile(updated)
    summary = compute_keep_rate_summary(saved)
    return jsonify(
        {
            "ok": True,
            "profile": saved,
            "keep_rate": summary,
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/agent/run-metrics", methods=["GET"])
def get_agent_run_metrics():
    from agent.run_metrics import aggregate_run_events

    max_files = request.args.get("max_files", type=int) or 30
    max_age = request.args.get("max_age_days", type=int) or 7
    profile = load_profile()
    return jsonify(
        {
            "run_events": aggregate_run_events(max_files=max_files, max_age_days=max_age),
            "keep_rate": compute_keep_rate_summary(profile),
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/skill-candidates", methods=["GET"])
def get_skill_candidates():
    from agent.skill_store import list_skill_candidates

    status = request.args.get("status") or "pending"
    candidates = list_skill_candidates(status=status if status != "all" else None)
    return jsonify(
        {
            "candidates": candidates,
            "count": len(candidates),
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/skill-candidates/promote", methods=["POST"])
def post_skill_candidate_promote():
    from agent.skill_store import promote_skill_candidate

    data = request.json or {}
    candidate_id = (data.get("id") or data.get("candidate_id") or "").strip()
    if not candidate_id:
        return jsonify({"error": "缺少 id"}), 400
    try:
        result = promote_skill_candidate(
            candidate_id,
            inject=(data.get("inject") or "").strip(),
            description=(data.get("description") or "").strip(),
        )
        return jsonify({**result, "schema_version": SETTINGS_SCHEMA_VERSION})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("skill-candidates/promote", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/template/analyze", methods=["POST"])
def template_analyze():
    data = request.json or {}
    file_data = data.get("file_data") or data.get("template_data")
    if not file_data:
        return jsonify({"error": "缺少 file_data（base64 docx）"}), 400
    file_name = data.get("file_name") or data.get("template_name") or "template.docx"
    template_type = (data.get("template_type") or "user_sample").strip()
    try:
        file_bytes = base64.b64decode(file_data)
        spec = parse_answer_template(
            file_bytes,
            file_name,
            template_type=template_type,
            assignment_metadata=data.get("metadata"),
            assignment_text=data.get("assignment_text") or data.get("report_text") or "",
        )
        return jsonify(
            {
                "format_spec": spec,
                "summary": spec.get("summary", ""),
                "alignment": spec.get("alignment"),
                "schema_version": SETTINGS_SCHEMA_VERSION,
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("template/analyze", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs")
def get_logs():
    n = int(request.args.get("n", 100))
    buf = get_log_buffer()
    from config import LOG_FILE

    return jsonify({"logs": buf[-n:], "log_file": str(LOG_FILE)})


@app.route("/api/runtime-status", methods=["GET"])
def runtime_status():
    from config import OCR_OK, get_all_runtime_status, get_diagram_tools_status, get_ocr_install_guide

    status = get_all_runtime_status()
    diagram_tools = get_diagram_tools_status()
    ocr = get_ocr_install_guide()
    return jsonify({
        "runtimes": status,
        "any_available": status["any_available"],
        "diagram_tools": diagram_tools,
        "plantuml_jar_ok": diagram_tools["plantuml_jar_ok"],
        "java_ok": diagram_tools["java_ok"],
        "graphviz_ok": diagram_tools["graphviz_ok"],
        "ocr_ok": OCR_OK,
        "ocr": ocr,
    })


# ══════════════════════════════════════════════════════
# 报告解析
# ══════════════════════════════════════════════════════


def _parse_ocr_settings(data: dict) -> dict:
    reading_mode = str(
        data.get("imageReadingMode") or data.get("image_reading_mode") or "ocr_only"
    ).strip().lower()
    if reading_mode not in ("ocr_only", "hybrid", "vision"):
        reading_mode = "ocr_only"
    return {
        "enable_image_ocr": bool(
            data.get("enableImageOcr") or data.get("enable_image_ocr")
        ),
        "ocr_lang": str(data.get("imageOcrLang") or data.get("ocr_lang") or "chi_sim+eng"),
        "ocr_max_pages": int(
            data.get("imageOcrMaxPages") or data.get("ocr_max_pages") or 20
        ),
        "image_reading_mode": reading_mode,
        "vision_max_pages": int(
            data.get("imageVisionMaxPages") or data.get("vision_max_pages") or 5
        ),
        "llm_settings": resolve_llm_settings({
            "api_key": data.get("api_key") or data.get("apiKey") or "",
            "provider": str(data.get("provider") or "deepseek"),
            "model": str(data.get("model") or "deepseek-chat"),
            "custom_url": data.get("customUrl") or data.get("custom_url") or "",
        }),
    }


def _collect_image_assets_from_parsed(parsed: dict) -> tuple[list, dict]:
    all_image_assets: list = []
    all_image_meta: dict = {}
    for d in parsed.get("_bundles") or []:
        imgs = (d.get("metadata") or {}).get("image_assets") or []
        all_image_assets.extend(imgs)
        if d.get("metadata", {}).get("image_bundle_meta"):
            all_image_meta = d["metadata"]["image_bundle_meta"]
    extra = parsed.get("_user_upload_assets") or []
    if extra:
        known = {img.get("sha256") for img in all_image_assets if img.get("sha256")}
        for img in extra:
            sha = img.get("sha256")
            if sha and sha in known:
                continue
            all_image_assets.append(img)
            if sha:
                known.add(sha)
    if all_image_assets:
        for i, img in enumerate(all_image_assets):
            img["id"] = f"img_{i + 1:03d}"
            img["order"] = i
        all_image_meta["deduped"] = len(all_image_assets)
    return all_image_assets, all_image_meta


@app.route("/api/parse-report", methods=["POST"])
def parse_report_route():
    data = request.json or {}
    documents = data.get("documents")
    assignment_images = (
        data.get("assignment_images")
        or data.get("assignmentImages")
        or data.get("user_upload_images")
        or []
    )
    ocr_settings = _parse_ocr_settings(data)

    if documents or assignment_images:
        try:
            if documents:
                parsed = parse_documents_list(
                    documents,
                    assignment_images=assignment_images,
                    **ocr_settings,
                )
            else:
                from agent.parse_documents import parse_assignment_images_only

                parsed = parse_assignment_images_only(
                    assignment_images,
                    **ocr_settings,
                )

            # Store parsed bundles in document_store so subsequent
            # /api/agent/plan and /api/agent/run can resolve via document_ids.
            bundles_to_store = parsed.get("_bundles") or []
            if bundles_to_store:
                stored_ids = store_parsed_batch(bundles_to_store)
                parsed["document_ids"] = stored_ids
                logi("parse", f"cached {len(stored_ids)} document bundle(s) for plan/run")

            # DA4: detect section structure from fill_target docx for UI confirmation
            sections_detected = []
            section_map = {}
            fill_hints = {}
            report_layout = parsed.get("layout") or ""
            table_map = (parsed.get("metadata") or {}).get("table_map") or []
            ft = parsed.get("fill_target") or {}
            ft_path = ft.get("file_path") or ft.get("fill_docx_path") or ""
            ft_fmt = ft.get("source_format") or (
                (parsed.get("metadata") or {}).get("source_format") or ""
            )
            if ft_path and ft_fmt == "docx":
                try:
                    from pathlib import Path as _Path

                    sd = detect_docx_sections(_Path(ft_path))
                    sections_detected = sd.get("sections_detected") or []
                    section_map = sd.get("section_map") or {}
                    fill_hints = sd.get("fill_hints") or {}
                    report_layout = sd.get("report_layout") or report_layout
                    table_map = sd.get("table_map") or table_map
                    logi(
                        "parse",
                        f"multi-doc sections_detected={len(sections_detected)} "
                        f"layout={report_layout}",
                    )
                except Exception as e:
                    logi("parse", f"multi-doc detect_docx_sections skipped: {e}")

            all_image_assets, all_image_meta = _collect_image_assets_from_parsed(parsed)

            return jsonify(
                {
                    "documents": parsed["documents"],
                    "document_ids": parsed["document_ids"],
                    "fill_target": parsed["fill_target"],
                    "fill_target_info": parsed.get("fill_target_info"),
                    "assignment_text": parsed.get("assignment_text", ""),
                    "layout": parsed.get("layout"),
                    "split_idx": parsed.get("split_idx"),
                    "split_at_heading": (parsed.get("fill_target") or {}).get(
                        "split_at_heading"
                    ),
                    "planner_input_preview": (parsed.get("planner_input_text") or "")[:500],
                    "metadata": parsed.get("metadata"),
                    "question": parsed.get("question"),
                    "questions": parsed.get("questions")
                    or ([parsed["question"]] if parsed.get("question") else []),
                    "needs_uml": parsed.get("needs_uml", False),
                    "warnings": parsed.get("warnings") or [],
                    "format_spec": parsed.get("format_spec"),
                    "format_spec_source_id": parsed.get("format_spec_source_id"),
                    "sections_detected": sections_detected,
                    "section_map": section_map,
                    "fill_hints": fill_hints,
                    "report_layout": report_layout,
                    "table_map": table_map,
                    "image_assets": all_image_assets,
                    "image_bundle_meta": all_image_meta,
                    "assignment_from_images": parsed.get("assignment_from_images", False),
                    "image_reading_mode": parsed.get("image_reading_mode") or "",
                    "image_read_summary": parsed.get("image_read_summary"),
                    "image_sections": parsed.get("image_sections") or [],
                    "runtimes_available": _runtimes_available_fields(),
                    "schema_version": SETTINGS_SCHEMA_VERSION,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            loge("parse", traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    file_bytes = base64.b64decode(data.get("file_data", ""))
    file_name = data.get("file_name", "report.docx")

    try:
        tmp = TEMP_DIR / file_name
        tmp.write_bytes(file_bytes)
        logi("parse", f"{file_name} ({len(file_bytes)} bytes)")

        question, metadata, full_text, warnings = build_question_from_document(
            tmp,
            file_name,
            enable_image_ocr=bool(
                data.get("enableImageOcr") or data.get("enable_image_ocr")
            ),
            ocr_lang=str(data.get("imageOcrLang") or data.get("ocr_lang") or "chi_sim+eng"),
            ocr_max_pages=int(
                data.get("imageOcrMaxPages") or data.get("ocr_max_pages") or 20
            ),
        )
        logi(
            "parse",
            f"提取文本 len={len(full_text)} 表格元数据键={list(metadata.keys())} warnings={len(warnings)}",
        )

        # DA4: detect section structure for UI confirmation
        sections_data = {}
        src_fmt = metadata.get("source_format") or document_format(file_name)
        if src_fmt == "docx":
            try:
                sections_data = detect_docx_sections(tmp)
                logi(
                    "parse",
                    f"sections_detected={len(sections_data.get('sections_detected') or [])} "
                    f"layout={sections_data.get('report_layout') or 'default'}",
                )
            except Exception as e:
                logi("parse", f"detect_docx_sections skipped: {e}")

        diagram_needs = (
            detect_needs_uml(full_text, metadata)
            if UML_RENDER_OK
            else {"needs_uml": False, "needs_dfd": False, "kinds": [], "evidence": ""}
        )
        needs_uml = bool(diagram_needs.get("needs_uml"))
        fill_export = {
            "source_format": src_fmt,
            "export_format": "docx",
            "fill_strategy": "generate_docx" if src_fmt == "pdf" else "docx",
            "fill_docx_from": "generated" if src_fmt == "pdf" else "docx",
        }
        if src_fmt == "pdf":
            fill_export["export_message"] = (
                "原版式 PDF 无法直接填回，已按解析出的章节生成 Word 并写入内容"
            )
        return jsonify(
            {
                "questions": [question],
                "total": 1,
                "metadata": metadata,
                "needs_uml": needs_uml,
                "warnings": warnings,
                "fill_target": fill_export,
                "sections_detected": sections_data.get("sections_detected") or [],
                "section_map": sections_data.get("section_map") or {},
                "fill_hints": sections_data.get("fill_hints") or {},
                "report_layout": sections_data.get("report_layout") or metadata.get("report_layout") or "",
                "table_map": sections_data.get("table_map") or metadata.get("table_map") or [],
                "image_assets": question.get("image_assets") or metadata.get("image_assets") or [],
                "image_bundle_meta": question.get("image_bundle_meta") or metadata.get("image_bundle_meta") or {},
                "assignment_text": question.get("assignment_text") or metadata.get("document_assignment_text") or "",
                "assignment_from_images": question.get("assignment_from_images", False),
                "image_reading_mode": question.get("image_reading_mode") or metadata.get("image_reading_mode") or "",
                "image_read_summary": question.get("image_read_summary") or metadata.get("image_read_summary"),
                "image_sections": question.get("image_sections") or metadata.get("image_sections") or [],
                "runtimes_available": _runtimes_available_fields(),
                "schema_version": SETTINGS_SCHEMA_VERSION,
            }
        )
    except Exception as e:
        loge("parse", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


def _runtimes_available_fields():
    from config import get_all_runtime_status
    rt = get_all_runtime_status()
    return {k: rt[k]["available"] for k in ["python", "java", "c", "node"] if rt[k]["available"]}


# ══════════════════════════════════════════════════════
# Agent 计划（Phase 1.3 — 单文档，不接 Electron Step2）
# ══════════════════════════════════════════════════════


@app.route("/api/agent/parse-section-brief", methods=["POST"])
def agent_parse_section_brief():
    data = request.json or {}
    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400
    try:
        result = parse_section_brief(
            data.get("input") or data.get("text") or "",
            settings=settings,
            section_id=data.get("section_id") or "",
        )
        return jsonify({**result, "schema_version": SETTINGS_SCHEMA_VERSION})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("agent/parse-section-brief", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/plan/clarify", methods=["POST"])
def agent_plan_clarify():
    data = request.json or {}
    answers = data.get("clarification_answers") or data.get("answers") or {}
    steps_in = data.get("steps") or (data.get("plan") or {}).get("steps") or []
    document_ids = [str(x) for x in (data.get("document_ids") or [])]
    sections_config = data.get("sections_config")

    try:
        if document_ids:
            doc_ctx = resolve_agent_context(document_ids)
            report_text = doc_ctx["report_text"]
            metadata = doc_ctx["metadata"]
            question = doc_ctx["question"]
            planner_input = doc_ctx["planner_input_text"]
            split_idx = doc_ctx.get("split_idx")
            layout = doc_ctx.get("layout")
        else:
            report_text = (data.get("report_text") or "").strip()
            metadata = data.get("metadata") or {}
            question = data.get("question") or {}
            planner_input = report_text
            split_idx = data.get("split_idx")
            layout = data.get("layout")

        profile = normalize_profile(
            merge_profile(load_profile(), data.get("profile") or data.get("user_profile") or {})
        )
        settings, err = _llm_settings_from_request(data)
        if err:
            return jsonify({"error": err}), 400
        format_spec = _session_format_spec(data)

        ctx = make_agent_context(
            report_text,
            settings,
            profile=profile,
            metadata=metadata,
            question=question,
            plan={"steps": steps_in, "plan_fingerprint": data.get("plan_fingerprint", "")},
            format_spec=format_spec,
        )
        ctx["document_ids"] = document_ids
        if format_spec:
            ctx["format_spec"] = format_spec
        ctx["planner_input_text"] = planner_input
        ctx["split_idx"] = split_idx
        ctx["layout"] = layout
        if sections_config:
            ctx["sections_config"] = sections_config
            norm = normalize_sections_config(sections_config)
            ctx["fill_scope"] = norm["fill_scope"]
            ctx["user_content"] = norm["user_content"]
            ctx["teacher_constraints"] = norm["teacher_constraints"]

        plan = replan_with_answers(ctx, answers, settings=settings)
        return jsonify(
            {
                "steps": plan.get("steps", []),
                "plan_fingerprint": plan.get("plan_fingerprint"),
                "clarifications": plan.get("clarifications", []),
                "decision_log": plan.get("decision_log", []),
                "schema_version": SETTINGS_SCHEMA_VERSION,
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("agent/plan/clarify", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/plan/feedback", methods=["POST"])
def agent_plan_feedback():
    """Record user plan edits (checkbox/order) for history; no profile learning."""
    data = request.json or {}
    baseline = (
        data.get("baseline_steps")
        or data.get("original_steps")
        or (data.get("plan") or {}).get("steps")
        or []
    )
    confirmed = (
        data.get("steps")
        or data.get("confirmed_steps")
        or data.get("user_steps")
        or []
    )
    plan_fingerprint = (data.get("plan_fingerprint") or "").strip()
    document_ids = [str(x) for x in (data.get("document_ids") or [])]

    try:
        apply_to_profile = bool(data.get("apply_to_profile", False))
        profile = normalize_profile(
            merge_profile(load_profile(), data.get("profile") or data.get("user_profile") or {})
        )
        result = record_plan_feedback(
            baseline,
            confirmed,
            plan_fingerprint=plan_fingerprint,
            document_ids=document_ids or None,
            apply_to_profile=apply_to_profile,
            profile=profile,
        )
        return jsonify({**result, "schema_version": SETTINGS_SCHEMA_VERSION})
    except Exception as e:
        loge("agent/plan/feedback", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/plan", methods=["POST"])
def agent_plan():
    data = request.json or {}

    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400

    profile = normalize_profile(
        merge_profile(load_profile(), data.get("profile") or data.get("user_profile") or {})
    )
    run_mode = (data.get("run_mode") or "standard").strip().lower()
    output_mode = (data.get("output_mode") or "deliverable").strip().lower()

    _apply_solve_quality_settings(settings, data)
    settings["run_mode"] = run_mode
    settings["autoRemediateMaxRounds"] = _auto_remediate_max_rounds_from_request(data)
    settings["maxReplanRounds"] = _max_replan_rounds_from_request(data)

    try:
        document_ids, bundle = store_from_request_payload(data)
        format_spec = _session_format_spec(data, bundle if isinstance(bundle, dict) else None)
        sections_config = data.get("sections_config")
        sections_norm = normalize_sections_config(sections_config) if sections_config else None

        if isinstance(bundle, dict) and bundle.get("planner_input_text"):
            report_text = bundle.get("report_text") or ""
            planner_input = bundle["planner_input_text"]
            metadata = dict(bundle.get("metadata") or {})
            question = bundle.get("question") or {}
            warnings = bundle.get("warnings") or []
            split_idx = bundle.get("split_idx")
            layout = bundle.get("layout")
            assignment_text = bundle.get("assignment_text", "")
            fill_target = bundle.get("fill_target")
            documents_summary = bundle.get("documents")
        else:
            report_text = bundle["report_text"]
            planner_input = bundle.get("planner_input_text") or report_text
            metadata = dict(bundle.get("metadata") or {})
            question = bundle.get("question") or {}
            warnings = bundle.get("warnings") or []
            split_idx = bundle.get("split_idx")
            layout = bundle.get("layout")
            assignment_text = bundle.get("assignment_text", "")
            fill_target = None
            documents_summary = None

        override_assignment = (data.get("assignment_text") or "").strip()
        if override_assignment and isinstance(bundle, dict):
            from agent.parse_documents import apply_assignment_text_override

            apply_assignment_text_override(bundle, override_assignment)
            assignment_text = bundle["assignment_text"]
            planner_input = bundle["planner_input_text"]

        metadata["document_ids"] = document_ids
        if isinstance(question, dict) and question.get("type"):
            metadata["question_type"] = question.get("type")
        # Defensive detection: cached question.type can be stale in some
        # parse/reload flows. Re-check assignment/planner text before planning.
        cloze_probe_text = (assignment_text or planner_input or "").strip()
        cloze_probe = detect_code_cloze(cloze_probe_text) if cloze_probe_text else {}
        if not metadata.get("mixed_assignment") and cloze_probe.get("is_code_cloze"):
            question = dict(question or {})
            question["type"] = "code_cloze"
            qmeta = dict(question.get("metadata") or {})
            qmeta["code_cloze"] = cloze_probe
            question["metadata"] = qmeta
            metadata["code_cloze"] = cloze_probe
            metadata["question_type"] = "code_cloze"
        needs_uml = bool(
            data.get("include_uml")
            or data.get("includeUml")
            or bundle.get("needs_uml")
        )
        if sections_norm and sections_norm.get("global", {}).get("include_uml"):
            needs_uml = True
        diagram_needs = (
            detect_needs_uml(planner_input, metadata)
            if UML_RENDER_OK
            else {"needs_uml": False, "needs_dfd": False, "kinds": [], "evidence": ""}
        )
        if not needs_uml:
            needs_uml = bool(diagram_needs.get("needs_uml"))

        if run_mode == "deep":
            understand, plan = understand_and_plan(
                report_text,
                settings=settings,
                profile=profile,
                metadata=metadata,
                planner_input_text=planner_input,
                sections_config=sections_config,
                document_ids=document_ids,
                split_idx=split_idx,
                assignment_text=assignment_text,
                format_spec=format_spec,
            )
        else:
            understand = None
            plan = plan_from_report(
                report_text,
                settings=settings,
                profile=profile,
                metadata=metadata,
                needs_uml=needs_uml,
                diagram_needs=diagram_needs,
                planner_input_text=planner_input,
                sections_config=sections_config,
                document_ids=document_ids,
                split_idx=split_idx,
                format_spec=format_spec,
            )
        plan = apply_question_type_overrides(
            plan,
            metadata=metadata,
            question_type=(question or {}).get("type") or "",
        )
        if metadata.get("mixed_assignment"):
            question = dict(question or {})
            question["type"] = "mixed_assignment"
            metadata["question_type"] = "mixed_assignment"
        steps = plan.get("steps", [])
        # Recompute after question-type overrides (steps may differ from plan_from_report).
        fingerprint = compute_plan_fingerprint(
            planner_input,
            steps,
            document_ids=document_ids,
            sections_config=sections_config,
            split_idx=split_idx,
        )
        plan["plan_fingerprint"] = fingerprint

        ctx = make_agent_context(
            report_text,
            settings,
            profile=profile,
            metadata=metadata,
            question=question,
            plan=plan,
            format_spec=format_spec,
        )
        ctx["document_ids"] = document_ids
        ctx["run_mode"] = run_mode
        ctx["output_mode"] = output_mode
        user_constraints = _normalize_user_constraints_input(data)
        if user_constraints:
            ctx["user_constraints"] = user_constraints
        prov_custom = (data.get("provenance_custom_label") or data.get("provenanceCustomLabel") or "").strip()
        if prov_custom:
            ctx["provenance_custom_label"] = prov_custom
        if format_spec:
            ctx["format_spec"] = format_spec
        if understand:
            ctx["understand"] = understand
        ctx["planner_input_text"] = planner_input
        ctx["split_idx"] = split_idx
        ctx["layout"] = layout
        ctx["assignment_text"] = assignment_text
        if sections_norm:
            ctx["sections_config"] = sections_config
            ctx["fill_scope"] = sections_norm["fill_scope"]
            ctx["user_content"] = sections_norm["user_content"]
            ctx["teacher_constraints"] = sections_norm["teacher_constraints"]

        return jsonify(
            {
                "steps": steps,
                "plan_fingerprint": fingerprint,
                "document_ids": document_ids,
                "clarifications": plan.get("clarifications", []),
                "prompt_version": plan.get("prompt_version", ""),
                "decision_log": plan.get("decision_log", []),
                "run_mode": run_mode,
                "understand": understand,
                "warnings": warnings,
                "layout": layout,
                "split_idx": split_idx,
                "output_mode": output_mode,
                "assignment_text_len": len(assignment_text or ""),
                "documents": documents_summary,
                "fill_target": fill_target,
                "format_spec": format_spec,
                "format_spec_summary": (format_spec or {}).get("summary"),
                "sections_normalized": (
                    {
                        "fill_scope": sections_norm["fill_scope"],
                        "teacher_rules_count": len(
                            (sections_norm.get("teacher_constraints") or {}).get("rules") or []
                        ),
                    }
                    if sections_norm
                    else None
                ),
                "agent_context": {
                    "schema_version": ctx.get("schema_version"),
                    "metadata": ctx.get("metadata"),
                    "prompt_versions": ctx.get("prompt_versions"),
                    "document_ids": document_ids,
                },
                "agent_context_snapshot": _build_agent_context_snapshot(
                    document_ids=document_ids,
                    report_text=report_text,
                    planner_input_text=planner_input,
                    metadata=metadata,
                    question=question,
                    split_idx=split_idx,
                    layout=layout,
                    assignment_text=assignment_text,
                    fill_target=fill_target,
                    fill_target_info=(
                        bundle.get("fill_target_info") if isinstance(bundle, dict) else None
                    ),
                    format_spec=format_spec,
                ),
                "schema_version": SETTINGS_SCHEMA_VERSION,
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("agent/plan", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/run", methods=["POST"])
def agent_run():
    data = request.json or {}
    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400

    run_mode = (data.get("run_mode") or "standard").strip().lower()
    output_mode_run = (data.get("output_mode") or "deliverable").strip().lower()
    plan_fingerprint = (data.get("plan_fingerprint") or "").strip()
    steps_in = data.get("steps") or (data.get("plan") or {}).get("steps") or []
    document_ids = [str(x) for x in (data.get("document_ids") or [])]

    _apply_solve_quality_settings(settings, data)
    settings["run_mode"] = run_mode
    settings["autoRemediateMaxRounds"] = _auto_remediate_max_rounds_from_request(data)
    settings["maxReplanRounds"] = _max_replan_rounds_from_request(data)
    profile = normalize_profile(
        merge_profile(load_profile(), data.get("profile") or data.get("user_profile") or {})
    )

    try:
        snapshot = data.get("agent_context_snapshot") if isinstance(data.get("agent_context_snapshot"), dict) else None
        if not document_ids:
            document_ids, bundle = store_from_request_payload(data)
            doc_ctx = (
                bundle
                if isinstance(bundle, dict) and bundle.get("planner_input_text")
                else {
                    "report_text": bundle.get("report_text"),
                    "metadata": bundle.get("metadata"),
                    "question": bundle.get("question"),
                    "planner_input_text": bundle.get("report_text"),
                    "split_idx": bundle.get("split_idx"),
                }
            )
        else:
            try:
                doc_ctx = resolve_agent_context(document_ids)
            except ValueError as e:
                msg = str(e)
                if "文档缓存已过期或不存在" not in msg:
                    raise
                fallback_ctx = _doc_ctx_from_snapshot(snapshot)
                if not fallback_ctx:
                    raise
                doc_ctx = fallback_ctx
                if not doc_ctx.get("document_ids"):
                    doc_ctx["document_ids"] = list(document_ids)
                logi("agent/run", "document cache stale; fallback to plan snapshot context")
        # Keep run-time planner input aligned with plan-time when user edited
        # assignment preview text; otherwise fingerprint verification may falsely
        # fail with "stale_plan" immediately after regenerate.
        override_assignment = (data.get("assignment_text") or "").strip()
        if override_assignment and isinstance(doc_ctx, dict):
            from agent.parse_documents import apply_assignment_text_override

            apply_assignment_text_override(doc_ctx, override_assignment)

        format_spec = _session_format_spec(data, doc_ctx if isinstance(doc_ctx, dict) else None)

        report_text = doc_ctx["report_text"]
        metadata = dict(doc_ctx.get("metadata") or {})
        question = doc_ctx.get("question") or {}
        if isinstance(question, dict) and question.get("type"):
            metadata["question_type"] = question.get("type")

        for key in (
            "sections_detected",
            "section_map",
            "fill_hints",
            "report_layout",
            "semantic_overrides",
        ):
            val = data.get(key)
            if val:
                metadata[key] = val
        cloze_probe_text = (
            (doc_ctx.get("assignment_text") or "")
            or (doc_ctx.get("planner_input_text") or "")
            or report_text
        )
        cloze_probe = detect_code_cloze(cloze_probe_text or "")
        if not metadata.get("mixed_assignment") and cloze_probe.get("is_code_cloze"):
            question = dict(question or {})
            question["type"] = "code_cloze"
            qmeta = dict(question.get("metadata") or {})
            qmeta["code_cloze"] = cloze_probe
            question["metadata"] = qmeta
            metadata["code_cloze"] = cloze_probe
            metadata["question_type"] = "code_cloze"

        if not steps_in:
            return jsonify({"error": "缺少 steps 或 plan.steps"}), 400

        sections_config = data.get("sections_config") or {}
        sections_norm = normalize_sections_config(sections_config) if sections_config else None

        ctx = make_agent_context(
            report_text,
            settings,
            profile=profile,
            metadata=metadata,
            question=question,
            plan={"steps": steps_in, "plan_fingerprint": plan_fingerprint},
            format_spec=format_spec,
        )
        ctx["document_ids"] = document_ids
        ctx["confirmed_steps"] = steps_in
        if format_spec:
            ctx["format_spec"] = format_spec
        ctx["sections_config"] = sections_config
        ctx["planner_input_text"] = doc_ctx.get("planner_input_text") or report_text
        ctx["split_idx"] = doc_ctx.get("split_idx")
        ctx["layout"] = doc_ctx.get("layout")
        ctx["assignment_text"] = doc_ctx.get("assignment_text", "")
        if doc_ctx.get("fill_target_info"):
            ctx["fill_target_info"] = doc_ctx["fill_target_info"]
        if doc_ctx.get("fill_target"):
            ctx["fill_target"] = doc_ctx["fill_target"]
        if sections_norm:
            ctx["fill_scope"] = sections_norm["fill_scope"]
            ctx["user_content"] = sections_norm["user_content"]
            ctx["teacher_constraints"] = sections_norm["teacher_constraints"]
        ctx["run_mode"] = run_mode
        ctx["output_mode"] = output_mode_run
        from agent.prompts import merge_prompt_versions

        pv_req = data.get("prompt_versions")
        if isinstance(pv_req, dict):
            merge_prompt_versions(ctx, pv_req)
        from modules.user_constraints import normalize_user_constraints

        user_constraints_run = normalize_user_constraints(
            data.get("user_constraints") or data.get("userConstraints")
        )
        if user_constraints_run:
            ctx["user_constraints"] = user_constraints_run
        approved_jar_ids_run = [
            str(i).strip()
            for i in (data.get("approved_jar_ids") or data.get("approvedJarIds") or [])
            if str(i).strip()
        ]
        if approved_jar_ids_run:
            ctx["approved_jar_ids"] = approved_jar_ids_run
        prov_custom_run = (data.get("provenance_custom_label") or data.get("provenanceCustomLabel") or "").strip()
        if prov_custom_run:
            ctx["provenance_custom_label"] = prov_custom_run
        if "auto_remediate" in data:
            ctx["auto_remediate"] = bool(data.get("auto_remediate"))
        else:
            ctx["auto_remediate"] = run_mode in ("standard", "deep")
        ctx["auto_remediate_max_rounds"] = _auto_remediate_max_rounds_from_request(data)
        ctx["max_replan_rounds"] = _max_replan_rounds_from_request(data)
        if "llm_replan" in data:
            ctx["llm_replan"] = bool(data.get("llm_replan"))
        elif "llmReplan" in data:
            ctx["llm_replan"] = bool(data.get("llmReplan"))
        else:
            settings_llm = (ctx.get("settings") or {}).get("llmReplan")
            ctx["llm_replan"] = settings_llm is not False
        if "auto_promote_skills" in data:
            ctx["auto_promote_skills"] = bool(data.get("auto_promote_skills"))
        elif "autoPromoteSkills" in data:
            ctx["auto_promote_skills"] = bool(data.get("autoPromoteSkills"))
        else:
            settings_promote = (ctx.get("settings") or {}).get("autoPromoteSkills")
            ctx["auto_promote_skills"] = settings_promote is not False
        ctx["replan_rounds"] = 0
        ctx["understand"] = data.get("understand") or {}
        if data.get("module_results"):
            ctx["module_results"] = data["module_results"]
        if data.get("dirty_modules") is not None:
            ctx["dirty_modules"] = list(data.get("dirty_modules") or [])
        if data.get("fill_sections"):
            ctx["fill_sections"] = data["fill_sections"]

        ok, expected = verify_plan_fingerprint(ctx, plan_fingerprint, steps_in)
        if plan_fingerprint and not ok:
            return jsonify(
                {
                    "error": "计划已过期，请重新生成计划",
                    "stale_plan": True,
                    "plan_fingerprint": expected,
                }
            ), 409

        use_fallback = bool(data.get("fallback_on_failure", True))
        _configure_run_events_from_request(data)
        queue_mode = _run_queue_mode_from_request(data)
        queue_max_depth = _run_queue_max_depth_from_request(data)
        queue_payload = {
            "ctx": ctx,
            "steps_in": steps_in,
            "use_fallback": use_fallback,
            "run_mode": run_mode,
        }

        try:
            run_id, run_status, queue_position = try_acquire_or_queue(
                data.get("run_id"),
                queue_mode=queue_mode,
                queue_max_depth=queue_max_depth,
                queue_payload=queue_payload,
            )
        except RunBusyError as e:
            return jsonify(
                {
                    "error": str(e),
                    "error_code": "run_busy",
                    "active_run_id": e.active_run_id,
                }
            ), 409
        except RunQueueFullError as e:
            return jsonify(
                {
                    "error": str(e),
                    "error_code": "queue_full",
                    "active_run_id": e.active_run_id,
                }
            ), 409

        if run_status == "running":
            start_run_async(
                run_id,
                ctx,
                steps_in,
                use_fallback=use_fallback,
                run_mode=run_mode,
            )
        body = {
            "run_id": run_id,
            "status": run_status,
            "output_mode": output_mode_run,
            "events_url": f"/api/agent/events?run_id={run_id}",
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
        if run_status == "queued":
            body["queue_position"] = queue_position
        return jsonify(body)
    except ValueError as e:
        msg = str(e)
        body = {"error": msg}
        if "文档缓存已过期或不存在" in msg:
            body["stale_documents"] = True
        return jsonify(body), 400
    except Exception as e:
        loge("agent/run", traceback.format_exc())
        mapped = map_api_error(e)
        return jsonify(mapped), mapped.get("http_status", 500)


@app.route("/api/agent/events")
def agent_events():
    run_id = request.args.get("run_id", "")
    since = int(request.args.get("since") or 0)
    if not run_id or not run_exists(run_id):
        return jsonify({"error": "run_id 无效或已结束"}), 404

    def generate():
        for ev in iter_events(run_id, since=since):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/agent/verify", methods=["POST"])
def agent_verify():
    """Rule-based verification on module_results (Phase 2b B3)."""
    data = request.json or {}
    ctx = data.get("agent_context") or data.get("ctx") or {}
    if not ctx.get("module_results") and data.get("module_results"):
        ctx["module_results"] = data["module_results"]
    if data.get("confirmed_steps"):
        ctx["confirmed_steps"] = data["confirmed_steps"]
    if data.get("steps"):
        ctx["confirmed_steps"] = data["steps"]
    if data.get("answer_template_text"):
        ctx["answer_template_text"] = data["answer_template_text"]
    sections_config = data.get("sections_config")
    if sections_config:
        norm = normalize_sections_config(sections_config)
        ctx["teacher_constraints"] = norm["teacher_constraints"]
        ctx["user_content"] = norm["user_content"]
    try:
        report = verify_answer(ctx, answer_template_text=data.get("answer_template_text") or "")
        return jsonify({"verification_report": report, "schema_version": SETTINGS_SCHEMA_VERSION})
    except Exception as e:
        loge("agent/verify", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/agent/revise", methods=["POST"])
def agent_revise():
    """Scoped revise_answer (Phase 2b B3)."""
    data = request.json or {}
    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400

    parsed = data.get("parsed") or {}
    solve = data.get("solve_data") or {}
    if not parsed and solve:
        parsed = solve.get("parsed") or {}

    scope = data.get("scope") or data.get("sections") or ["full"]
    feedback = data.get("feedback") or data.get("user_feedback") or ""
    if not feedback.strip():
        return jsonify({"error": "请填写修订反馈"}), 400

    profile = normalize_profile(
        merge_profile(load_profile(), data.get("profile") or data.get("user_profile") or {})
    )

    try:
        from agent.executor_dirty import (
            apply_revise_to_module_results,
            mark_dirty_from_revise,
        )

        result = revise_answer(
            settings,
            parsed=parsed,
            report_excerpt=data.get("report_excerpt") or data.get("report_text") or "",
            scope=scope,
            feedback=feedback,
            verification_report=data.get("verification_report"),
            format_spec=data.get("format_spec"),
        )
        merged = result.get("parsed") or parsed
        changed = result.get("changed_fields") or []
        if solve:
            solve = {
                **solve,
                "parsed": merged,
                "code": merged.get("code") or solve.get("code"),
                "language": merged.get("language") or solve.get("language"),
                "type": solve.get("type") or "lab_report",
            }
        else:
            solve = {
                "type": "lab_report",
                "parsed": merged,
                "code": merged.get("code") or "",
                "language": merged.get("language") or "java",
            }

        ctx = data.get("agent_context") or data.get("ctx") or {}
        if data.get("module_results"):
            ctx["module_results"] = data["module_results"]
        ctx.setdefault("module_results", {})
        apply_revise_to_module_results(ctx, solve, changed_fields=changed)
        dirty_modules = mark_dirty_from_revise(
            ctx, changed_fields=changed, scope=scope
        )
        fill_sections = ctx.get("fill_sections")

        if profile.get("optimize_plan_from_usage"):
            tags = [str(s) for s in (scope if isinstance(scope, list) else [scope]) if s]
            if feedback.strip():
                tags.append("feedback")
            updated = record_revise_tags(profile, tags)
            save_profile(updated)

        return jsonify(
            {
                "parsed": merged,
                "solve_data": solve,
                "changed_fields": changed,
                "dirty_modules": dirty_modules,
                "fill_sections": fill_sections,
                "module_results": {
                    "solve_lab": ctx["module_results"].get("solve_lab"),
                },
                "schema_version": SETTINGS_SCHEMA_VERSION,
            }
        )
    except Exception as e:
        loge("agent/revise", traceback.format_exc())
        mapped = map_api_error(e)
        return jsonify(mapped), mapped.get("http_status", 500)


@app.route("/api/agent/active-run")
def agent_active_run():
    """Return in-flight run_id when UI lost local state after refresh (RL10)."""
    run_id = get_active_run_id()
    if not run_id:
        return jsonify({"error": "无执行中任务"}), 404
    return jsonify(
        {
            "run_id": run_id,
            "status": "running",
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/agent/run-status")
def agent_run_status():
    """Poll run progress / replay SSE events after disconnect (RL10)."""
    run_id = request.args.get("run_id", "")
    since = int(request.args.get("since") or 0)
    if not run_id:
        return jsonify({"error": "缺少 run_id"}), 400
    status, events = get_run_events(run_id, since=since)
    if status == "missing":
        return jsonify({"error": "run_id 无效或已结束"}), 404
    return jsonify(
        {
            "run_id": run_id,
            "status": status,
            "events": events,
            "since": since,
            "schema_version": SETTINGS_SCHEMA_VERSION,
        }
    )


@app.route("/api/agent/jar-consent", methods=["POST"])
def agent_jar_consent():
    """Resume solve_lab sandbox after user approves curated jar download (RL8)."""
    data = request.json or {}
    run_id = (data.get("run_id") or "").strip()
    if not run_id:
        return jsonify({"error": "缺少 run_id"}), 400
    approved = bool(data.get("approved"))
    jar_ids = [
        str(i).strip()
        for i in (data.get("jar_ids") or data.get("approved_jar_ids") or [])
        if str(i).strip()
    ]
    if not respond_jar_consent(run_id, approved, jar_ids or None):
        return jsonify({"error": "run_id 无效或不在等待 jar 确认"}), 404
    return jsonify({"success": True, "run_id": run_id, "approved": approved})


@app.route("/api/agent/cancel", methods=["POST"])
def agent_cancel():
    data = request.json or {}
    run_id = data.get("run_id", "")
    if not run_id:
        return jsonify({"error": "缺少 run_id"}), 400
    if cancel_run(run_id):
        release_run(run_id, "cancelled")
        return jsonify({"success": True, "run_id": run_id, "status": "cancelled"})
    return jsonify({"error": "run_id 不存在或已结束"}), 404


@app.route("/api/agent/retry-step", methods=["POST"])
def agent_retry_step():
    data = request.json or {}
    run_id = data.get("run_id", "")
    module_id = data.get("module_id") or data.get("module", "")
    if not run_id or not module_id:
        return jsonify({"error": "缺少 run_id 或 module_id"}), 400

    state = get_run(run_id)
    if not state:
        return jsonify({"error": "run_id 不存在"}), 404

    ctx = data.get("agent_context") or data.get("ctx") or {}
    if not ctx.get("settings"):
        resolved, err = _llm_settings_from_request(data)
        if err:
            return jsonify({"error": err}), 400
        ctx["settings"] = resolved
    ctx["run_id"] = run_id
    ctx["confirmed_steps"] = data.get("steps") or ctx.get("confirmed_steps") or []

    try:
        retry_single_step(run_id, ctx, module_id)
        return jsonify({"success": True, "run_id": run_id, "module_id": module_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        mapped = map_api_error(e)
        return jsonify(mapped), mapped.get("http_status", 500)


# ══════════════════════════════════════════════════════
# AI 解题
# ══════════════════════════════════════════════════════


def _solve_text_cloze_or_lab(
    *,
    settings: dict,
    text: str,
    question: dict | None = None,
    preferred_lang: str = "",
    include_uml: bool = False,
    format_spec=None,
    user_constraints=None,
    approved_jar_ids=None,
) -> dict:
    """Shared detect_code_cloze → call_ai(code_cloze) or solve_lab (R2/R3)."""
    cloze_probe = detect_code_cloze(text) if text else {}
    lang = preferred_lang or cloze_probe.get("language_hint") or ""

    if cloze_probe.get("is_code_cloze"):
        cloze_question = {
            "type": "code_cloze",
            "full_text": text,
            "content": text,
            "preferred_lang": lang or "java",
            "metadata": {"code_cloze": cloze_probe},
        }
        result = call_ai(
            settings["api_key"],
            settings["provider"],
            settings["model"],
            cloze_question,
            custom_url=settings.get("custom_url") or "",
        )
        parsed = result.get("parsed") or {}
        return {
            "type": "code_cloze",
            "answer": result.get("answer", ""),
            "parsed": parsed,
            "blanks": parsed.get("blanks") or {},
            "completed_code": parsed.get("completed_code") or "",
            "pattern_note": parsed.get("pattern_note") or "",
            "language": parsed.get("language") or result.get("language") or lang or "java",
            "code_cloze_detected": cloze_probe,
        }

    q = dict(question or {})
    q.setdefault("type", "lab_report")
    if text:
        q.setdefault("full_text", text)
        q.setdefault("content", text)
    if lang:
        q.setdefault("preferred_lang", lang)
    result = solve_lab(
        settings["api_key"],
        settings["provider"],
        settings["model"],
        q,
        custom_url=settings.get("custom_url") or "",
        include_uml=include_uml,
        format_spec=format_spec,
        settings=settings,
        user_constraints=user_constraints,
        approved_jar_ids=approved_jar_ids or None,
    )
    out = dict(result)
    out["type"] = "lab_report"
    return out


@app.route("/api/solve", methods=["POST"])
def solve():
    data = request.json
    question = data.get("question", {})
    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400

    provider = settings["provider"]
    model = settings["model"]
    code_language = data.get("code_language", "")
    include_code = data.get("include_code", True)
    include_uml = data.get("include_uml", False)

    if code_language:
        question = {**question, "preferred_lang": code_language}

    format_spec = _session_format_spec(data)
    text = (
        (question.get("full_text") or question.get("content") or "")
        or (data.get("text") or data.get("full_text") or "")
    ).strip()

    try:
        logi(
            "ai",
            f'解题 type={question.get("type")} provider={provider} model={model} lang={code_language}',
        )
        result = _solve_text_cloze_or_lab(
            settings=settings,
            text=text,
            question=question,
            preferred_lang=code_language or question.get("preferred_lang") or "",
            include_uml=include_uml,
            format_spec=format_spec,
        )
        if result.get("type") != "code_cloze":
            result["include_code"] = include_code
            result["include_uml"] = include_uml
        _maybe_save_insight(result.get("parsed", {}))
        logi(
            "ai",
            f'解题成功 type={result.get("type")} answer_len={len(result.get("answer", ""))}',
        )
        return jsonify(result)
    except Exception as e:
        loge("ai", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/render-uml", methods=["POST"])
def render_uml_api():
    if not UML_RENDER_OK:
        return jsonify({"error": "uml_render 模块不可用"}), 500
    data = request.json or {}
    diagrams = data.get("diagrams") or []
    if not diagrams and data.get("plantuml"):
        diagrams = [{"title": data.get("title", "UML"), "plantuml": data["plantuml"]}]
    allow_online = data.get("allow_online", True)
    try:
        out = render_uml_diagrams(
            diagrams,
            allow_online=allow_online,
            code=data.get("code") or "",
            language=data.get("language") or "java",
        )
        logi(
            "uml",
            f'渲染 {len(out["images_b64"])}/{len(diagrams)} 张, errors={len(out["errors"])}',
        )
        return jsonify(out)
    except Exception as e:
        loge("uml", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 代码执行
# ══════════════════════════════════════════════════════


@app.route("/api/java-status")
def java_status():
    return jsonify(java_status_info())


@app.route("/api/java-jars", methods=["GET"])
def java_jars_list():
    from modules.java_jars import list_curated_jars_status

    return jsonify({"jars": list_curated_jars_status(), "sandbox_only": True})


@app.route("/api/java-jars/download", methods=["POST"])
def java_jars_download():
    from modules.java_jars import CURATED_JAR_CATALOG, download_curated_jar, invalidate_java_env_cache

    data = request.json or {}
    raw_ids = data.get("ids") or data.get("jar_ids") or []
    if data.get("id"):
        raw_ids = list(raw_ids) + [data["id"]]
    ids = [str(i).strip() for i in raw_ids if str(i).strip()]
    if not ids:
        return jsonify({"error": "缺少 ids"}), 400
    unknown = [i for i in ids if i not in CURATED_JAR_CATALOG]
    if unknown:
        return jsonify({"error": f"未知 jar: {', '.join(unknown)}"}), 400
    try:
        installed = []
        for jar_id in ids:
            path = download_curated_jar(jar_id)
            installed.append({"id": jar_id, "path": str(path)})
        invalidate_java_env_cache()
        return jsonify({"success": True, "installed": installed, "sandbox_only": True})
    except Exception as e:
        loge("java_jars", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/download-jre", methods=["POST"])
def download_jre():
    JRE_URL = (
        "https://github.com/adoptium/temurin21-binaries/releases/download/"
        "jdk-21.0.3%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.3_9.zip"
    )
    zip_path = APP_DATA / "jre_download.zip"
    try:
        logi("jre", "开始下载JRE...")
        urllib.request.urlretrieve(JRE_URL, str(zip_path))
        logi("jre", "解压中...")
        JRE_DIR.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(zip_path), "r") as z:
            z.extractall(str(JRE_DIR))
        zip_path.unlink(missing_ok=True)
        java = get_java_exe()
        logi("jre", f"安装完成: {java}")
        if java:
            return jsonify({"success": True, "java_path": java})
        return jsonify({"success": False, "error": "解压后未找到java.exe"}), 500
    except Exception as e:
        loge("jre", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/run-code-multi", methods=["POST"])
def run_code_multi():
    from modules.preflight import _check_execution_pattern
    from modules.run_code import execute_multi_file

    data = request.json or {}
    files = data.get("files") or []
    language = data.get("language") or "python"
    main_file = data.get("main_file") or ""

    if not files:
        return jsonify({"output": "无文件", "error": True})

    if not main_file:
        main_file = files[0].get("name") or files[0].get("filename") or "main.py"

    # Preflight check on combined code
    combined_code = "\n".join(f.get("code") or f.get("content") or "" for f in files)
    if combined_code.strip():
        exec_check = _check_execution_pattern(combined_code, language)
        if not exec_check.get("ok"):
            logi("run_multi", f"blocked by preflight: pattern={exec_check.get('pattern')}")
            return jsonify({
                "output": exec_check.get("message", "代码无法安全执行"),
                "error": False,
                "blocked_by_preflight": True,
                "preflight_pattern": exec_check.get("pattern"),
                "preflight_message": exec_check.get("message"),
            })

    try:
        logi("run_multi", f"执行 multi lang={language} files={len(files)} main={main_file}")
        output, is_error = execute_multi_file(files, language, main_file)
        logi("run_multi", f"完成 error={is_error} out_len={len(output)}")
        return jsonify({"output": output, "error": is_error})
    except Exception as e:
        loge("run_multi", traceback.format_exc())
        return jsonify({"output": f"[ERR] {e}", "error": True})


@app.route("/api/run-code", methods=["POST"])
def run_code():
    from modules.preflight import _check_execution_pattern

    data = request.json
    code = data.get("code", "")
    language = data.get("language", "python")
    has_gui = data.get("has_gui", False)

    if language == "java" and not get_java_exe():
        return jsonify(
            {
                "output": "",
                "error": False,
                "needs_jre": True,
                "message": "需要下载Java运行环境（约50MB）",
            }
        )

    # P0B: preflight code execution pattern before running
    if code.strip():
        exec_check = _check_execution_pattern(code, language)
        if not exec_check.get("ok"):
            logi("run", f"blocked by preflight: pattern={exec_check.get('pattern')}")
            return jsonify({
                "output": exec_check.get("message", "代码无法安全执行"),
                "error": False,
                "needs_jre": False,
                "blocked_by_preflight": True,
                "preflight_pattern": exec_check.get("pattern"),
                "preflight_message": exec_check.get("message"),
            })

    try:
        logi("run", f"执行 lang={language} len={len(code)} gui={has_gui}")
        output, is_error = execute_code(code, language)
        logi("run", f"完成 error={is_error} out_len={len(output)}")
        return jsonify({"output": output, "error": is_error, "needs_jre": False})
    except Exception as e:
        loge("run", traceback.format_exc())
        return jsonify({"output": f"[ERR] {e}", "error": True, "needs_jre": False})


# ══════════════════════════════════════════════════════
# 答案交付物（V5）
# ══════════════════════════════════════════════════════


@app.route("/api/deliverable/export", methods=["POST"])
def deliverable_export():
    """Export LabDeliverable: markdown / json / docx / code_zip / diagrams_zip."""
    from modules.deliverable import build_deliverable, export_deliverable

    data = request.json or {}
    dlv = data.get("deliverable")
    if not dlv:
        ctx = dict(data.get("agent_context") or {})
        if data.get("module_results"):
            ctx = {**ctx, "module_results": data["module_results"]}
        prov_label = (data.get("provenance_custom_label") or data.get("provenanceCustomLabel") or "").strip()
        if prov_label:
            ctx["provenance_custom_label"] = prov_label
        try:
            dlv = build_deliverable(ctx)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    fmt = (data.get("format") or "markdown").strip().lower()
    include_footer = data.get("include_footer")
    if include_footer is not None and not isinstance(include_footer, bool):
        include_footer = str(include_footer).lower() in ("1", "true", "yes")
    try:
        payload = export_deliverable(dlv, fmt, include_footer=include_footer)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(payload)


# ══════════════════════════════════════════════════════
# 报告填充（高级 / 实验性）
# ══════════════════════════════════════════════════════


@app.route("/api/fill-report", methods=["POST"])
def fill_report():
    from document.pdf_export import prepare_fill_docx_for_fill

    data = request.json
    file_data = data.get("file_data", "")
    file_name = data.get("file_name", "report.docx")
    answers = data.get("answers", [])
    output_path = data.get("output_path", "")

    try:
        tmp_in = None
        if file_data:
            tmp_in = TEMP_DIR / file_name
            tmp_in.write_bytes(base64.b64decode(file_data))

        paired_path = None
        paired_data = data.get("paired_docx_data")
        if paired_data:
            paired_name = data.get("paired_docx_name") or "template.docx"
            paired_path = TEMP_DIR / f"paired_{paired_name}"
            paired_path.write_bytes(base64.b64decode(paired_data))

        source_format = data.get("source_format") or document_format(file_name)
        metadata = data.get("metadata") or {}
        fill_body_text = (
            data.get("fill_body_text")
            or data.get("report_text")
            or (answers[0].get("full_text") if answers else "")
            or ""
        )

        docx_in, fill_target = prepare_fill_docx_for_fill(
            tmp_in,
            file_name,
            source_format=source_format,
            paired_docx_path=paired_path,
            fill_body_text=fill_body_text,
            metadata=metadata,
        )
        out = do_fill(docx_in, answers, output_path, metadata=metadata)
        return jsonify(
            {
                "output_path": str(out),
                "success": True,
                "fill_target": fill_target,
            }
        )
    except Exception as e:
        loge("fill", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 连接测试
# ══════════════════════════════════════════════════════


@app.route("/api/hosted-providers/status", methods=["GET"])
def hosted_providers_status_route():
    return jsonify(hosted_providers_status())


@app.route("/api/llm-models", methods=["GET"])
def llm_models_catalog():
    return jsonify(get_model_catalog())


@app.route("/api/hosted-providers/agnes/seed", methods=["POST"])
def seed_hosted_agnes_key():
    """Persist developer Agnes key for hosted free tier (once)."""
    data = request.json or {}
    api_key = (data.get("api_key") or data.get("apiKey") or "").strip()
    if not api_key:
        return jsonify({"error": "API Key 为空"}), 400
    if is_hosted_configured("agnes"):
        return jsonify({"ok": True, "configured": True, "already_configured": True})
    try:
        save_hosted_api_key("agnes", api_key)
        logi("hosted", "Agnes hosted API key saved")
        return jsonify({"ok": True, "configured": True, "already_configured": False})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        loge("hosted", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    data = request.json
    settings, err = _llm_settings_from_request(data)
    if err:
        return jsonify({"error": err}), 400
    try:
        r = call_ai(
            settings["api_key"],
            settings["provider"],
            settings["model"],
            {"type": "theory", "content": '回复"OK"两个字', "full_text": "回复OK"},
            settings["custom_url"],
        )
        return jsonify(
            {
                "success": True,
                "model": settings["model"],
                "response": r.get("answer", "")[:50],
                "hosted": settings.get("hosted", False),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 工具箱模式 — 独立工具 API（Phase 1）
# ══════════════════════════════════════════════════════


def _tool_ok(data=None, **kwargs):
    """Unified toolbox response: {ok, data, ...extra}."""
    resp = {"ok": True, "data": data}
    resp.update(kwargs)
    return jsonify(resp)


def _tool_err(message: str, status=400):
    return jsonify({"ok": False, "error": str(message)}), status


def _tool_settings(data: dict) -> dict:
    """Extract LLM settings from a toolbox request body."""
    return resolve_llm_settings(data)


# ── 1. 解析文档 ──

@app.route("/api/tool/parse", methods=["POST"])
def tool_parse():
    data = request.json or {}
    file_data = data.get("file_data", "")
    file_name = data.get("file_name", "report.docx")
    if not file_data:
        return _tool_err("缺少 file_data（base64）")
    try:
        file_bytes = base64.b64decode(file_data)
    except Exception:
        return _tool_err("file_data base64 解码失败")
    try:
        tmp = TEMP_DIR / file_name
        tmp.write_bytes(file_bytes)
        question, metadata, full_text, warnings = build_question_from_document(tmp, file_name)
        src_fmt = metadata.get("source_format") or document_format(file_name)

        # Gather tables info
        tables = metadata.get("tables") or question.get("tables") or []

        # Gather image assets
        image_assets = question.get("image_assets") or metadata.get("image_assets") or []

        # Detect sections
        sections_detected = []
        section_map = {}
        if src_fmt == "docx":
            try:
                sd = detect_docx_sections(tmp)
                sections_detected = sd.get("sections_detected") or []
                section_map = sd.get("section_map") or {}
            except Exception:
                pass

        return _tool_ok(
            {
                "full_text": full_text,
                "sections": sections_detected,
                "section_map": section_map,
                "tables": tables,
                "images": image_assets,
                "metadata": metadata,
                "question": question,
                "warnings": warnings,
                "source_format": src_fmt,
                "char_count": len(full_text),
            }
        )
    except Exception as e:
        loge("tool/parse", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 2. AI 解题 ──

@app.route("/api/tool/solve", methods=["POST"])
def tool_solve():
    data = request.json or {}
    text = (data.get("text") or data.get("full_text") or "").strip()
    if not text:
        return _tool_err("缺少 text 或 full_text")
    settings = _tool_settings(data)
    err = llm_settings_error(settings)
    if err:
        return _tool_err(err)
    try:
        from modules.user_constraints import normalize_user_constraints

        preferred_lang = data.get("language") or data.get("code_language") or ""
        include_uml = bool(data.get("include_uml"))
        user_constraints = normalize_user_constraints(
            data.get("user_constraints") or data.get("userConstraints")
        )
        settings["user_constraints"] = user_constraints
        approved_jar_ids = [
            str(i).strip()
            for i in (data.get("approved_jar_ids") or data.get("approvedJarIds") or [])
            if str(i).strip()
        ]
        result = _solve_text_cloze_or_lab(
            settings=settings,
            text=text,
            preferred_lang=preferred_lang,
            include_uml=include_uml,
            format_spec=data.get("format_spec"),
            user_constraints=user_constraints,
            approved_jar_ids=approved_jar_ids or None,
        )
        if result.get("type") == "code_cloze":
            return _tool_ok(result)

        parsed = result.get("parsed") or {}
        payload = {
            "type": "lab_report",
            "answer": result.get("answer", ""),
            "parsed": parsed,
            "code": parsed.get("code") or result.get("code", ""),
            "code_files": parsed.get("code_files") or result.get("code_files", []),
            "main_file": parsed.get("main_file") or result.get("main_file", ""),
            "language": parsed.get("language") or result.get("language", ""),
            "diagrams": parsed.get("diagrams") or [],
            "steps_analysis": parsed.get("steps_analysis", ""),
            "result_description": parsed.get("result_description", ""),
            "summary": parsed.get("summary", ""),
            "tokens": result.get("tokens"),
        }
        if result.get("pipeline_meta"):
            payload["pipeline_meta"] = result["pipeline_meta"]
        if result.get("solve_session"):
            payload["solve_session"] = result["solve_session"]
        return _tool_ok(payload)
    except Exception as e:
        loge("tool/solve", traceback.format_exc())
        return _tool_err(str(e), 500)


@app.route("/api/tool/retry-validation", methods=["POST"])
def tool_retry_validation():
    """Re-run internal validation after user approved curated jar download."""
    data = request.json or {}
    session = data.get("solve_session")
    if not session:
        return _tool_err("缺少 solve_session")
    settings = _tool_settings(data)
    err = llm_settings_error(settings)
    if err:
        return _tool_err(err)
    try:
        from modules.solve_pipeline import retry_pipeline_validation
        from modules.user_constraints import normalize_user_constraints

        user_constraints = normalize_user_constraints(
            data.get("user_constraints") or data.get("userConstraints")
        )
        approved_jar_ids = [
            str(i).strip()
            for i in (data.get("approved_jar_ids") or data.get("approvedJarIds") or [])
            if str(i).strip()
        ]
        question = {
            "type": "lab_report",
            "full_text": (data.get("text") or data.get("full_text") or "").strip(),
            "content": (data.get("text") or data.get("full_text") or "").strip(),
            "preferred_lang": data.get("language") or data.get("code_language") or "",
        }
        result = retry_pipeline_validation(
            settings,
            session,
            question,
            tier=data.get("tier") or "standard",
            approved_jar_ids=approved_jar_ids or None,
        )
        parsed = result.get("parsed") or {}
        payload = {
            "answer": result.get("answer", ""),
            "parsed": parsed,
            "code": parsed.get("code") or result.get("code", ""),
            "code_files": parsed.get("code_files") or result.get("code_files", []),
            "main_file": parsed.get("main_file") or result.get("main_file", ""),
            "language": parsed.get("language") or result.get("language", ""),
            "steps_analysis": parsed.get("steps_analysis", ""),
            "result_description": parsed.get("result_description", ""),
            "summary": parsed.get("summary", ""),
        }
        if result.get("pipeline_meta"):
            payload["pipeline_meta"] = result["pipeline_meta"]
        if result.get("solve_session"):
            payload["solve_session"] = result["solve_session"]
        return _tool_ok(payload)
    except Exception as e:
        loge("tool/retry-validation", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 3. 运行代码 ──

@app.route("/api/tool/run", methods=["POST"])
def tool_run():
    from modules.preflight import _check_execution_pattern

    data = request.json or {}
    code = data.get("code", "")
    language = data.get("language", "python")
    if not code.strip():
        return _tool_err("缺少 code")
    try:
        if code.strip():
            exec_check = _check_execution_pattern(code, language)
            if not exec_check.get("ok"):
                return _tool_ok(
                    {
                        "stdout": exec_check.get("message", "代码无法安全执行"),
                        "stderr": "",
                        "exit_code": 0,
                        "blocked_by_preflight": True,
                        "preflight_pattern": exec_check.get("pattern"),
                    }
                )
        output, is_error = execute_code(code, language)
        return _tool_ok(
            {
                "stdout": output,
                "stderr": output if is_error else "",
                "exit_code": 1 if is_error else 0,
                "is_error": is_error,
            }
        )
    except Exception as e:
        loge("tool/run", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 4. 图表渲染（PlantUML + DFD） ──

def _parse_tool_diagrams(data: dict) -> list | None:
    """Accept diagrams array, dfd_json, plantuml_src, or JSON string input."""
    import json

    diagrams = data.get("diagrams")
    if isinstance(diagrams, str):
        try:
            diagrams = json.loads(diagrams)
        except json.JSONDecodeError:
            diagrams = None
    if isinstance(diagrams, list) and diagrams:
        return diagrams

    raw_input = (data.get("input") or "").strip()
    if raw_input.startswith("[") or raw_input.startswith("{"):
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                if isinstance(parsed.get("diagrams"), list):
                    return parsed["diagrams"]
                if parsed.get("plantuml") or parsed.get("dfd_json") or parsed.get("kind"):
                    return [parsed]
        except json.JSONDecodeError:
            pass

    dfd_json = data.get("dfd_json")
    if dfd_json:
        if isinstance(dfd_json, str):
            try:
                dfd_json = json.loads(dfd_json)
            except json.JSONDecodeError:
                return None
        return [{
            "kind": "dfd",
            "title": data.get("title", "DFD"),
            "source_engine": "graphviz",
            "dfd_json": dfd_json,
        }]

    plantuml_src = data.get("plantuml_src") or data.get("plantuml") or raw_input
    if (plantuml_src or "").strip():
        return [{"title": data.get("title", "UML"), "plantuml": plantuml_src}]
    return None


@app.route("/api/tool/uml", methods=["POST"])
def tool_uml():
    if not UML_RENDER_OK:
        return _tool_err("图表渲染模块不可用", 500)
    data = request.json or {}
    diagrams = _parse_tool_diagrams(data)
    if not diagrams:
        return _tool_err("缺少 diagrams / plantuml_src / dfd_json（可粘贴 #2 的 diagrams JSON 数组）")
    allow_online = data.get("allow_online", True)
    try:
        out = render_uml_diagrams(
            diagrams,
            allow_online=allow_online,
            code=data.get("code") or "",
            language=data.get("language") or "java",
        )
        payload = {
            "images_b64": out.get("images_b64", []),
            "image_b64": out["images_b64"][0] if out.get("images_b64") else None,
            "titles": out.get("titles", []),
            "errors": out.get("errors", []),
            "sources": out.get("sources", []),
            "consistency": out.get("consistency"),
            "kind_stats": out.get("kind_stats", {}),
            "summary": out.get("summary", ""),
            "diagram_count": len(diagrams),
            "validation": out.get("validation"),
            "suggested_actions": out.get("suggested_actions") or [],
            "success": bool(out.get("success")),
        }
        return _tool_ok(payload)
    except Exception as e:
        loge("tool/uml", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 5b. 图表验错 / 修复 ──

@app.route("/api/tool/verify-diagrams", methods=["POST"])
def tool_verify_diagrams():
    from modules.diagram_verify import verify_diagrams

    data = request.json or {}
    answer = data.get("answer_json") or data.get("parsed") or {}
    if isinstance(answer, list):
        answer = answer[0] if answer else {}
    parsed = answer.get("parsed") if isinstance(answer.get("parsed"), dict) else answer
    diagrams = _parse_tool_diagrams(data) or (parsed or {}).get("diagrams")
    if not diagrams:
        return _tool_err("缺少 diagrams 或 answer_json")
    if isinstance(diagrams, list):
        parsed = dict(parsed or {})
        parsed["diagrams"] = diagrams
    solve_data = {
        "parsed": parsed,
        "code": data.get("code") or parsed.get("code") or answer.get("code") or "",
        "language": data.get("language") or parsed.get("language") or "java",
    }
    render_result = data.get("render_result")
    try:
        report = verify_diagrams(
            solve_data,
            render_result=render_result,
            include_consistency=bool(solve_data.get("code")),
        )
        return _tool_ok(report)
    except Exception as e:
        loge("tool/verify-diagrams", traceback.format_exc())
        return _tool_err(str(e), 500)


@app.route("/api/tool/fix-diagrams", methods=["POST"])
def tool_fix_diagrams():
    from modules.fix_diagrams import fix_diagrams

    data = request.json or {}
    answer = data.get("answer_json") or data.get("parsed") or {}
    if isinstance(answer, list):
        answer = answer[0] if answer else {}
    parsed = answer.get("parsed") if isinstance(answer.get("parsed"), dict) else answer
    if not parsed:
        return _tool_err("缺少 answer_json / parsed")
    settings = _tool_settings(data)
    err = llm_settings_error(settings)
    if err:
        return _tool_err(err)
    issues = data.get("issues")
    if issues is None and data.get("render_result"):
        from modules.diagram_verify import verify_diagrams

        vr = verify_diagrams(
            {"parsed": parsed, "code": parsed.get("code") or answer.get("code") or ""},
            render_result=data.get("render_result"),
        )
        issues = vr.get("issues")
    try:
        result = fix_diagrams(
            settings,
            parsed=parsed,
            report_excerpt=data.get("report_excerpt") or data.get("text") or "",
            feedback=data.get("feedback") or "",
            issues=issues,
        )
        merged = dict(answer)
        merged["parsed"] = result.get("parsed") or parsed
        if merged["parsed"].get("diagrams"):
            merged["diagrams"] = merged["parsed"]["diagrams"]
        return _tool_ok(
            {
                "parsed": merged["parsed"],
                "answer_json": merged,
                "changed_fields": result.get("changed_fields") or ["diagrams"],
                "diagrams": merged["parsed"].get("diagrams"),
            }
        )
    except Exception as e:
        loge("tool/fix-diagrams", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 6. 填写报告 ──

@app.route("/api/tool/fill", methods=["POST"])
def tool_fill():
    from document.pdf_export import prepare_fill_docx_for_fill

    data = request.json or {}
    answer_json = data.get("answer_json") or data.get("answers") or []
    file_data = data.get("file_data", "")
    file_name = data.get("file_name", "report.docx")
    if not answer_json:
        return _tool_err("缺少 answer_json")
    if isinstance(answer_json, dict):
        answer_json = [answer_json]
    try:
        tmp_in = None
        if file_data:
            tmp_in = TEMP_DIR / file_name
            tmp_in.write_bytes(base64.b64decode(file_data))

        source_format = data.get("source_format") or document_format(file_name)
        fill_body_text = (
            data.get("fill_body_text")
            or data.get("report_text")
            or (answer_json[0].get("full_text") if answer_json else "")
            or ""
        )
        fill_scope = data.get("fill_scope") or data.get("fill_sections")

        docx_in, fill_target = prepare_fill_docx_for_fill(
            tmp_in,
            file_name,
            source_format=source_format,
            fill_body_text=fill_body_text,
            metadata=data.get("metadata") or {},
        )
        output_path = data.get("output_path", "")
        out_path = do_fill(
            docx_in, answer_json, output_path,
            metadata=data.get("metadata") or {},
            fill_sections=fill_scope,
        )

        # Read back the result
        out_bytes = Path(out_path).read_bytes()
        result_b64 = base64.b64encode(out_bytes).decode()

        return _tool_ok(
            {
                "output_path": str(out_path),
                "file_data": result_b64,
                "file_name": Path(out_path).name,
                "fill_target": fill_target,
            }
        )
    except Exception as e:
        loge("tool/fill", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 7. 修复代码 ──

@app.route("/api/tool/fix", methods=["POST"])
def tool_fix():
    data = request.json or {}
    code = data.get("code", "")
    error_output = data.get("error_output") or data.get("error", "")
    language = data.get("language", "python")
    if not code.strip():
        return _tool_err("缺少 code")
    settings = _tool_settings(data)
    err = llm_settings_error(settings)
    if err:
        return _tool_err(err)
    try:
        result = fix_code_from_error(
            settings,
            code=code,
            language=language,
            error_output=error_output,
            report_excerpt=data.get("report_excerpt", ""),
            category=data.get("category", ""),
            pattern=data.get("pattern", ""),
        )
        return _tool_ok(
            {
                "code": result.get("code", code),
                "code_files": result.get("code_files", []),
                "main_file": result.get("main_file", ""),
                "language": result.get("language", language),
                "parsed": result.get("parsed", {}),
                "category": result.get("category", ""),
            }
        )
    except Exception as e:
        loge("tool/fix", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 8. 校验答案 ──

@app.route("/api/tool/verify", methods=["POST"])
def tool_verify():
    data = request.json or {}
    answer_json = data.get("answer_json") or data.get("parsed") or {}
    if not answer_json:
        return _tool_err("缺少 answer_json")
    try:
        ctx = {
            "module_results": {"solve_lab": {"data": dict(answer_json)}},
            "confirmed_steps": data.get("steps") or [],
        }
        report = verify_answer(
            ctx,
            answer_template_text=data.get("answer_template_text", ""),
        )
        return _tool_ok(
            {
                "passed": report.get("passed", False),
                "checks": report.get("checks", []),
                "suggested_actions": report.get("suggested_actions", []),
            }
        )
    except Exception as e:
        loge("tool/verify", traceback.format_exc())
        return _tool_err(str(e), 500)


# ── 9. 修订答案 ──

@app.route("/api/tool/revise", methods=["POST"])
def tool_revise():
    data = request.json or {}
    answer_json = data.get("answer_json") or data.get("parsed") or {}
    feedback = (data.get("feedback") or "").strip()
    if not answer_json:
        return _tool_err("缺少 answer_json")
    if not feedback:
        return _tool_err("请填写修订反馈")
    settings = _tool_settings(data)
    err = llm_settings_error(settings)
    if err:
        return _tool_err(err)
    try:
        result = revise_answer(
            settings,
            parsed=dict(answer_json),
            report_excerpt=data.get("report_excerpt", ""),
            scope=data.get("scope") or ["full"],
            feedback=feedback,
            verification_report=data.get("verification_report"),
            format_spec=data.get("format_spec"),
        )
        merged = result.get("parsed") or answer_json
        return _tool_ok(
            {
                "parsed": merged,
                "changed_fields": result.get("changed_fields", []),
                "code": merged.get("code", ""),
                "language": merged.get("language", ""),
            }
        )
    except Exception as e:
        loge("tool/revise", traceback.format_exc())
        return _tool_err(str(e), 500)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5199)
    args = parser.parse_args()
    logi("server", f"启动端口={args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
