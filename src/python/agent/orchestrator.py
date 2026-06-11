"""
RunOrchestrator — shared module execution, verify, and finalize (V3-2).

Policy layers (standard / deep / react) decide *what* to run; orchestrator decides
*how* to emit progress, record decisions, and invoke registry runners.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.decision_log import append_decision
from agent.executor_dirty import note_module_completed, should_rerun_module
from agent.planner import replan_incremental
from agent.registry import get_runner
from agent.run_control import is_cancelled, map_api_error, pop_retry_module, set_last_error
from agent.types import ModuleResult, PlanStep, max_consecutive_failures_for_mode


@dataclass
class RunStepsOptions:
    """Tuning for standard vs deep-tail step loops."""

    exclude_modules: frozenset[str] = frozenset()
    emit_skipped: bool = True
    enable_reuse: bool = True
    enable_retry_filter: bool = True
    emit_plan_updated: bool = True
    replan_restart_index: bool = True
    note_completion: bool = True
    set_last_error_on_fail: bool = True
    run_code_error_meta: bool = True
    initial_completed: list[str] = field(default_factory=list)
    decision_agent: str = "executor"
    log_step_decisions: bool = True


def _first_pending_index(step_list: list[PlanStep], completed: list[str]) -> int:
    for idx, s in enumerate(step_list):
        mod = s.get("module") or ""
        if mod not in completed:
            return idx
    return len(step_list)


def _build_error_meta(result_data: dict, module: str) -> dict | None:
    if module != "run_code":
        return None
    degraded = result_data.get("degraded") or result_data.get("degraded_reason")
    meta = {
        "degraded": bool(degraded),
        "degraded_reason": result_data.get("degraded_reason", ""),
    }
    if result_data.get("error_category"):
        meta["category"] = result_data["error_category"]
    return meta if (meta["degraded"] or meta.get("category")) else None


class RunOrchestrator:
    def __init__(
        self,
        run_id: str,
        ctx: dict,
        *,
        emit: Callable[[dict], None],
        on_decision: Callable[[dict], None] | None = None,
    ):
        self.run_id = run_id
        self.ctx = ctx
        self.emit = emit
        self.on_decision = on_decision or (lambda _e: None)
        self.completed_modules: list[str] = []
        self.replan_count = 0
        self._llm_calls = 0
        self._auto_remediate_rounds = 0
        self._max_consecutive_failures = max_consecutive_failures_for_mode(
            (self.ctx.get("run_mode") or "standard")
        )

    def auto_remediate_max_rounds(self) -> int:
        """Configurable verify auto-remediate rounds (IR-8)."""
        ctx_val = self.ctx.get("auto_remediate_max_rounds")
        settings_val = (self.ctx.get("settings") or {}).get("autoRemediateMaxRounds")
        raw = ctx_val if ctx_val is not None else settings_val
        try:
            rounds = int(raw)
        except (TypeError, ValueError):
            rounds = 1
        return max(0, min(5, rounds))

    def should_reuse(self, module: str) -> bool:
        """Delegate executor_dirty.should_rerun_module — return True when cache may be reused."""
        return not should_rerun_module(self.ctx, module)

    def run_module(
        self,
        module: str,
        params: dict,
        *,
        step_meta: dict | None = None,
        index: int | None = None,
        emit_running: bool = True,
        decision_agent: str | None = None,
    ) -> ModuleResult:
        """Single module: decision_log, module_results, progress SSE."""
        from agent.executor import _fail_result, run_module as executor_run_module

        agent = decision_agent or "orchestrator"
        step: PlanStep = {"module": module, "params": params or {}}
        if step_meta:
            step.update(step_meta)

        if emit_running:
            progress: dict[str, Any] = {
                "type": "progress",
                "module": module,
                "status": "running",
            }
            if index is not None:
                progress["index"] = index
            self.emit(progress)

        append_decision(
            self.ctx,
            agent=agent,
            decision="run_module",
            target=module,
            reason=(step_meta or {}).get("reason") or "",
            emit=self.on_decision,
        )

        try:
            runner = get_runner(module)
            if runner:
                result = runner(self.ctx, params or {})
            else:
                result = executor_run_module(self.ctx, step)
        except Exception as e:
            mapped = map_api_error(e)
            result = _fail_result(module, mapped["error"], params)
            self.emit({"type": "error", "module": module, **mapped})

        self.ctx.setdefault("module_results", {})[module] = result
        ok = bool(result.get("ok"))

        done_payload: dict[str, Any] = {
            "type": "progress",
            "module": module,
            "status": "done" if ok else "failed",
        }
        if index is not None:
            done_payload["index"] = index

        if ok:
            self.ctx["consecutive_failures"] = 0
            if module not in self.completed_modules:
                self.completed_modules.append(module)
            note_module_completed(self.ctx, module)
            self.emit(done_payload)
        else:
            from agent.executor import module_failure_blocks_pipeline, progress_payload_for_module_result

            result_data = result.get("data") or {}
            err_msg = result_data.get("error", "失败")
            if module_failure_blocks_pipeline(module, result):
                self.ctx["consecutive_failures"] = int(self.ctx.get("consecutive_failures") or 0) + 1
                set_last_error(self.run_id, module, err_msg)
            else:
                self.ctx["consecutive_failures"] = 0
            self.emit(progress_payload_for_module_result(module, result, index=index))

        return result

    def _parallel_steps_enabled(self, opts: RunStepsOptions) -> bool:
        settings = self.ctx.get("settings") or {}
        val = settings.get("enableParallelModuleSteps")
        if val is None:
            val = settings.get("enable_parallel_module_steps")
        if val is None:
            return True
        return bool(val)

    def _run_parallel_batch(
        self,
        batch: list[tuple[int, PlanStep]],
        *,
        opts: RunStepsOptions,
        stop_on_failure: bool,
    ) -> bool:
        """Run a parallel-safe module group. Returns True if run was cancelled."""
        from agent.executor import _fail_result, module_failure_blocks_pipeline, run_module as executor_run_module

        if is_cancelled(self.run_id):
            return True

        append_decision(
            self.ctx,
            agent=opts.decision_agent,
            decision="run_parallel_batch",
            target=",".join((s.get("module") or "") for _, s in batch),
            reason="IR-13b parallel group",
            emit=self.on_decision,
        )

        for index, step in batch:
            module = step.get("module") or ""
            self.emit(
                {
                    "type": "progress",
                    "module": module,
                    "index": index,
                    "status": "running",
                    "parallel": True,
                }
            )
            if opts.log_step_decisions:
                append_decision(
                    self.ctx,
                    agent=opts.decision_agent,
                    decision="run_module",
                    target=module,
                    reason=step.get("reason") or "",
                    emit=self.on_decision,
                )

        results_by_index: dict[int, tuple[str, ModuleResult]] = {}

        def _run_one(index: int, step: PlanStep) -> tuple[int, str, ModuleResult]:
            module = step.get("module") or ""
            if is_cancelled(self.run_id):
                return index, module, _fail_result(module, "已取消", step.get("params"))
            try:
                result = executor_run_module(self.ctx, step)
            except Exception as e:
                mapped = map_api_error(e)
                result = _fail_result(module, mapped["error"], step.get("params"))
            return index, module, result

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(_run_one, idx, step) for idx, step in batch]
            for fut in as_completed(futures):
                if is_cancelled(self.run_id):
                    for pending in futures:
                        pending.cancel()
                    return True
                index, module, result = fut.result()
                results_by_index[index] = (module, result)

        for index, step in sorted(batch, key=lambda x: x[0]):
            module, result = results_by_index[index]
            self.ctx.setdefault("module_results", {})[module] = result
            ok = bool(result.get("ok"))
            if ok:
                self.ctx["consecutive_failures"] = 0
                if module not in self.completed_modules:
                    self.completed_modules.append(module)
                if opts.note_completion:
                    note_module_completed(self.ctx, module)
                self.emit(
                    {
                        "type": "progress",
                        "module": module,
                        "index": index,
                        "status": "done",
                        "parallel": True,
                    }
                )
                continue

            from agent.executor import progress_payload_for_module_result

            result_data = result.get("data") or {}
            err_msg = result_data.get("error", "失败")
            if module_failure_blocks_pipeline(module, result):
                self.ctx["consecutive_failures"] = int(self.ctx.get("consecutive_failures") or 0) + 1
                if opts.set_last_error_on_fail:
                    set_last_error(self.run_id, module, err_msg)
            else:
                self.ctx["consecutive_failures"] = 0
            self.emit(progress_payload_for_module_result(module, result, index=index))

            if stop_on_failure and module_failure_blocks_pipeline(module, result):
                return False

            if self.ctx["consecutive_failures"] >= self._max_consecutive_failures:
                replanned = self.maybe_replan(
                    module,
                    err_msg,
                    emit_plan_updated=opts.emit_plan_updated,
                )
                if replanned:
                    self.ctx["_replan_restart"] = True
                    return False
                self.ctx["consecutive_failures"] = 0

        return False

    def maybe_replan(
        self,
        failed_module: str,
        error_summary: str,
        completed: list[str] | None = None,
        *,
        emit_plan_updated: bool = True,
    ) -> bool:
        """Call replan_incremental; emit plan_updated when rounds increase. Returns True if replanned."""
        rounds_before = int(self.ctx.get("replan_rounds") or 0)
        result_data = ((self.ctx.get("module_results") or {}).get(failed_module) or {}).get("data") or {}
        error_category = str(result_data.get("error_category") or "").strip().lower()
        new_plan = replan_incremental(
            self.ctx,
            {
                "failed_module": failed_module,
                "error_summary": error_summary,
                "error_category": error_category,
                "completed_modules": completed if completed is not None else self.completed_modules,
            },
            emit=self.on_decision,
        )
        if int(self.ctx.get("replan_rounds") or 0) > rounds_before:
            self.replan_count += 1
            if emit_plan_updated:
                self.emit(
                    {
                        "type": "plan_updated",
                        "plan_fingerprint": new_plan.get("plan_fingerprint"),
                        "steps": new_plan.get("steps"),
                    }
                )
            self.ctx["consecutive_failures"] = 0
            return True
        return False

    def run_steps(
        self,
        steps: list[PlanStep],
        *,
        stop_on_failure: bool = False,
        options: RunStepsOptions | None = None,
    ) -> tuple[list[str], bool]:
        """
        Sequential step execution with skip / reuse / replan.

        Returns (completed_modules, cancelled).
        """
        opts = options or RunStepsOptions()
        self.completed_modules = list(opts.initial_completed)
        steps = list(steps)
        i = 0

        while i < len(steps):
            if is_cancelled(self.run_id):
                return self.completed_modules, True

            step = steps[i]
            retry_only = pop_retry_module(self.run_id) if opts.enable_retry_filter else None
            module = step.get("module") or ""

            if module in opts.exclude_modules:
                i += 1
                continue

            if retry_only and module != retry_only:
                i += 1
                continue

            if module in self.completed_modules:
                i += 1
                continue

            if not step.get("default_checked", True):
                if opts.emit_skipped:
                    if opts.log_step_decisions:
                        append_decision(
                            self.ctx,
                            agent=opts.decision_agent,
                            decision="skip_module",
                            target=module,
                            reason="用户未勾选",
                            emit=self.on_decision,
                        )
                    self.emit(
                        {
                            "type": "progress",
                            "module": module,
                            "index": i,
                            "status": "skipped",
                        }
                    )
                i += 1
                continue

            if opts.enable_reuse:
                prior = (self.ctx.get("module_results") or {}).get(module)
                if prior and prior.get("ok") and module == "solve_lab" and self.should_reuse(module):
                    self.completed_modules.append(module)
                    self.emit(
                        {
                            "type": "progress",
                            "module": module,
                            "index": i,
                            "status": "done",
                            "note": "draft 已完成",
                        }
                    )
                    i += 1
                    continue

                if prior and prior.get("ok") and self.should_reuse(module):
                    if opts.log_step_decisions:
                        append_decision(
                            self.ctx,
                            agent=opts.decision_agent,
                            decision="reuse_cache",
                            target=module,
                            reason="子指纹未变 / 非 dirty_modules",
                            fingerprint=(prior.get("fingerprint") or "")[:32],
                            emit=self.on_decision,
                        )
                    self.completed_modules.append(module)
                    self.emit(
                        {
                            "type": "progress",
                            "module": module,
                            "index": i,
                            "status": "done",
                            "note": "复用缓存",
                            "reused": True,
                        }
                    )
                    i += 1
                    continue

            if self._parallel_steps_enabled(opts):
                from agent.parallel_groups import scan_parallel_batch

                batch = scan_parallel_batch(
                    steps,
                    i,
                    completed_modules=set(self.completed_modules),
                    exclude_modules=opts.exclude_modules,
                )
                if batch and len(batch) >= 2:
                    cancelled = self._run_parallel_batch(
                        batch,
                        opts=opts,
                        stop_on_failure=stop_on_failure,
                    )
                    if cancelled:
                        return self.completed_modules, True
                    if self.ctx.pop("_replan_restart", None):
                        steps = list((self.ctx.get("plan") or {}).get("steps") or steps)
                        if opts.exclude_modules:
                            steps = [
                                s
                                for s in steps
                                if (s.get("module") or "") not in opts.exclude_modules
                            ]
                        i = _first_pending_index(steps, self.completed_modules)
                        continue
                    i = batch[-1][0] + 1
                    continue

            self.emit(
                {
                    "type": "progress",
                    "module": module,
                    "index": i,
                    "status": "running",
                }
            )
            if opts.log_step_decisions:
                append_decision(
                    self.ctx,
                    agent=opts.decision_agent,
                    decision="run_module",
                    target=module,
                    reason=step.get("reason") or "",
                    emit=self.on_decision,
                )

            from agent.executor import _fail_result, run_module as executor_run_module

            try:
                result = executor_run_module(self.ctx, step)
            except Exception as e:
                mapped = map_api_error(e)
                result = _fail_result(module, mapped["error"], step.get("params"))
                self.emit({"type": "error", "module": module, **mapped})

            self.ctx.setdefault("module_results", {})[module] = result
            ok = bool(result.get("ok"))

            if ok:
                self.ctx["consecutive_failures"] = 0
                self.completed_modules.append(module)
                if opts.note_completion:
                    note_module_completed(self.ctx, module)
                self.emit(
                    {
                        "type": "progress",
                        "module": module,
                        "index": i,
                        "status": "done",
                    }
                )
                i += 1
                continue

            from agent.executor import module_failure_blocks_pipeline, progress_payload_for_module_result

            result_data = result.get("data") or {}
            err_msg = result_data.get("error", "失败")
            if module_failure_blocks_pipeline(module, result):
                self.ctx["consecutive_failures"] = int(self.ctx.get("consecutive_failures") or 0) + 1
                if opts.set_last_error_on_fail:
                    set_last_error(self.run_id, module, err_msg)
            else:
                self.ctx["consecutive_failures"] = 0
            self.emit(progress_payload_for_module_result(module, result, index=i))

            if stop_on_failure and module_failure_blocks_pipeline(module, result):
                return self.completed_modules, False

            if self.ctx["consecutive_failures"] >= self._max_consecutive_failures:
                replanned = self.maybe_replan(
                    module,
                    err_msg,
                    emit_plan_updated=opts.emit_plan_updated,
                )
                if replanned:
                    steps = list((self.ctx.get("plan") or {}).get("steps") or steps)
                    if opts.exclude_modules:
                        steps = [s for s in steps if (s.get("module") or "") not in opts.exclude_modules]
                    if opts.replan_restart_index:
                        i = _first_pending_index(steps, self.completed_modules)
                        continue
                self.ctx["consecutive_failures"] = 0

            i += 1

        return self.completed_modules, False

    def run_verify(self, *, auto_remediate: bool = False, max_rounds: int | None = None) -> dict:
        """verify_answer → optional auto_remediate: dirty → partial rerun → re-verify."""
        from agent.executor_dirty import mark_dirty_from_verify, modules_to_rerun_from_verify
        from agent.quality import verify_answer

        do_remediate = auto_remediate or bool(self.ctx.get("auto_remediate"))
        max_rounds_effective = self.auto_remediate_max_rounds() if max_rounds is None else max(
            0, min(5, int(max_rounds))
        )
        remediate_rounds = 0

        verification = verify_answer(self.ctx)
        self.ctx["verification_report"] = verification
        self.emit({"type": "verification", **verification})

        while (
            do_remediate
            and remediate_rounds < max_rounds_effective
            and not verification.get("passed")
            and verification.get("suggested_actions")
        ):
            suggested = list(verification.get("suggested_actions") or [])
            suggested = _filter_remediate_actions(suggested, self.ctx)
            rerun_modules = modules_to_rerun_from_verify(suggested, self.ctx)
            if not rerun_modules:
                break

            mark_dirty_from_verify(self.ctx, suggested)
            remediate_rounds += 1

            append_decision(
                self.ctx,
                agent="orchestrator",
                decision="auto_remediate",
                target=",".join(rerun_modules),
                reason=f"verify failed: {', '.join(suggested)}",
                emit=self.on_decision,
            )

            self.completed_modules = [m for m in self.completed_modules if m not in rerun_modules]
            remediate_steps = self._build_remediate_steps(rerun_modules)
            self.run_steps(
                remediate_steps,
                options=RunStepsOptions(
                    enable_reuse=False,
                    emit_plan_updated=False,
                    replan_restart_index=False,
                ),
            )

            verification = verify_answer(self.ctx)
            self.ctx["verification_report"] = verification
            self.emit(
                {
                    "type": "verification",
                    **verification,
                    "remediated": True,
                    "remediate_rounds": remediate_rounds,
                }
            )

        self._auto_remediate_rounds = remediate_rounds
        return verification

    def _build_remediate_steps(self, rerun_modules: list[str]) -> list[PlanStep]:
        """Plan steps for verify remediate — prefer confirmed plan, else synthetic."""
        steps = self.ctx.get("confirmed_steps") or (self.ctx.get("plan") or {}).get("steps") or []
        by_module = {s.get("module"): s for s in steps if s.get("module")}
        out: list[PlanStep] = []
        for mod in rerun_modules:
            if mod in by_module:
                step = dict(by_module[mod])
                step["default_checked"] = True
                out.append(step)
            else:
                out.append({"module": mod, "params": {}, "default_checked": True})
        return out

    def run_finalize(
        self,
        steps: list[PlanStep],
        *,
        max_rounds: int = 12,
        emit_fn: Callable[[dict], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Post-loop finalize: UML / present_deliverable / fill_report (from react_finalize_pipeline)."""
        from agent.react_tools import _format_result_summary, emit_react_cycle
        from log_util import logi

        cycles: list[dict[str, Any]] = []
        mr = self.ctx.get("module_results") or {}
        solve_ok = bool((mr.get("solve_lab") or {}).get("ok")) or bool(
            (mr.get("solve_code_cloze") or {}).get("ok")
        )
        if not solve_ok:
            logi("orchestrator", "finalize skip: no solve result")
            return cycles

        from modules.deliverable import is_content_only_output_mode

        output_mode = self.ctx.get("output_mode", "deliverable")
        content_only = is_content_only_output_mode(output_mode)

        todo: list[tuple[str, str]] = []
        if _should_render_uml(self.ctx):
            todo.append(("render_uml", "补跑 UML 渲染（ReAct 未执行）"))
        if content_only and not _module_done(self.ctx, "present_deliverable"):
            todo.append(("present_deliverable", "汇编答案交付物（ReAct 未执行）"))
        elif not content_only and not _module_done(self.ctx, "fill_report"):
            todo.append(("fill_report", "补跑填表（ReAct 未执行，实验性）"))

        if not todo:
            logi("orchestrator", "finalize nothing pending")
            return cycles

        self.ctx["finalize_ran"] = True
        base_round = max_rounds + 1
        for i, (module, thought) in enumerate(todo):
            round_num = base_round + i
            logi("orchestrator", f"finalize running {module}")
            step: PlanStep = {"module": module, "params": {}, "default_checked": True}
            runner = get_runner(module)
            if runner:
                result = runner(self.ctx, {})
            else:
                from agent.executor import run_module as executor_run_module

                result = executor_run_module(self.ctx, step)
            self.ctx.setdefault("module_results", {})[module] = result
            ok = bool(result.get("ok"))
            summary = _format_result_summary(module, result)
            emit_react_cycle(
                self.run_id, round_num, max_rounds + len(todo), thought, module, ok, summary
            )
            if emit_fn:
                emit_fn(
                    {"type": "react_cycle", "round": round_num, "action": module, "finalize": True}
                )
            cycles.append(
                {
                    "round": round_num,
                    "max_rounds": max_rounds + len(todo),
                    "thought": thought,
                    "action": module,
                    "params": {},
                    "result_ok": ok,
                    "result_summary": summary,
                    "finalize": True,
                }
            )
        return cycles

    def build_run_summary(self) -> dict:
        """Structured run summary for SSE done event (V3-4)."""
        from llm_client import get_llm_call_count, get_llm_calls_by_phase
        from modules.solve_pipeline import pipeline_version, resolve_solve_quality_tier

        fill_mr = (self.ctx.get("module_results") or {}).get("fill_report")
        verification = self.ctx.get("verification_report") or {}
        mode = (self.ctx.get("run_mode") or "standard").lower()
        skills = list(self.ctx.get("skills_fired") or [])
        settings = self.ctx.get("settings") or {}
        pipeline_meta = self.ctx.get("pipeline_meta") or {}
        solve_session = self.ctx.get("solve_session") or {}
        solve_mr = (self.ctx.get("module_results") or {}).get("solve_lab") or {}
        solve_data_meta = ((solve_mr.get("data") or {}).get("pipeline_meta") or {})
        code_status = (
            pipeline_meta.get("code_status")
            or solve_session.get("code_status")
            or solve_data_meta.get("code_status")
        )
        return {
            "mode": mode,
            "solve_quality_tier": resolve_solve_quality_tier(settings, self.ctx),
            "pipeline_version": pipeline_meta.get("version") or pipeline_version(settings),
            "code_status": code_status,
            "llm_calls": get_llm_call_count(),
            "llm_calls_by_phase": get_llm_calls_by_phase(),
            "prompt_versions": dict(self.ctx.get("prompt_versions") or {}),
            "replan_count": self.replan_count,
            "verify_pass": bool(verification.get("passed")),
            "auto_remediate_rounds": self._auto_remediate_rounds,
            "skills_fired": skills,
            "finalize_ran": bool(self.ctx.get("finalize_ran")),
            "output_path": (fill_mr or {}).get("data", {}).get("output_path") if fill_mr else None,
        }


def _filter_remediate_actions(suggested: list[str], ctx: dict) -> list[str]:
    """Drop code-fix actions when V4 pipeline already verified code (AO-5)."""
    from agent.executor_dirty import code_status_from_ctx

    if code_status_from_ctx(ctx) != "verified":
        return suggested
    blocked = {"fix_code", "run_code"}
    out: list[str] = []
    for action in suggested:
        a = (action or "").strip().lower()
        if a in blocked:
            continue
        out.append(action)
    return out


def finalize_run_payload(orch: RunOrchestrator, final: dict) -> dict:
    """Persist learning signals and attach run_summary to done payload."""
    from agent.skill_store import record_skill_candidates_from_run
    from agent.user_profile import persist_run_behavior_from_ctx

    persist_run_behavior_from_ctx(orch.ctx)
    record_skill_candidates_from_run(orch.ctx)
    final["run_summary"] = orch.build_run_summary()
    return final


def _step_checked(step: dict) -> bool:
    return step.get("default_checked", True) is not False


def _module_done(ctx: dict, module: str) -> bool:
    mr = (ctx.get("module_results") or {}).get(module) or {}
    return bool(mr.get("ok"))


def _should_render_uml(ctx: dict) -> bool:
    if _module_done(ctx, "render_uml"):
        return False
    solve = (ctx.get("module_results") or {}).get("solve_lab") or {}
    if not solve.get("ok"):
        return False
    parsed = (solve.get("data") or {}).get("parsed") or {}
    return bool(parsed.get("diagrams"))
