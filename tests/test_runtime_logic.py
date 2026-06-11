"""Regression tests for RUNTIME_LOGIC_ISSUES.md (RL1, RL2, …)."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.react_loop import run_react_loop

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "renderer" / "app.js"


@pytest.fixture(autouse=True)
def _orchestrator_not_cancelled():
    with patch("agent.orchestrator.is_cancelled", return_value=False):
        yield


class TestRL1SseGracefulClose:
    """RL1 — SSE 正常结束时误报「连接中断」."""

    def test_onerror_skips_toast_when_sse_closing_gracefully(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "agentSseClosingGracefully" in src

        onerror_block = re.search(r"es\.onerror\s*=\s*\(\)\s*=>\s*\{([^}]+)\}", src, re.DOTALL)
        assert onerror_block, "connectAgentSSE must define es.onerror"
        body = onerror_block.group(1)
        assert "agentSseClosingGracefully" in body
        assert "agentRunFinished" in body

    def test_done_and_cancelled_set_graceful_flag_before_async_cleanup(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert re.search(
            r"type === 'cancelled'[\s\S]*?agentSseClosingGracefully\s*=\s*true",
            src,
        )
        assert re.search(
            r"type === 'done'[\s\S]*?agentSseClosingGracefully\s*=\s*true[\s\S]*?applyAgentRunDone",
            src,
        )


class TestRL2ReactFallbackDoneOk:
    """RL2 — ReAct fallback 后 done.ok 未重算."""

    def _make_ctx(self, **overrides):
        ctx = {
            "settings": {
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "report_text": "实验报告全文...",
            "planner_input_text": "【作业要求】\n页面置换算法",
            "question": {"type": "lab_report"},
            "user_profile": {"default_language": "python"},
            "module_results": {},
            "run_id": "test-run",
        }
        ctx.update(overrides)
        return ctx

    @patch("agent.fallback.fallback_to_solve")
    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_fallback_success_sets_done_ok(
        self, mock_cancel, mock_release, mock_emit, mock_chat, mock_fallback
    ):
        mock_cancel.return_value = False
        mock_chat.return_value = {
            "content": "THOUGHT: 完成\nACTION: done",
            "reasoning_content": "",
            "finish_reason": "stop",
        }

        def _fallback(ctx, **kwargs):
            ctx.setdefault("module_results", {})["solve_lab"] = {
                "ok": True,
                "data": {"parsed": {"steps_analysis": "ok"}},
            }

        mock_fallback.side_effect = _fallback

        with patch(
            "agent.orchestrator.RunOrchestrator.run_verify",
            return_value={"passed": False, "checks": []},
        ):
            result = run_react_loop("rl2-fallback", self._make_ctx(), [], use_fallback=True)

        assert result["ok"] is True
        mock_fallback.assert_called_once()
        done_events = []
        for c in mock_emit.call_args_list:
            ev = c.args[1] if len(c.args) > 1 else c.kwargs.get("event")
            if isinstance(ev, dict) and ev.get("type") == "done":
                done_events.append(ev)
        assert done_events
        assert done_events[-1]["ok"] is True

    @patch("agent.fallback.fallback_to_solve")
    @patch("agent.react_loop.chat_messages")
    @patch("agent.react_loop.emit_event")
    @patch("agent.react_loop.release_run")
    @patch("agent.react_loop.is_cancelled")
    def test_no_fallback_still_fails_when_solve_and_verify_fail(
        self, mock_cancel, mock_release, mock_emit, mock_chat, mock_fallback
    ):
        mock_cancel.return_value = False
        mock_chat.return_value = {
            "content": "THOUGHT: 完成\nACTION: done",
            "reasoning_content": "",
            "finish_reason": "stop",
        }

        with patch(
            "agent.orchestrator.RunOrchestrator.run_verify",
            return_value={"passed": False, "checks": []},
        ):
            result = run_react_loop(
                "rl2-no-fallback",
                self._make_ctx(module_results={"solve_lab": {"ok": False}}),
                [],
                use_fallback=False,
            )

        assert result["ok"] is False
        mock_fallback.assert_not_called()


class TestRL3StandardRunDoneOk:
    """RL3 — 标准模式 done.ok 恒为 true."""

    def test_standard_run_ok_helper(self):
        from agent.executor import _standard_run_ok

        assert _standard_run_ok({"module_results": {"solve_lab": {"ok": True}}}) is True
        assert _standard_run_ok({"module_results": {"solve_lab": {"ok": False}}}) is False
        assert _standard_run_ok({"module_results": {"fill_report": {"ok": True}}}) is False

    def _std_ctx(self, **overrides):
        ctx = {
            "run_id": "rl3-std",
            "module_results": {},
            "consecutive_failures": 0,
            "replan_rounds": 0,
            "plan": {"steps": []},
            "decision_log": [],
            "settings": {"api_key": "sk-test"},
            "auto_remediate": False,
            "run_mode": "standard",
        }
        ctx.update(overrides)
        return ctx

    def _run_orchestrator(self, ctx, steps, runners, *, use_fallback=False):
        from agent.executor import _execute_standard_via_orchestrator

        events = []
        with patch("agent.executor.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
            with patch("agent.executor.release_run"):
                with patch("agent.executor.clear_run_temp"):
                    with patch.dict(
                        "agent.executor._MODULE_RUNNERS",
                        runners,
                        clear=False,
                    ):
                        with patch(
                            "agent.orchestrator.RunOrchestrator.run_verify",
                            return_value={"passed": True, "checks": []},
                        ):
                            with patch(
                                "agent.orchestrator.RunOrchestrator.maybe_replan",
                                return_value=False,
                            ):
                                _execute_standard_via_orchestrator(
                                    "rl3-std", ctx, steps, use_fallback=use_fallback
                                )
        done = next(e for e in events if e.get("type") == "done")
        return done

    def test_solve_lab_failure_without_fallback_is_not_ok(self):
        steps = [{"module": "solve_lab", "default_checked": True}]
        done = self._run_orchestrator(
            self._std_ctx(),
            steps,
            {"solve_lab": lambda c, p: {"ok": False, "data": {}}},
            use_fallback=False,
        )
        assert done["ok"] is False

    def test_fill_report_failure_does_not_block_ok_when_solve_succeeded(self):
        steps = [
            {"module": "solve_lab", "default_checked": True},
            {"module": "fill_report", "default_checked": True},
        ]
        done = self._run_orchestrator(
            self._std_ctx(),
            steps,
            {
                "solve_lab": lambda c, p: {"ok": True, "data": {}},
                "fill_report": lambda c, p: {"ok": False, "data": {}},
            },
            use_fallback=False,
        )
        assert done["ok"] is True

    @patch("agent.fallback.fallback_to_solve")
    def test_fallback_success_recalculates_done_ok(self, mock_fallback):
        from agent.executor import _execute_standard_via_orchestrator

        ctx = self._std_ctx(module_results={"solve_lab": {"ok": False, "data": {}}})
        steps = [{"module": "solve_lab", "default_checked": True}]
        events = []

        def _fallback(c, **kwargs):
            c.setdefault("module_results", {})["solve_lab"] = {"ok": True, "data": {}}

        mock_fallback.side_effect = _fallback

        with patch("agent.executor.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
            with patch("agent.executor.release_run"):
                with patch("agent.executor.clear_run_temp"):
                    with patch.dict(
                        "agent.executor._MODULE_RUNNERS",
                        {"solve_lab": lambda c, p: {"ok": False, "data": {}}},
                        clear=False,
                    ):
                        with patch(
                            "agent.orchestrator.RunOrchestrator.run_verify",
                            return_value={"passed": False, "checks": []},
                        ):
                            with patch(
                                "agent.orchestrator.RunOrchestrator.maybe_replan",
                                return_value=False,
                            ):
                                _execute_standard_via_orchestrator(
                                    "rl3-fb", ctx, steps, use_fallback=True
                                )

        done = next(e for e in events if e.get("type") == "done")
        assert done["ok"] is True
        mock_fallback.assert_called_once()


class TestRL4StaleDocumentRetry:
    """RL4 — 执行阶段 document_ids 失效无兜底."""

    def test_agent_run_returns_stale_documents_flag_without_snapshot(self):
        from server import app

        client = app.test_client()
        resp = client.post(
            "/api/agent/run",
            json={
                "api_key": "sk-test",
                "document_ids": ["missing-doc-id"],
                "steps": [{"module": "solve_lab", "default_checked": True}],
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("stale_documents") is True
        assert "文档缓存已过期或不存在" in data.get("error", "")

    def test_agent_run_uses_snapshot_when_documents_stale(self):
        from server import app

        client = app.test_client()
        payload = {
            "api_key": "sk-test",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "run_mode": "standard",
            "document_ids": ["missing-doc-id"],
            "steps": [{"module": "solve_lab", "default_checked": True}],
            "plan_fingerprint": "sha256:dummy",
            "agent_context_snapshot": {
                "report_text": "实验报告正文",
                "planner_input_text": "实验报告正文",
                "metadata": {},
                "question": {"type": "lab_report"},
                "document_ids": ["missing-doc-id"],
            },
        }

        with patch("server.verify_plan_fingerprint", return_value=(True, "sha256:dummy")):
            with patch("server.acquire_run", return_value="rl4-snapshot-run"):
                with patch("server.start_run_async") as mock_start:
                    resp = client.post("/api/agent/run", json=payload)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "running"
        assert data.get("run_id") == "rl4-snapshot-run"
        assert mock_start.called

    def test_post_agent_run_retries_after_stale_documents(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "postAgentRunWithDocRetry" in src
        assert re.search(
            r"buildAgentDocumentPayload\(\{ forceReupload: true \}\)",
            src,
        )
        assert "err.stale_documents" in src
        assert "agent_context_snapshot" in src

    def test_agent_run_sets_auto_remediate_max_rounds(self):
        from server import app

        client = app.test_client()
        payload = {
            "api_key": "sk-test",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "run_mode": "standard",
            "document_ids": ["missing-doc-id"],
            "steps": [{"module": "solve_lab", "default_checked": True}],
            "plan_fingerprint": "sha256:dummy",
            "auto_remediate_max_rounds": 2,
            "agent_context_snapshot": {
                "report_text": "实验报告正文",
                "planner_input_text": "实验报告正文",
                "metadata": {},
                "question": {"type": "lab_report"},
                "document_ids": ["missing-doc-id"],
            },
        }

        with patch("server.verify_plan_fingerprint", return_value=(True, "sha256:dummy")):
            with patch("server.acquire_run", return_value="rl8-remediate-rounds"):
                with patch("server.start_run_async") as mock_start:
                    resp = client.post("/api/agent/run", json=payload)

        assert resp.status_code == 200
        args = mock_start.call_args[0]
        ctx = args[1]
        assert ctx.get("auto_remediate_max_rounds") == 2
        assert (ctx.get("settings") or {}).get("autoRemediateMaxRounds") == 2


class TestIR3FailureThresholdConfig:
    def test_failure_threshold_single_source(self):
        from agent.types import max_consecutive_failures_for_mode
        from agent.planner import MAX_CONSECUTIVE_FAILURES as planner_max
        from agent.react_loop import MAX_CONSECUTIVE_FAILURES as react_max

        assert planner_max == max_consecutive_failures_for_mode("standard")
        assert react_max == max_consecutive_failures_for_mode("react")
        assert max_consecutive_failures_for_mode("deep") == max_consecutive_failures_for_mode(
            "standard"
        )


class TestIR2PlanRunSnapshot:
    """IR-2 — plan→run 文档上下文快照兜底."""

    @patch("server.plan_from_report")
    def test_agent_plan_returns_context_snapshot(self, mock_plan):
        from server import app

        mock_plan.return_value = {
            "steps": [{"module": "solve_lab", "params": {}, "default_checked": True}],
            "clarifications": [],
            "plan_fingerprint": "sha256:plan-fp",
            "decision_log": [],
            "prompt_version": "test",
        }
        client = app.test_client()
        resp = client.post(
            "/api/agent/plan",
            json={
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "report_text": "实验报告正文",
                "question": {"type": "lab_report"},
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        snapshot = data.get("agent_context_snapshot") or {}
        assert snapshot.get("report_text") == "实验报告正文"
        assert snapshot.get("planner_input_text")
        assert data.get("plan_fingerprint") == "sha256:plan-fp"


class TestRL5PipelinePhaseSse:
    """RL5 — V4 pipeline 子阶段进度推送 SSE."""

    def test_solve_lab_on_phase_emits_pipeline_phase_sse(self):
        from agent.executor import _run_solve_lab

        events = []
        ctx = {
            "run_id": "rl5-run",
            "settings": {
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "question": {},
            "user_profile": {"default_language": "python"},
        }

        def _fake_solve(*_a, on_phase=None, **_kw):
            if on_phase:
                on_phase({"phase": "understand_brief", "status": "running", "detail": "读题对齐"})
                on_phase({"phase": "understand_brief", "status": "ok", "detail": ""})
            return {"answer": "ok", "solve_session": {}, "pipeline_meta": {}}

        with patch("agent.executor_solve.solve_lab", side_effect=_fake_solve):
            with patch("agent.executor_solve.emit_event", side_effect=lambda _rid, ev: events.append(ev)):
                _run_solve_lab(ctx, {"language": "python"})

        phase_events = [e for e in events if e.get("type") == "pipeline_phase"]
        assert len(phase_events) >= 2
        assert phase_events[0]["phase"] == "understand_brief"
        assert phase_events[0]["module"] == "solve_lab"
        assert ctx["pipeline_phases"]

    def test_app_js_handles_pipeline_phase(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "PIPELINE_PHASE_LABELS" in src
        assert re.search(
            r"type === 'pipeline_phase'[\s\S]*?PIPELINE_PHASE_LABELS",
            src,
        )


class TestRL6RunCodeDedup:
    """RL6 — V4 内化验证与计划内 run_code 去重."""

    def test_adjust_plan_demotes_run_code_under_v4(self):
        from agent.planner import adjust_plan_for_v4_pipeline

        steps = [
            {"module": "solve_lab", "params": {}, "default_checked": True, "reason": "解题"},
            {"module": "run_code", "params": {}, "default_checked": True, "reason": "验证代码"},
        ]
        adjusted = adjust_plan_for_v4_pipeline(steps, {"solve_pipeline_version": "v4"})
        run_step = next(s for s in adjusted if s["module"] == "run_code")
        assert run_step["default_checked"] is False
        assert "内化验证" in run_step["reason"]

    def test_fallback_plan_run_code_optional_under_v4(self):
        from agent.planner import _fallback_plan

        text = "三、实验步骤\n四、实验结果\n需要编写程序并运行"
        with patch("modules.solve_pipeline.should_use_pipeline", return_value=True):
            with patch("agent.planner._runtime_available_for", return_value=True):
                with patch("config._any_runtime_available", return_value=True):
                    steps = _fallback_plan(text, {"default_language": "python"}, False)
        run_step = next((s for s in steps if s["module"] == "run_code"), None)
        assert run_step is not None
        assert run_step["default_checked"] is False
        assert "内化验证" in run_step["reason"]

    def test_run_code_reuses_verified_solve_session(self):
        from agent.executor import _run_run_code

        ctx = {
            "module_results": {
                "solve_lab": {
                    "ok": True,
                    "data": {
                        "code_files": [{"name": "main.py", "code": "print(1)"}],
                        "main_file": "main.py",
                        "language": "python",
                        "pipeline_meta": {"code_status": "verified"},
                    },
                }
            },
            "solve_session": {
                "code_status": "verified",
                "run_result": {"output": "1\n", "stdout": "1\n"},
                "code_files": [{"name": "main.py", "code": "print(1)"}],
                "main_file": "main.py",
            },
        }
        with patch("modules.run_code.execute_code") as mock_exec:
            result = _run_run_code(ctx, {})
        mock_exec.assert_not_called()
        assert result["ok"] is True
        assert result["data"].get("reused_from_solve_lab") is True

    def test_planner_prompt_mentions_v4_internal_validation(self):
        from agent.prompts import render_plan_prompt

        prompt = render_plan_prompt(
            "实验报告",
            {"default_language": "java"},
            v4_pipeline=True,
        )
        assert "内化沙箱验证" in prompt or "run_code_sandbox" in prompt
        assert "default_checked=false" in prompt or "default_checked" in prompt


class TestRL9ReactDeliverablePrompts:
    """RL9 — ReAct 提示词与 V5 deliverable 定位对齐."""

    def test_run_code_failure_hint_deliverable_mode_no_word_mandate(self):
        from agent.react_loop import run_react_loop

        captured_hints: list[str] = []

        def _capture_chat(_settings, history, **_kw):
            for msg in history:
                if msg.get("role") == "user" and "代码验证已尝试多次" in (msg.get("content") or ""):
                    captured_hints.append(msg["content"])
            # Need 4 failed run_code rounds before escalation hint (MAX_RUN_CODE_FIX_CYCLES).
            fail_rounds = sum(
                1 for m in history if m.get("role") == "assistant" and "run_code" in (m.get("content") or "")
            )
            if fail_rounds < 4:
                return {
                    "content": "THOUGHT: 再试\nACTION: run_code",
                    "reasoning_content": "",
                    "finish_reason": "stop",
                }
            return {
                "content": "THOUGHT: 完成\nACTION: done",
                "reasoning_content": "",
                "finish_reason": "stop",
            }

        ctx = {
            "settings": {
                "api_key": "sk-test",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "report_text": "实验报告",
            "planner_input_text": "实验",
            "question": {"type": "lab_report"},
            "user_profile": {"default_language": "python"},
            "module_results": {},
            "run_id": "rl9-run",
            "output_mode": "deliverable",
        }

        with patch("agent.react_loop.chat_messages", side_effect=_capture_chat):
            with patch("agent.react_loop.emit_event"):
                with patch("agent.react_loop.release_run"):
                    with patch("agent.react_loop.is_cancelled", return_value=False):
                        with patch(
                            "agent.react_tools.execute_tool",
                            return_value={"ok": False, "result_summary": "compile error"},
                        ):
                            with patch(
                                "agent.orchestrator.RunOrchestrator.run_verify",
                                return_value={"passed": False, "checks": []},
                            ):
                                run_react_loop("rl9-run", ctx, [], use_fallback=False)

        assert captured_hints, "expected run_code failure escalation hint"
        hint = captured_hints[-1]
        assert "Word" not in hint
        assert "present_deliverable" in hint

    def test_plan_checklist_deliverable_mode_prefers_present_deliverable(self):
        from agent.react_prompts import build_plan_checklist

        text = build_plan_checklist(
            [{"module": "solve_lab", "default_checked": True}],
            {"output_mode": "deliverable", "module_results": {}},
        )
        assert "present_deliverable" in text
        assert "勿默认 fill_report" in text


class TestRL7ComputeRunOk:
    """RL7 — 三模式共用 compute_run_ok 与 complete_agent_run 收尾."""

    def test_compute_run_ok_matches_solve_modules_only(self):
        from agent.run_result import compute_run_ok

        assert compute_run_ok({"module_results": {"solve_lab": {"ok": True}}}) is True
        assert compute_run_ok({"module_results": {"solve_theory": {"ok": True}}}) is True
        assert compute_run_ok({"module_results": {"fill_report": {"ok": False}}}) is False
        assert compute_run_ok({"module_results": {"solve_lab": {"ok": True}, "fill_report": {"ok": False}}}) is True

    def test_standard_executor_delegates_to_compute_run_ok(self):
        from agent.executor import _standard_run_ok

        assert _standard_run_ok({"module_results": {"solve_lab": {"ok": True}}}) is True

    def test_three_modes_use_complete_agent_run(self):
        for rel in ("executor.py", "deep_pipeline.py", "react_loop.py"):
            src = (ROOT / "src" / "python" / "agent" / rel).read_text(encoding="utf-8")
            assert "complete_agent_run(" in src, rel

    def test_complete_agent_run_orders_fallback_before_verify(self):
        from unittest.mock import MagicMock

        from agent.run_result import complete_agent_run

        ctx = {"module_results": {}, "run_id": "rl7-order"}
        orch = MagicMock()
        call_order: list[str] = []

        def _fallback(*_args, **_kwargs):
            call_order.append("fallback")
            return True, None

        def _verify(**_kwargs):
            call_order.append("verify")
            return {"passed": True, "checks": []}

        orch.run_verify.side_effect = _verify

        with patch("agent.run_result.maybe_fallback_solve", side_effect=_fallback):
            with patch("agent.orchestrator.finalize_run_payload", side_effect=lambda _o, f: f):
                with patch("agent.run_control.release_run"):
                    with patch("agent.document_store.clear_run_temp"):
                        result = complete_agent_run(
                            "rl7-order",
                            ctx,
                            orch,
                            emit=lambda _e: None,
                            use_fallback=True,
                        )
        assert call_order == ["fallback", "verify"]
        assert result.get("fallback") is True

    def test_react_tools_dispatch_via_orchestrator_when_present(self):
        src = (ROOT / "src" / "python" / "agent" / "react_tools.py").read_text(encoding="utf-8")
        assert 'ctx.get("_orchestrator")' in src
        assert "orch.run_module(" in src

    def test_deep_pipeline_tail_always_uses_orchestrator(self):
        src = (ROOT / "src" / "python" / "agent" / "deep_pipeline.py").read_text(encoding="utf-8")
        assert "orchestrator_enabled" not in src
        assert "RunOrchestrator(run_id" in src
        assert "complete_agent_run(" in src


class TestRL8JarConsentMidRun:
    """RL8 — Agent 执行中 JAR 同意."""

    def test_wait_for_jar_consent_emits_sse_and_unblocks(self):
        from agent.run_control import (
            acquire_run,
            get_run_events,
            release_run,
            respond_jar_consent,
            wait_for_jar_consent,
        )

        rid = acquire_run("rl8-jar")
        results: list[bool] = []

        def _worker():
            results.append(
                wait_for_jar_consent(rid, [{"id": "h2", "label": "H2"}])
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        time.sleep(0.05)
        _status, events = get_run_events(rid, 0)
        assert any(e.get("type") == "jar_consent_required" for e in events)
        assert respond_jar_consent(rid, True, ["h2"]) is True
        t.join(timeout=2)
        assert results == [True]
        release_run(rid)

    def test_executor_passes_on_jar_consent_when_allow_curated_jars(self):
        src = (ROOT / "src" / "python" / "agent" / "executor_solve.py").read_text(encoding="utf-8")
        assert "wait_for_jar_consent" in src
        assert "on_jar_consent=on_jar_consent" in src

    def test_app_js_handles_jar_consent_required(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "jar_consent_required" in src
        assert "handleAgentJarConsentRequired" in src
        assert "/api/agent/jar-consent" in src


class TestRL10SseReplay:
    """RL10 — SSE 事件回放与重连."""

    def test_emit_event_appends_event_log(self):
        from agent.run_control import acquire_run, emit_event, get_run_events, release_run

        rid = acquire_run("rl10-log")
        emit_event(rid, {"type": "progress", "module": "solve_lab", "status": "running"})
        emit_event(rid, {"type": "done", "ok": True})
        status, events = get_run_events(rid, since=1)
        assert status == "running"
        assert len(events) == 1
        assert events[0]["type"] == "done"
        release_run(rid)

    def test_iter_events_replays_since_index(self):
        from agent.run_control import acquire_run, emit_event, iter_events, release_run

        rid = acquire_run("rl10-iter")
        emit_event(rid, {"type": "progress", "module": "a", "status": "running"})
        emit_event(rid, {"type": "progress", "module": "b", "status": "running"})
        emit_event(rid, {"type": "done", "ok": True})
        replayed = list(iter_events(rid, since=1))
        types = [e.get("type") for e in replayed]
        assert types == ["progress", "done"]
        release_run(rid)

    def test_connect_agent_sse_supports_since_reconnect(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "agentSseEventIndex" in src
        assert re.search(r"since=\$\{since\}", src)
        assert "正在重连" in src

    def test_get_active_run_id_returns_only_running(self):
        from agent.run_control import (
            acquire_run,
            get_active_run_id,
            release_run,
        )

        rid = acquire_run("rl10-active")
        assert get_active_run_id() == rid
        release_run(rid, "completed")
        assert get_active_run_id() is None

    def test_active_run_api_endpoint(self):
        from agent.run_control import acquire_run, release_run
        from server import app

        client = app.test_client()
        assert client.get("/api/agent/active-run").status_code == 404
        rid = acquire_run("rl10-api-active")
        try:
            resp = client.get("/api/agent/active-run")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["run_id"] == rid
            assert body["status"] == "running"
        finally:
            release_run(rid, "completed")

    def test_refresh_recovery_persists_and_restores_run(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "AGENT_ACTIVE_RUN_KEY" in src
        assert "persistAgentActiveRun" in src
        assert "tryRestoreAgentRunAfterLoad" in src
        assert "clearAgentActiveRun" in src
        assert re.search(
            r"runServerReadyBootstrap\(\)[\s\S]*?tryRestoreAgentRunAfterLoad",
            src,
        )
        assert "finishAgentRunUI" in src
        finish_block = re.search(r"function finishAgentRunUI\([^)]*\)\s*\{([^}]+)\}", src)
        assert finish_block and "clearAgentActiveRun" in finish_block.group(1)


class TestRL11InitServerReady:
    """RL11 — init() 5s 超时与后端就绪竞态."""

    def _init_section(self, src: str) -> str:
        m = re.search(r"async function init\(\)\s*\{", src)
        assert m, "init() must exist"
        start = m.end()
        depth = 1
        i = start
        while i < len(src) and depth > 0:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        return src[start : i - 1]

    def test_server_bootstrap_guarded_and_centralized(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "serverBootstrapDone" in src
        assert "function runServerReadyBootstrap()" in src
        assert re.search(
            r"onServerReady\(\(\)\s*=>\s*\{\s*runServerReadyBootstrap\(\)",
            src,
        )

    def test_five_second_timeout_does_not_call_backend_apis(self):
        src = APP_JS.read_text(encoding="utf-8")
        init_body = self._init_section(src)
        timeout_block = re.search(
            r"setTimeout\(async\s*\(\)\s*=>\s*\{([\s\S]*?)\},\s*5000\)",
            init_body,
        )
        assert timeout_block, "init must keep 5s UI unlock timeout"
        body = timeout_block.group(1)
        assert "fetchLogFilePath" not in body
        assert "runComplianceStartupSequence" not in body
        assert "pollServerHealth" in body

    def test_health_poll_fallback_before_bootstrap(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "async function pollServerHealth" in src
        assert "/api/health" in src
        bootstrap = re.search(
            r"function runServerReadyBootstrap\(\)\s*\{([\s\S]*?)^\}",
            src,
            re.MULTILINE,
        )
        assert bootstrap
        body = bootstrap.group(1)
        assert "fetchLogFilePath" in body
        assert "runComplianceStartupSequence" in body


class TestRL12DeepDoneOk:
    """RL12 — 深度模式 done.ok 与标准模式对齐."""

    def test_deep_pipeline_uses_compute_run_ok_not_verify_veto(self):
        deep_src = (ROOT / "src" / "python" / "agent" / "deep_pipeline.py").read_text(encoding="utf-8")
        run_src = (ROOT / "src" / "python" / "agent" / "run_result.py").read_text(encoding="utf-8")
        assert "complete_agent_run(" in deep_src
        assert '"ok": compute_run_ok(ctx)' in run_src
        assert "report.get(\"passed\"" not in deep_src

    def test_solve_ok_true_even_if_verify_would_fail(self):
        from agent.run_result import compute_run_ok

        ctx = {
            "module_results": {
                "solve_lab": {"ok": True, "data": {}},
            },
            "verification_report": {"passed": False, "checks": [{"id": "x", "passed": False}]},
        }
        assert compute_run_ok(ctx) is True


class TestCodeClozeFallbackGuard:
    def test_maybe_fallback_skips_code_cloze_run(self):
        from agent.run_result import maybe_fallback_solve

        ctx = {
            "question": {"type": "code_cloze"},
            "metadata": {"code_cloze": {"is_code_cloze": True, "blank_count": 4}},
            "confirmed_steps": [
                {"module": "solve_code_cloze", "default_checked": True},
                {"module": "present_deliverable", "default_checked": True},
            ],
            "module_results": {"solve_code_cloze": {"ok": False, "data": {}}},
        }
        with patch("agent.fallback.fallback_to_solve") as mock_fb:
            ran, err = maybe_fallback_solve(ctx, use_fallback=True)
        assert ran is False
        assert err is None
        mock_fb.assert_not_called()


class TestIR16RunEventPersist:
    """IR-16a — run events jsonl + crash replay."""

    @pytest.fixture(autouse=True)
    def _isolated_run_control(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.RUN_EVENTS_DIR", tmp_path / "run_events")
        from agent import run_control as rc

        rc.reset_run_control_for_tests()
        rc.configure_run_events(persist=True, max_files=30, max_age_days=7)
        yield
        rc.reset_run_control_for_tests()

    def test_emit_event_writes_jsonl(self):
        from agent.run_control import acquire_run, emit_event, release_run
        from agent.run_event_store import event_path, read_events

        rid = acquire_run("ir16-persist")
        emit_event(rid, {"type": "progress", "module": "solve_lab", "status": "running"})
        emit_event(rid, {"type": "done", "ok": True})
        release_run(rid)
        assert event_path(rid).is_file()
        events = read_events(rid, 0)
        assert [e["type"] for e in events] == ["progress", "done"]
        assert events[0].get("ts")
        assert events[0].get("seq") == 0

    def test_get_run_events_replays_from_disk_after_memory_cleared(self):
        from agent import run_control as rc
        from agent.run_control import acquire_run, emit_event, get_run_events, release_run

        rid = acquire_run("ir16-replay")
        emit_event(rid, {"type": "progress", "module": "a"})
        emit_event(rid, {"type": "done", "ok": True})
        release_run(rid)
        rc.reset_run_control_for_tests()
        status, events = get_run_events(rid, since=0)
        assert status == "completed"
        assert [e["type"] for e in events] == ["progress", "done"]

    def test_infer_orphaned_when_no_terminal_event(self):
        from agent import run_control as rc
        from agent.run_control import acquire_run, emit_event, get_run_events

        rid = acquire_run("ir16-orphan")
        emit_event(rid, {"type": "progress", "module": "solve_lab"})
        rc.reset_run_control_for_tests()
        status, events = get_run_events(rid, 0)
        assert status == "orphaned"
        assert len(events) == 1

    def test_prune_old_files_respects_max_files(self, tmp_path, monkeypatch):
        from agent.run_event_store import append_event, prune_old_files

        monkeypatch.setattr("config.RUN_EVENTS_DIR", tmp_path / "run_events")
        for i in range(5):
            append_event(f"old-{i}", {"type": "done", "ok": True, "seq": 0})
        removed = prune_old_files(max_files=2, max_age_days=365)
        assert removed == 3
        remaining = list((tmp_path / "run_events").glob("*.jsonl"))
        assert len(remaining) == 2

    def test_executor_thread_named_with_run_id(self):
        src = (ROOT / "src" / "python" / "agent" / "executor.py").read_text(encoding="utf-8")
        assert 'name=f"agent-run-{short_id}"' in src


class TestIR16RunQueue:
    """IR-16b — optional FIFO queue when busy."""

    @pytest.fixture(autouse=True)
    def _isolated_run_control(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.RUN_EVENTS_DIR", tmp_path / "run_events")
        from agent import run_control as rc

        rc.reset_run_control_for_tests()
        rc.configure_run_events(persist=False)
        started: list[str] = []

        def _starter(run_id: str, payload: dict) -> None:
            started.append(run_id)

        rc.register_run_starter(_starter)
        self._started = started
        yield
        rc.reset_run_control_for_tests()

    def test_default_reject_raises_run_busy(self):
        from agent.run_control import RunBusyError, acquire_run, release_run, try_acquire_or_queue

        rid = acquire_run("ir16-busy-a")
        try:
            with pytest.raises(RunBusyError):
                try_acquire_or_queue("ir16-busy-b", queue_mode="reject")
        finally:
            release_run(rid)

    def test_fifo_queues_second_run(self):
        from agent.run_control import (
            acquire_run,
            get_run,
            get_run_events,
            release_run,
            try_acquire_or_queue,
        )

        rid1 = acquire_run("ir16-q1")
        payload = {"ctx": {}, "steps_in": [], "use_fallback": True, "run_mode": "standard"}
        rid2, status, pos = try_acquire_or_queue(
            "ir16-q2",
            queue_mode="fifo",
            queue_payload=payload,
        )
        assert status == "queued"
        assert pos == 1
        assert get_run(rid2)["status"] == "queued"
        _st, events = get_run_events(rid2, 0)
        assert any(e.get("type") == "queued" for e in events)
        release_run(rid1, "completed")
        assert self._started == ["ir16-q2"]
        assert get_run(rid2)["status"] == "running"
        release_run(rid2, "completed")

    def test_queue_full_raises(self):
        from agent import run_control as rc
        from agent.run_control import (
            RunQueueFullError,
            acquire_run,
            release_run,
            try_acquire_or_queue,
        )

        rid1 = acquire_run("ir16-full-1")
        payload = {"ctx": {}, "steps_in": []}
        rid2, status, _ = try_acquire_or_queue(
            "ir16-full-2",
            queue_mode="fifo",
            queue_max_depth=1,
            queue_payload=payload,
        )
        assert status == "queued"
        with pytest.raises(RunQueueFullError):
            try_acquire_or_queue(
                "ir16-full-3",
                queue_mode="fifo",
                queue_max_depth=1,
                queue_payload=payload,
            )
        release_run(rid1)
        assert rc.get_run(rid2)["status"] == "running"
        release_run(rid2)

    def test_cancel_queued_does_not_start_next(self):
        from agent.run_control import (
            acquire_run,
            cancel_run,
            release_run,
            try_acquire_or_queue,
        )

        rid1 = acquire_run("ir16-cancel-1")
        payload = {"ctx": {}, "steps_in": []}
        rid2, status, _ = try_acquire_or_queue(
            "ir16-cancel-2",
            queue_mode="fifo",
            queue_payload=payload,
        )
        assert status == "queued"
        assert cancel_run(rid2) is True
        release_run(rid2, "cancelled")
        assert self._started == []
        release_run(rid1)
