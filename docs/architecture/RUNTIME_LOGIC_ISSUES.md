# 运行逻辑问题清单

**用途**：记录 Agent 端到端运行链路（Electron → Flask → 标准/深度/ReAct）中已识别的逻辑缺口、语义不一致与体验问题。  
**审查日期**：2026-06-06  
**状态**：P0–P3 + RL7 + RL10 + RL11 已修复  
**关联**：[V1_BUGFIX_LOG.md](../logs/V1_BUGFIX_LOG.md)（BF1–BF38，RL → BF28–BF38）· [AGENT_ARCHITECTURE_V3.md](AGENT_ARCHITECTURE_V3.md) · [V5_PRODUCT_PIVOT.md](../product/V5_PRODUCT_PIVOT.md) · [V4_MULTI_PHASE_SOLVE.md](../product/V4_MULTI_PHASE_SOLVE.md)

---

## 运行链路概览

```
用户点击「执行计划」
  → POST /api/agent/run（server.py）
  → start_run_async（executor.py）
       ├─ run_mode=standard → RunOrchestrator.run_steps（或 legacy 回退）
       ├─ run_mode=deep     → deep_pipeline.execute_deep_run
       └─ run_mode=react   → react_loop + react_finalize_pipeline
  → SSE /api/agent/events → app.js handleAgentSSEEvent
  → applyAgentRunDone → 答案工作区 / 历史
```

三种模式共享 `solve_lab`（默认 V4 分阶段 pipeline）。**RL1–RL12 已修复**；RL7 三模式共用 `RunOrchestrator` 收尾（`complete_agent_run`）与 ReAct `run_module` 分发。

---

## 问题总表

| ID | 简述 | 严重度 | 状态 | 优先级 |
|----|------|--------|------|--------|
| RL1 | SSE 正常结束时误报「连接中断」 | 🟠 高（假阳性） | ✅ 已修复 | P0 |
| RL2 | ReAct fallback 后 `done.ok` 未重算 | 🟠 高 | ✅ 已修复 | P0 |
| RL3 | 标准模式 `done.ok` 恒为 `true` | 🟠 高 | ✅ 已修复 | P1 |
| RL4 | 执行阶段 `document_ids` 失效无兜底 | 🟠 高 | ✅ 已修复 | P1 |
| RL5 | V4 pipeline 子阶段进度未推送 SSE | 🟡 中 | ✅ 已修复 | P2 |
| RL6 | V4 内化验证 + 计划内 `run_code` 重复执行 | 🟡 中 | ✅ 已修复 | P2 |
| RL7 | 三种运行模式编排语义分裂 | 🟡 中 | ✅ 已修复 | P3 |
| RL8 | Agent 路径 JAR 同意仅跑完后补救 | 🟡 中 | ✅ 已修复 | P3 |
| RL9 | ReAct 提示词与 V5 deliverable 定位冲突 | 🟡 中 | ✅ 已修复 | P2 |
| RL10 | 单任务锁 + SSE 无重连/回放 | 🟡 中 | ✅ 已修复（回放+重连） | P3 |
| RL11 | 初始化 5s 超时与后端就绪竞态 | 🟢 低 | ✅ 已修复 | backlog |
| RL12 | 深度模式 `done.ok` 过严（verify 一票否决） | 🟢 低 | ✅ 已修复 | P3 |

---

## RL1 — SSE 正常结束时误报「连接中断」 ✅

**严重度**：🟠 高（成功任务也弹错误 Toast）  
**影响**：全部 Agent 模式（标准 / 深度 / ReAct）  
**修复**：2026-06-06 — `done`/`cancelled` 同步设 `agentSseClosingGracefully`，`es.onerror` 跳过 Toast；`tests/test_runtime_logic.py::TestRL1SseGracefulClose`

### 现象

任务正常完成、答案已生成，仍弹出「SSE 连接中断，请查看后端日志」。

### 根因

1. 服务端 `iter_events` 在 `type: done` 后结束流，浏览器 `EventSource` 常触发 `onerror`。
2. `app.js` 的 `es.onerror` 在 `agentRunId` 仍存在时无条件 `showToast(..., 'error')`。
3. `done` 处理为异步：`applyAgentRunDone(...).then(() => finishAgentRunUI())`，`agentRunId` 在 `finishAgentRunUI` 才清空，时序上 `onerror` 可能先于清理执行。

### 涉及文件

| 文件 | 位置 |
|------|------|
| `src/renderer/app.js` | `connectAgentSSE` → `es.onerror` |
| `src/python/agent/run_control.py` | `iter_events` 结束条件 |

### 建议修复

- `done` / `cancelled` 收到后设 `agentRunFinished` 或 `sseClosingGracefully`，`onerror` 内跳过 Toast；
- 或仅在 `onerror` 且未完成、未取消时提示。

### 验收

- 标准 / 深度 / ReAct 跑通后无「SSE 连接中断」Toast；
- 真中断（杀后端）仍应有提示。

---

## RL2 — ReAct fallback 后 `done.ok` 未重算 ✅

**严重度**：🟠 高  
**影响**：ReAct 模式 + `fallback_on_failure: true`（默认）  
**修复**：2026-06-06 — `fallback_to_solve` 后重读 `module_results.solve_lab.ok`；`tests/test_runtime_logic.py::TestRL2ReactFallbackDoneOk`

### 现象

ReAct 主循环 `solve_lab` 失败，收尾 `fallback_to_solve` 成功，前端仍显示「执行未完全成功」。

### 根因

`react_loop.py` 在 fallback **之前**读取 `any_solve`，构建 `final["ok"]` 时未重新检查 `module_results.solve_lab.ok`：

```python
any_solve = (ctx.get("module_results") or {}).get("solve_lab", {}).get("ok")
if not any_solve and use_fallback:
    fallback_to_solve(ctx)  # 会写入 module_results
final = {"ok": bool(any_solve or report.get("passed", False)), ...}  # any_solve 仍为 False
```

### 涉及文件

| 文件 |
|------|
| `src/python/agent/react_loop.py` |

### 建议修复

fallback 后重算：`any_solve = ctx["module_results"]["solve_lab"].get("ok")`，或 `final["ok"]` 直接读最新 `module_results`。

### 验收

- ReAct 仅 fallback 成功时 `done.ok === true`，`finishAgentRunUI(true)`。

---

## RL3 — 标准模式 `done.ok` 恒为 `true` ✅

**严重度**：🟠 高  
**影响**：标准模式（`RunOrchestrator` 路径）  
**修复**：2026-06-06 — `_standard_run_ok(ctx)` 按 `solve_lab`/`solve_theory` 计算 `done.ok`；`tests/test_runtime_logic.py::TestRL3StandardRunDoneOk`

### 现象

`solve_lab` / `run_code` 失败，UI 仍走成功收尾（「全部完成」、成功 Toast），与 ReAct/深度语义不一致。

### 根因

`_execute_standard_via_orchestrator` 与 legacy 路径末尾固定：

```python
emit({"type": "done", "ok": True, **final})
```

未根据 `module_results` 或 `verification_report` 计算成败。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/executor.py` |

### 建议修复

与 `deep_pipeline` / `react_loop` 对齐，例如：

```python
any_solve = any(ctx["module_results"].get(m, {}).get("ok") for m in ("solve_lab", "solve_theory"))
emit({"type": "done", "ok": bool(any_solve), **final})
```

或引入统一的 `compute_run_ok(ctx)` 供三模式共用。

### 验收

- `solve_lab` 失败且无 fallback → `done.ok: false`；
- 部分非阻塞模块失败（如 `fill_report` degraded）→ 仍可为 `true`。

---

## RL4 — 执行阶段 `document_ids` 失效无兜底 ✅

**严重度**：🟠 高  
**影响**：生成计划后隔一段时间再执行、或后端重启后执行  
**修复**：2026-06-06 — `/api/agent/run` 返回 `stale_documents`；前端 `postAgentRunWithDocRetry` 强制重传；`tests/test_runtime_logic.py::TestRL4StaleDocumentRetry`

### 现象

点击「执行计划」报错：`文档缓存已过期或不存在: <uuid>`。

### 根因

1. `document_store._store` 为内存缓存，TTL 1h，后端重启即清空。
2. `buildAgentDocumentPayload()` 有 `document_ids` 时只传 ID，不重传文件。
3. BF1/BF2 修复了 parse → plan 写入；**plan → run 间隔失效**未覆盖。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/document_store.py` |
| `src/renderer/app.js` | `buildAgentDocumentPayload`、`executeAgentPlan` |
| `src/python/server.py` | `/api/agent/run` |

### 建议修复

- 前端：`/api/agent/run` 409/400 含 `stale_plan` 或缓存过期时，自动 `buildDocumentsPayload()` 重传并重试；
- 或执行时始终附带 `uploadedDocuments` 快照（体积换可靠性）。

### 验收

- 解析 → 计划 → 重启后端 → 执行：自动恢复或明确引导「请重新生成计划」；
- 超 TTL 同上。

---

## RL5 — V4 pipeline 子阶段进度未推送 SSE ✅

**严重度**：🟡 中  
**影响**：标准 / 深度 / ReAct 中的 `solve_lab` 步骤  
**修复**：2026-06-06 — `executor._run_solve_lab` 的 `on_phase` 推送 `pipeline_phase` SSE；`app.js` 展示子阶段；`tests/test_runtime_logic.py::TestRL5PipelinePhaseSse`

### 现象

`solve_lab` 显示「执行中…」长达数分钟，用户不知当前在生成代码、跑沙箱还是写报告。

### 根因

`executor._run_solve_lab` 的 `on_phase` 仅写入 `ctx["pipeline_phases"]`，未 `emit_event`。
V4-1 backlog「SSE 子阶段」未落地。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/executor.py` |
| `src/python/modules/solve_pipeline.py` |
| `src/renderer/app.js` |

### 建议修复

- 新增 SSE 事件类型 `pipeline_phase`（或复用 `thought`）；
- 前端在 autonomous 模式侧栏或 Step3 展示子阶段。

### 验收

- 跑含代码实验时可见：`understand_brief` → `solve_code` → `run_code_sandbox` → `write_report_text`。

---

## RL6 — V4 内化验证与计划内 `run_code` 重复 ✅

**严重度**：🟡 中  
**影响**：默认 V4 pipeline + Planner 含 `run_code` 的计划  
**修复**：2026-06-06 — Planner/fallback 默认不勾 `run_code`；`executor._run_run_code` 复用 `code_status=verified`；`tests/test_runtime_logic.py::TestRL6RunCodeDedup`

### 现象

同一份代码在 `solve_lab` 内已验证/修复，计划又执行 `run_code` → 可能再次失败并触发 `fix_code`，浪费轮次。

### 根因

1. `should_use_pipeline` 默认 v4，`solve_lab` 内含 sandbox。
2. Planner / `_fallback_plan` 在报告含「代码/程序/运行」时仍插入 `run_code`。
3. Planner prompt 未说明「solve_lab 已含内化验证」。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/planner.py` |
| `src/python/agent/prompts.py` |
| `src/python/modules/solve_pipeline.py` |

### 建议修复

- 用户约束含 `skip_validation` 或 V4 开启时，默认不勾 `run_code`；
- 或 `run_code` 检测到 `solve_session.code_status === 'verified'` 时直接复用结果。

### 验收

- 默认计划：代码题仅一次内化验证；`run_code` 为可选高级步骤。

---

## RL7 — 三种运行模式编排语义分裂 ✅

**严重度**：🟡 中（维护债）  
**影响**：长期演进、修一处漏一处  
**修复**：2026-06-06 — `compute_run_ok`（BF35）+ `complete_agent_run` 共享收尾 + ReAct `execute_tool` 经 `RunOrchestrator.run_module`；深度 tail 移除 legacy 内联循环；`tests/test_runtime_logic.py::TestRL7ComputeRunOk`

### 说明（收敛后）

| 能力 | 标准 | 深度 | ReAct |
|------|------|------|-------|
| 谁决定步骤 | `confirmed_steps` 顺序 | draft/reflect（Policy）+ orch tail | LLM 选题（Policy） |
| 怎么跑模块 | `RunOrchestrator.run_steps` / `run_module` | 同上（tail） | `run_module`（工具分发） |
| 收尾 | `complete_agent_run` | 同上 | 同上 + `react_finalize_pipeline` |
| `done.ok` | `compute_run_ok` | 同上 | 同上 |

Policy 层仍分三模式；Core 层 verify / finalize / done payload 已统一。

---

## RL8 — Agent 路径 JAR 同意仅跑完后补救 ✅

**严重度**：🟡 中  
**影响**：Java + 第三方 JDBC（H2/SQLite）实验 + `allow_curated_jars` 约束  
**修复**：2026-06-06 — SSE `jar_consent_required` + `/api/agent/jar-consent`；`executor` 传 `on_jar_consent`；`app.js` 中途弹窗；`tests/test_runtime_logic.py::TestRL8JarConsentMidRun`

### 现象

Agent 执行中验证被 skip（`reason: missing_jar`），跑完后 `applyAgentRunDone` 才调 `maybeRetryValidationForMissingJars` 弹窗。

### 根因

`executor._run_solve_lab` 传 `approved_jar_ids`，不传 `on_jar_consent`；pipeline 无法中途阻塞等用户。
工具箱 quick solve 有完整中途弹窗流程。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/executor.py` |
| `src/renderer/app.js` | `applyAgentRunDone`、`maybeRetryValidationForMissingJars` |

### 建议修复

- ~~短期：保持跑后补救，但在 Step3 明确展示「待确认 jar」~~ → 已落地中途 SSE 弹窗 + Step3 文案；
- ~~长期：SSE 事件 `jar_consent_required` + 前端模态~~ → 已落地；跑后 `maybeRetryValidationForMissingJars` 仍作兜底。

---

## RL9 — ReAct 提示词与 V5 deliverable 定位冲突 ✅

**严重度**：🟡 中  
**影响**：ReAct + `output_mode=deliverable`（默认）  
**修复**：2026-06-06 — `react_loop` / `react_prompts` 按 `output_mode` 分支；deliverable 引导 `present_deliverable`；`tests/test_runtime_logic.py::TestRL9ReactDeliverablePrompts`

### 现象

`run_code` 多次失败后注入：「实验报告类作业必须产出 Word 文档…」，与 V5「答案工作区复制、fill 为高级」矛盾。

### 涉及文件

| 文件 |
|------|
| `src/python/agent/react_loop.py` |
| `src/python/agent/react_prompts.py` |

### 建议修复

按 `output_mode` 分支提示：deliverable → 引导 `present_deliverable`；fill_original → 才可提 fill_report。

---

## RL10 — 单任务锁 + SSE 无重连 ✅

**严重度**：🟡 中  
**影响**：长跑、网络抖动、页面刷新  
**修复**：2026-06-06 — `event_log` 回放 + `?since=` 重连；`GET /api/agent/run-status`；前端自动重连 3 次；进度文案提示勿刷新；`tests/test_runtime_logic.py::TestRL10SseReplay`

### 说明（残余）

- `acquire_run` 仍全局单任务（`RunBusyError`）；刷新恢复见 RL10 续（BF41）。

### RL10 续 — 刷新后 run 状态恢复 ✅

**修复**：2026-06-06 — `localStorage` 持久化 `run_id`/步骤/SSE 偏移；启动时 `tryRestoreAgentRunAfterLoad` 回放 `run-status` 并重连 SSE；`GET /api/agent/active-run` 兜底；`tests/test_runtime_logic.py::TestRL10SseReplay`

---

## RL11 — 初始化 5s 超时与后端就绪竞态 ✅

**严重度**：🟢 低  
**修复**：2026-06-06 — `runServerReadyBootstrap` 单次守卫；5s 仅解锁 UI + 本地 `loadSettings`/`renderHistory`；`/api/health` 轮询作 IPC 兜底；`tests/test_runtime_logic.py::TestRL11InitServerReady`

### 现象

后端慢启动（主进程 `waitForServer` 可达 ~10s）时，5s 超时抢先调用 `fetchLogFilePath` / `runComplianceStartupSequence`，首批 API 失败。

### 根因

`init()` 的 5s `setTimeout` 与 `onServerReady` 并行，且重复执行同一套 bootstrap，不区分「UI 解锁」与「后端 API 就绪」。

### 涉及文件

| 文件 |
|------|
| `src/renderer/app.js` | `init()`、`runServerReadyBootstrap`、`pollServerHealth` |

### 验收

- 慢启动时 5s 后界面可交互，但合规/日志等 API 仅在 health 通过或 `server-ready` IPC 后执行；
- 正常启动仍只 Toast 一次「AI引擎就绪」。

---

## RL12 — 深度模式 `done.ok` 过严 ✅

**严重度**：🟢 低  
**修复**：2026-06-06 — `deep_pipeline` 改用 `compute_run_ok(ctx)`，verify 仅作 `verification_report` 展示；`tests/test_runtime_logic.py::TestRL12DeepDoneOk`

---

## 修复路线图（建议）

| 阶段 | 项 | 状态 |
|------|-----|------|
| **P0** | RL1 SSE 假错误 + RL2 ReAct ok | ✅ 2026-06-06 |
| **P1** | RL3 标准 ok + RL4 文档缓存兜底 | ✅ 2026-06-06 |
| **P2** | RL5 子阶段 SSE + RL6 去重 run_code + RL9 提示词 | ✅ 2026-06-06 |
| **P3** | RL7 done.ok 收敛 + RL8 JAR 中途 + RL10 SSE 重连 + RL12 deep ok | ✅ 2026-06-06 |
| **AO-P0** | deep V4 去重 preflight/fix（`test_deep_pipeline_v4.py`） | ✅ 2026-06-06 |
| **backlog** | — | — |

---

## 与已修复项的关系

[V1_BUGFIX_LOG.md](../logs/V1_BUGFIX_LOG.md) 中 BF1–BF41 为**已落地**修复（含 BF28–BF41 对应 RL1–RL12）。

**RL 修复记录**：

| RL | BF | 测试 |
|----|-----|------|
| RL1 | BF28 | `tests/test_runtime_logic.py::TestRL1SseGracefulClose` |
| RL2 | BF29 | `tests/test_runtime_logic.py::TestRL2ReactFallbackDoneOk` |
| RL3 | BF30 | `tests/test_runtime_logic.py::TestRL3StandardRunDoneOk` |
| RL4 | BF31 | `tests/test_runtime_logic.py::TestRL4StaleDocumentRetry` |
| RL5 | BF32 | `tests/test_runtime_logic.py::TestRL5PipelinePhaseSse` |
| RL6 | BF33 | `tests/test_runtime_logic.py::TestRL6RunCodeDedup` |
| RL9 | BF34 | `tests/test_runtime_logic.py::TestRL9ReactDeliverablePrompts` |
| RL7 | BF35、BF40 | `tests/test_runtime_logic.py::TestRL7ComputeRunOk` |
| RL8 | BF36 | `tests/test_runtime_logic.py::TestRL8JarConsentMidRun` |
| RL10 | BF37、BF41 | `tests/test_runtime_logic.py::TestRL10SseReplay` |
| RL12 | BF38 | `tests/test_runtime_logic.py::TestRL12DeepDoneOk` |
| RL11 | BF39 | `tests/test_runtime_logic.py::TestRL11InitServerReady` |

后续 RL 修复仍按：本表标 ✅ → 用户可见则写 BF 条目 → 补 `test_runtime_logic.py` 或专项 pytest。

---

*文档版本：2026-06-06（P0–P3 落地）· 审查方式：静态链路分析 + `tests/test_runtime_logic.py`*
