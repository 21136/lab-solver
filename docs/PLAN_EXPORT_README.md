# Lab-Solver Agent 计划导出说明

**导出时间**：2026-06-03（已合并 DeepSeek **附录 B + 附录 D**；见 [deepseek的建议.md](./deepseek的建议.md)）  
**实现进度**：Phase 1～3 主体已落地；详见 [IMPLEMENTATION_PHASES.md](./IMPLEMENTATION_PHASES.md) §四  
**完整计划正文**：[`LAB_SOLVER_AGENT_PLAN.md`](./LAB_SOLVER_AGENT_PLAN.md)（与 Cursor 计划同步）  
**分阶段实施（推荐先看）**：[`IMPLEMENTATION_PHASES.md`](./IMPLEMENTATION_PHASES.md)  
**Cursor 源文件**：`%USERPROFILE%\.cursor\plans\lab_solver_agent_a5374109.plan.md`

---

## 给其它 AI 的推荐用法

1. 上传或粘贴 **`LAB_SOLVER_AGENT_PLAN.md` 全文**。
2. 附上项目背景（可选）：
   - 桌面 Electron + Python Flask 后端
   - 实验报告解题助手，用户自填 API Key（safeStorage 加密，见 [KEY_STORAGE.md](./KEY_STORAGE.md)）
   - **已实现**：标准/深度/ReAct Agent、分节工作台、verify/revise、PDF 读/导出 docx、V2 动态分节（L0-L3）
   - **待补**：Step1 多文档/范文 UI、`build-installer` 打包验证
3. 明确你希望的输出类型，例如：
   - 挑逻辑漏洞 / 矛盾
   - 压缩实施范围（MVP）
   - API 设计评审
   - Token 成本再优化
   - Phase 拆分与依赖顺序

---

## 建议提问模板（复制即用）

```
你是软件架构评审。下面是一份「解题能手 lab-solver」从桌面工具升级为模块化 Agent 的完整计划。

请基于全文：
1. 找出前后矛盾、遗漏依赖、过度设计之处；
2. 建议 MVP 最小可发布范围（标出可延后章节）；
3. 对 Phase 1→2a→2b→3 顺序提出调整；
4. 单独评价 Token 默认策略（`agent_mode=标准`，约 2 次 LLM）是否合理。

计划全文：
---
（粘贴 LAB_SOLVER_AGENT_PLAN.md）
---
```

---

## 计划要点速览（便于短上下文）

| 维度 | 决策 | 实现状态 |
|------|------|----------|
| 平台 | 保留 Electron，用户自选 LLM API Key，不用 Cursor SDK | ✅ |
| 核心流 | 子模块 + Planner 步骤计划 + 用户确认后执行 | ✅ 标准/深度/ReAct |
| 默认省流 | `run_mode=standard`（约 2 次 LLM） | ✅ |
| 深度可选 | understand→plan→draft→preflight→reflect→execute | ✅ |
| 运行模式 | 标准/深度/ReAct 三档；ReAct 含 **自动收尾** + `finalize_report` | ✅ |
| UI | Step2 分节工作台；Step3 SSE + 校验修订 | ✅；Step1 多文档 + 粘贴题目 ✅ |
| 文档 | docx/pdf 读；PDF 导出 docx；合体拆分；**粘贴题目**（`text_content`） | ✅ |
| Key 存储 | Electron safeStorage + 降级说明 | ✅ [KEY_STORAGE.md](./KEY_STORAGE.md) |
| 已舍弃 | 第三方软件 GUI 自动操控 | — |
| 待发布 | `build-installer.bat` 打包验证 | ⏳ |

---

## 文件列表

| 文件 | 用途 |
|------|------|
| `LAB_SOLVER_AGENT_PLAN.md` | 完整计划（给 AI / 团队评审） |
| `PLAN_EXPORT_README.md` | 本说明 + 提问模板 |
| `IMPLEMENTATION_PHASES.md` | V1 分阶段实施与当前进度 |
| `NEXT_VERSION_BACKLOG.md` | **下一版 v2**：核心项 + **盲区/O7–O31**（§二） |
| `V2_DOC_TEMPLATE_ADAPTATION.md` | **v2 高优**：表格实训、节号不统一（DA1–DA4） |
| `V2_IMAGE_INPUT.md` | **v2 高优**：图片/多图识题（IM1–IM5，含 OCR/Vision） |
| `PROMPT_CRITIQUE_CHECKLIST.md` | 分维度评审清单（可选） |
| `KEY_STORAGE.md` | API Key safeStorage 与风险说明 |
