# V1 错误修复日志

**用途**：记录 V1 版本从测试/使用中发现的 bug 及其修复。  
**最后更新**：2026-06-08

---

## BF1 — 文档缓存未写入（"文档缓存已过期或不存在"）

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（标准模式生成计划完全不可用）  
**影响范围**：全部多文档流程（标准模式、深度模式、执行计划）

### 症状

上传文档 → 解析成功 → 点击「生成计划」→ 报错 `文档缓存已过期或不存在`。

### 根因链路

```
POST /api/parse-report → parse_documents_list(documents)
  → 返回 {document_ids, _bundles, ...}
  ❌ 没有调用 store_parsed_batch(_bundles)
  → bundles 随 HTTP 响应返回后就丢弃了

POST /api/agent/plan → store_from_request_payload({document_ids})
  → resolve_agent_context(ids)
    → get_document(did) → _store[did] → None
  💥 "文档缓存已过期或不存在"
```

`document_store._store` 是一个**内存** dict，`/api/parse-report` 从未把解析结果写入其中，后续 `/api/agent/plan`、`/api/agent/run` 自然找不到。

### 修复

**文件**：`src/python/server.py`（+5 行）、`src/python/agent/document_store.py`（+1/-1 行）

1. **server.py** — `/api/parse-report` 多文档分支，在 `parse_documents_list()` 之后立即调用 `store_parsed_batch(parsed["_bundles"])`，把解析结果写入内存缓存
2. **document_store.py** — `store_from_request_payload()` 缓存路径，从 `return ids, ctx["primary_bundle"]` 改为 `return ids, ctx`，返回完整的合并上下文而非单个 bundle（见 BF2）

### 验收

- 上传多文档 → 解析 → 生成计划 → 正常返回步骤列表
- 上传单文档 → 同上
- 解析后重新生成计划不报缓存错误

> **2026-06-06 补充（BF31 / RL4）**：BF1/BF2 覆盖 parse→plan；**plan→run** 间隔或后端重启导致 `document_ids` 失效时，由 `/api/agent/run` 返回 `stale_documents` + 前端 `postAgentRunWithDocRetry` 自动重传。见 BF31。

---

## BF2 — 缓存路径丢失多文档合并上下文

**发现时间**：2026-06-04  
**严重度**：🟡 中等（多文档场景 Planner 看不到 assignment 内容）  
**影响范围**：多文档上传后走缓存路径（`document_ids` 已存在时）

### 症状

多文档场景（如：题目 docx + 待填报告 docx），Planner 只能看到 fill_target 的文本，assignment 文档的内容被忽略。

### 根因

`store_from_request_payload()` 在 `document_ids` 已存在时：

```python
ctx = resolve_agent_context(ids)
return ids, ctx["primary_bundle"]  # ← 只返回一个 bundle
```

`resolve_agent_context()` 已经正确合并了所有文档的 `planner_input_text`、`assignment_text`、`references` 等，但只返回了 `primary_bundle`（fill_target），合并后的上下文被丢弃。

而直接发送 `documents[]` 的路径返回的是 `parse_documents_list()` 的完整结果，两个路径行为不一致。

### 修复

**文件**：`src/python/agent/document_store.py` L255

```python
# 旧
return ids, ctx["primary_bundle"]

# 新
return ids, ctx
```

`ctx` 和 `parse_documents_list()` 返回的 dict 拥有相同的关键字段（`planner_input_text`、`report_text`、`assignment_text`、`layout`、`fill_target` 等），所有调用方兼容。

**同步受影响的调用方**（无需改动，已验证兼容）：

| 路由 | 使用方式 | 兼容性 |
|------|---------|--------|
| `/api/agent/plan` | `bundle.get("planner_input_text")` | ✅ ctx 有此字段 |
| `/api/agent/run` | `bundle.get("planner_input_text")` | ✅ 同上 |
| `_session_format_spec` | `bundle.get("metadata")` / `bundle.get("assignment_text")` | ✅ ctx 有这些字段 |

---

## BF3 — 训练表格报告布局误判（P0A）

**发现时间**：2026-06-04（日志诊断）  
**严重度**：🔴 严重（实训表格报告无法正确解题）  
**来源文档**：[V2_CODE_EXECUTION_FIX.md](../v2/V2_CODE_EXECUTION_FIX.md)

### 症状

上传纯实训表格 `.docx`（无"三/四/五"标题），`detect_combined_layout()` 回退为 `assignment_only`，Planner 不知道填什么、填哪里。

### 根因

`parse_single_file()` 中 `detect_combined_layout()` 找不到三/四/五标题就返回 `assignment_only`，但 `parse_report` 模块已经通过表格结构检测识别为 `training_table`，这个结果存在 metadata 里，没有被 `detect_combined_layout` 使用。

### 修复

**文件**：`src/python/agent/parse_documents.py`（+14 行）

`parse_single_file()` 在 `detect_combined_layout()` 返回 `assignment_only` 但 `metadata.report_layout == "training_table"` 时，覆盖为 `fill_only`。

详见 [V2_CODE_EXECUTION_FIX.md](../v2/V2_CODE_EXECUTION_FIX.md) §P0A。

---

## BF4 — 快速解题路径缺失代码预检（P0B）

**发现时间**：2026-06-04（日志诊断）  
**严重度**：🟡 中等（Web 服务器代码 15 秒超时白等）  
**来源文档**：[V2_CODE_EXECUTION_FIX.md](../v2/V2_CODE_EXECUTION_FIX.md)

### 症状

AI 生成 Flask Web 服务器代码（含 `app.run()`），快速解题后盲跑，15 秒超时。

### 根因

`preflight._check_execution_pattern()` 能检测 `web_server`/`interactive` 模式，但只在**深度模式** DeepPipeline 的 draft→preflight 阶段调用。快速解题 `/api/solve` 和标准模式执行后直接跑代码，不预检。

### 修复

**文件**：`src/python/server.py`（+18 行）

`/api/run-code` 和 `/api/run-and-screenshot` 在执行前调用 `_check_execution_pattern()`，检测到隐患 → 跳过执行 → 返回 `blocked_by_preflight: true`。

详见 [V2_CODE_EXECUTION_FIX.md](../v2/V2_CODE_EXECUTION_FIX.md) §P0B。

---

## BF5 — Prompt 模板花括号转义错误

**发现时间**：2026-06-04（单元测试失败）  
**严重度**：🔴 阻断（导致 2 个测试失败，prompt 渲染崩溃）  

### 症状

```python
pytest tests/test_phase2b_b4.py
# FAILED test_render_lab_prompt_backward_compat - KeyError: '"name"'
# FAILED test_render_lab_prompt_with_constraints - KeyError: '"name"'
```

### 根因

`prompts.py` 的 `LAB_REPORT_USER` 模板中 JSON 示例含 `{"name": "main.py", "code": "..."}`，Python 的 `str.format()` 把 `{"name"...}` 中的 `"name"` 解析为格式化参数名，但 `render()` 调用方未传该 key，抛 `KeyError`。

### 修复

**文件**：`src/python/agent/prompts.py`

```python
# 旧（被 .format() 误解析）
{"name": "main.py", "code": "完整可运行源码含中文注释"}

# 新（双花括号转义）
{{"name": "main.py", "code": "完整可运行源码含中文注释"}}
```

同一问题在 `FIX_CODE_USER` 模板中一并修复。

---

## 总结

| ID | 简述 | 严重度 | 文件 | 状态 |
|----|------|--------|------|------|
| BF1 | parse_report_route 不写缓存 | 🔴 阻断 | `server.py` +5, `document_store.py` ±1 | ✅ |
| BF2 | 缓存路径返回单 bundle 丢失合并上下文 | 🟡 中等 | `document_store.py` ±1 | ✅ |
| BF3 | 训练表格布局误判 assignment_only | 🔴 严重 | `parse_documents.py` +14 | ✅ |
| BF4 | 快速解题缺失代码预检 | 🟡 中等 | `server.py` +18 | ✅ |
| BF5 | Prompt JSON 花括号被 .format() 当作参数 | 🔴 阻断 | `prompts.py` | ✅ |

**未修已知问题**：（无）

---

## BF6 — Windows 退出时 Python 僵尸进程堆积

**发现时间**：2026-06-04（缓存修复验证时发现）  
**严重度**：🔴 阻断（代码修改不生效、请求路由到旧代码、行为不可预测）  
**影响范围**：所有 Electron 启动后修改代码并重启的场景

### 症状

1. 修改 Python 代码后重启 Electron，旧 bug 依旧存在
2. 添加日志标记后完全不出现在日志中，仿佛新代码从未加载
3. `netstat -ano` 显示端口 5199 上有多个 `LISTENING` 的 Python 进程
4. `taskkill /f /im python.exe` 静默失败，`tasklist` 不显示这些 PID（但 `powershell Get-Process` 可见）

### 根因

Electron 的 `process.kill()` 在 Windows 上无法彻底杀掉 Flask 的多线程子进程：

1. `main.js` 使用 `pythonProcess.kill()` — 只发 `SIGTERM` 信号，Windows 不支持标准 POSIX 信号，实际效果弱
2. Flask 的 `threaded=True` 模式会 fork 出多个处理线程，`kill()` 只杀主线程
3. 关闭窗口退出时没有等待 kill 完成，Electron 自身退出后 Python 成孤儿进程
4. `before-quit` / `window-all-closed` 只绑定了 `kill()`，`will-quit` 和进程信号均未处理
5. 累积效应：每次"重启" spawn 新进程，旧进程未死，端口复用导致请求随机路由到新旧进程之一

**验证法**：
```bash
netstat -ano | findstr ":5199.*LISTENING"
# 观察到 7 个 PID 同时监听，全部是旧 Python 进程
```

### 修复

**文件**：`main.js`（+50/-4 行）

1. `killPythonTree(pid)` — 新增：Windows 用 `taskkill /F /T /PID` 树级强杀（`/T` 杀所有子进程），macOS/Linux 用 `kill(-pid, SIGKILL)` 进程组杀
2. `killAllPythonOnPort(port)` — 新增：`netstat` 查端口上的所有 LISTENING PID → `taskkill /F` 逐个清理
3. `cleanupPython()` — 新增：组合 `killPythonTree` + `killAllPythonOnPort` 兜底
4. `startPythonServer()` — spawn 之前调用 `killAllPythonOnPort` 清理僵尸；记录 `pythonPid`
5. 退出事件 — `window-all-closed`、`before-quit`、`will-quit`、`SIGINT`、`SIGTERM` 全部绑定 `cleanupPython()`

### 验收

- 关闭 Electron 窗口后：`netstat -ano | findstr ":5199.*LISTENING"` 输出为空
- 修改 Python 代码 → 重启 Electron → 新日志标记立即出现在 `app.log`
- 反复开关 5 次：端口上始终只有 1 个进程

---

## BF7 — Emoji 导致 Windows 控制台 GBK 编码崩溃

**发现时间**：2026-06-04（排查 BF1 缓存修复不生效时发现）  
**严重度**：🔴 阻断（只要日志消息含 emoji，整个请求就崩溃）  
**影响范围**：所有含 emoji 的 `logi()` 调用 → 后端 400 错误

### 症状

`/api/parse-report` 返回 `HTTP 400`，日志中只有 traceback，没有正常流程日志。

```
[17:27:XX][ERROR][parse] Traceback (most recent call last):
  File "server.py", line 180, in parse_report_route
    logi("parse", "V2 parse_report_route documents branch entered")
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f7e2' in position 24
```

### 根因

`log_util.py` 中 `log()` 函数执行 `print(line, end="")`，Windows 的 `sys.stdout` 默认编码是 **GBK**。GBK 是双字节编码，无法表示 4 字节 UTF-8 emoji（如 🟢📦🔴🚀🔍）。即使日志消息本身正确，**第一个含 emoji 的 `logi()` 调用就会抛 `UnicodeEncodeError`**，Flask 捕获异常后返回 400。

典型链路：
```
parse_report_route()
  → logi("parse", "🟢 branch entered")   # 💥 UnicodeEncodeError
  → Flask 捕获 → return 400
  → 后续 store_parsed_batch() 永远执行不到
```

### 修复

**文件**：`src/python/server.py`（-4 行调试日志 + 去 emoji）、`src/python/agent/parse_documents.py`（去 emoji 标记）、`src/python/agent/document_store.py`（去 emoji 标记）

**原则**：日志中禁止使用 emoji。`log_util.py` 的 `sanitize_log_message` 可考虑增加非 ASCII 过滤（留给后续加固）。

> **2026-06-06 补充（BF24）**：已完成生成侧禁止 + 运行/日志防御，见 BF24。

### 验收

- `python -c "from log_util import logi; logi('test', 'hello')"` 不抛异常
- Windows 终端启动 server.py 无编码错误

---

## BF8 — Agent 模式 null textContent 崩溃

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（Agent 执行完成 + 手动点"运行"→ 前端崩溃）  
**影响范围**：Agent 模式结束后运行代码

### 症状

Agent 执行完成 → 代码面板自动打开 → 点"▶ 运行" → 报错：
```
Cannot set properties of null (setting 'textContent')
```

### 根因

`runCode()` 的完成回调中直接访问 `answer-{idx}` 元素：

```js
document.getElementById(`answer-${idx}`).textContent = `代码已执行...`;
```

- **快速解题**（`solveAll`）调用 `renderSolvingList()`，列表项 ID = `answer-{i}`
- **Agent 模式**调用 `renderAgentProgressList()`，列表项 ID = `agent-detail-{module}`
- Agent 完成后 `onSolveComplete` → `showCodePanel` 自动打开代码面板，`questionIndex = 0`
- 用户点"运行" → 代码执行完成 → 查找 `answer-0` → 元素不存在 → `null.textContent` 崩溃

### 修复

**文件**：`src/renderer/app.js`（6 处加 guard）

1. `runCode()` — `btn` / `consoleBody` 为空时 early return（防止 code panel 意外关闭时崩溃）
2. `runCode()` 完成回调 — `answer-${idx}` 不存在时静默跳过
3. `showCodePanel()` — `codePanel` 为空时 early return；`codePanelTitle` 空时跳过
4. `applyAgentRunDone()` / `executeAgentPlan()` / `solveAll()` — `step3Title` 空时跳过

### 验收

- Agent 模式执行完成 → 代码面板打开 → 点"▶ 运行" → 输出正常，不崩溃
- 快速解题 → 代码面板打开 → 点"▶ 运行" → 输出正常

---

## BF9 — code_files → code 不回写致 fix_code 生成错误代码

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（Agent 模式生成页面置换算法实验，最终代码却是冒泡排序）  
**影响范围**：所有 Agent 模式（标准/深度），P1 多文件 prompt 改后

### 症状

1. 上传"页面置换算法"实验报告 → Agent 执行 → 思考过程正确（页面置换算法）
2. 代码面板显示的代码却是**冒泡排序**，与实验内容完全无关
3. 日志中首次 `solve_lab` 的 `parsed补全后 keys` 含 `code_files` 但**不含 `code`**

```
[17:36:30][INFO][ai] parsed补全后 keys=['course_type', 'language', 'steps_analysis',
  'result_description', 'expected_output', 'summary', 'code_files', 'main_file', 'diagrams']
#                                                                 ^^^^^^^^^^
#                                                    有 code_files，没有 code！
```

### 根因

P1（多文件代码支持）修改了 prompt JSON schema，AI 开始返回新格式：

```json
{
  "code_files": [{"name": "main.py", "code": "def fifo():\n  ..."}],
  "main_file": "main.py"
}
```

不再返回旧的 `"code"` 字段。但 `complete_lab_parsed()` 的规范化逻辑是**单向的**：

```python
# lab_parse.py L158-169（修复前）
code_files = parsed.get("code_files")
if isinstance(code_files, list) and code_files:
    parsed["code_files"] = code_files          # ✅ code_files 正常
    # ❌ 从未设置 parsed["code"]
elif parsed.get("code"):
    parsed["code_files"] = [...]               # code → code_files ✅
```

AI 走第一个分支：`code_files` 有值但 `code` 从不设置。下游影响链：

1. **`llm_client.call_ai()`** — `code = parsed.get("code") or extract_code_block(...)` → 可能从全文正则提取到代码，也可能返回空字符串
2. **`deep_pipeline.py` L126** — `fix_code_from_error(code=solve_data.get("code") or "", ...)` → 拿到空字符串或正则误提取的代码
3. **`fix_code.py`** — LLM 收到空代码 + "请修复" → **自行发挥，生成冒泡排序**
4. **`deep_pipeline.py` L173** — `solve_data["code"] = parsed.get("code") or solve_data.get("code")` → 只更新 `code`，不更新 `code_files`

### 修复

**文件**：`src/python/modules/lab_parse.py`（+3 行）、`src/python/agent/deep_pipeline.py`（+8 行）

1. **lab_parse.py** — `complete_lab_parsed()` 规范化时**双向**设置：
   ```python
   if isinstance(code_files, list) and code_files:
       parsed["code_files"] = code_files
       ...
       if not parsed.get("code"):
           parsed["code"] = code_files[0].get("code", "")  # ← 新增：回写
   ```

2. **deep_pipeline.py** L124 — `fix_code_from_error()` 调用增加 `code_files`、`main_file` 参数

3. **deep_pipeline.py** L173 — `revise_answer` 后同步更新 `solve_data["code_files"]` 和 `solve_data["main_file"]`

### 验收

- 上传实验报告 → Agent 执行 → 代码面板显示与实验内容一致的代码
- AI 返回 `code_files`（新格式）→ `solve_data["code"]` 自动获得主文件代码
- AI 返回 `code`（旧格式）→ 不受影响，仍正常

---

## 总结

| ID | 简述 | 严重度 | 文件 | 状态 |
|----|------|--------|------|------|
| BF1 | parse_report_route 不写缓存 | 🔴 阻断 | `server.py` +5, `document_store.py` ±1 | ✅ |
| BF2 | 缓存路径返回单 bundle 丢失合并上下文 | 🟡 中等 | `document_store.py` ±1 | ✅ |
| BF3 | 训练表格布局误判 assignment_only | 🔴 严重 | `parse_documents.py` +14 | ✅ |
| BF4 | 快速解题缺失代码预检 | 🟡 中等 | `server.py` +18 | ✅ |
| BF5 | Prompt JSON 花括号被 .format() 当作参数 | 🔴 阻断 | `prompts.py` | ✅ |
| BF6 | Windows 退出时 Python 僵尸进程堆积 | 🔴 阻断 | `main.js` +50/-4 | ✅ |
| BF7 | Emoji 导致 Windows GBK 控制台编码崩溃 | 🔴 阻断 | `server.py`, `parse_documents.py`, `document_store.py` | ✅ |
| BF8 | Agent 模式 null textContent 崩溃 | 🔴 阻断 | `app.js` 6 处 +guard | ✅ |
| BF9 | code_files→code 不回写导致 fix_code 生成错误代码 | 🔴 阻断 | `lab_parse.py` +3, `deep_pipeline.py` +8 | ✅ |
| BF10 | solve_lab 只传 report_text 导致合体文档看不到题目 | 🔴 阻断 | `executor.py` +3/-1, `fallback.py` ±1 | ✅ |
| BF11 | replan/reflect/revise/fix/uml 等多处仅用 report_text | 🔴 阻断 | 6 个文件共 8 处修复 | ✅ |
| BF12 | revise_answer 不支持 code_files（P1 副作用） | 🔴 阻断 | `revise_answer.py` +12, `prompts.py` ±1 | ✅ |
| BF13 | 实训表格"实训任务"标签不在填表关键字中 | 🔴 阻断 | `fill_report.py` ±1, `test_da3_fill.py` ±1 | ✅ |
| BF14 | JSP/HTML 混入 Java 代码未检测 → 编译失败 | 🔴 阻断 | `preflight.py` +14, `executor.py` +1, `fix_code.py` +6, `deep_pipeline.py` +6, `app.js` +12 | ✅ |

**BF1 补充说明**：BF1 的修复代码本身正确，但因 BF6（僵尸进程跑旧代码）和 BF7（emoji 使新代码第一个日志调用就崩溃）叠加，修复在 7 次重启中从未真正生效。三 bug 同步修复后方可通过端到端验证。

**BF9 补充说明**：BF9 是 P1（多文件代码）的副作用。但用户反馈还有更深层问题：首轮 solve_lab 生成的文字内容也完全对不上（学生成绩管理系统而非页面置换算法），这说明 LLM 根本没看到题目要求。见 BF10。

**未修已知问题**：（无）

---

## BF10 — solve_lab 只传 report_text 导致合体文档看不到题目

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（合体文档（前半题目+后半模版）的 Agent 解题内容完全对不上）  
**影响范围**：所有合体文档（combined layout，占多数单文档上传场景）

### 症状

1. 上传"页面置换算法"实验报告 → Agent 执行 → 解题文字是"学生成绩管理系统"
2. 思考过程（understand/reflect/preflight）描述正确（页面置换算法）
3. 首轮 solve_lab 就已偏离，后续 fix/revise 也无法纠回

### 根因链路

合体文档（combined layout）的处理逻辑：

```
parse_single_file() L185-194:
  combined layout → split at "三、实验步骤"
    assignment_text = 拆分点之前（实验目的、实验要求）  ← 包含题目！
    fill_body_text  = 拆分点之后（三、实验步骤 + 四、五空壳）
    report_text     = fill_body_text                    ← 仅空壳模版！
```

但 `_run_solve_lab()` 把 LLM 调用用的 full_text 设为：

```python
# executor.py L103（修复前）
question["full_text"] = ctx.get("report_text") or question.get("full_text") or ""
```

`ctx["report_text"]` 非空（"三、实验步骤\n\n四、实验结果\n\n五、实验总结"），短路取到空壳模版。

LLM 收到的 prompt 只有：
```
你是一名大学课程助教...
【实验报告全文】
三、实验步骤

四、实验结果

五、实验总结
```

没有实验目的、没有算法要求、没有题目内容。LLM 只能猜测，随便写了个"学生成绩管理系统"。

而 Planner 和 Reflect 用的是 `planner_input_text`（包含 `【作业要求】` + `【待填报告】`），所以它们的分析是正确的。

### 修复

**文件**：`src/python/agent/executor.py`（+3/-1 行）、`src/python/agent/fallback.py`（±1 行）

```python
# _run_solve_lab（修复后）
full_text = ctx.get("planner_input_text") or ctx.get("report_text") or question.get("full_text") or ""
question["full_text"] = full_text
```

```python
# fallback.py（修复后）
question["full_text"] = ctx.get("planner_input_text") or ctx.get("report_text") or question.get("full_text") or ""
```

`planner_input_text` = `【作业要求】\n...\n\n【待填报告】\n...`，LLM 看到完整上下文。

`_run_solve_theory` 同步修复。

### 验收

- 上传合体文档（前半题目+后半空壳）→ Agent 执行 → 解题内容与实验要求匹配
- 非合体文档不受影响（`planner_input_text` 回退到 `report_text`）
- Reflect 审稿不再报告"内容完全偏离作业要求"

---

## BF11 — 系统审计：Agent 路径多处仅用 report_text 丢失题目上下文

**发现时间**：2026-06-04（全量审计 Agent 路径）  
**严重度**：🔴 阻断 — 合体文档关键路径多处 LLM 调用看不到题目要求  
**影响范围**：replan、reflect、revise、fix_code、UML 检测

### 背景

合体文档（combined）拆分后：
- `planner_input_text` = `【作业要求】` + `【待填报告】`（完整）
- `report_text` = 拆分点之后的报告壳（仅空壳模版）

BF10 修复了 `solve_lab` 路径，但全量审计发现 **8 处**其他位置也使用了 `report_text`。

### 审计发现与修复

| # | 文件 | 原代码 | 修复 | 严重度 |
|---|------|--------|------|--------|
| 1 | `planner.py:557` replan fallback | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🔴 |
| 2 | `planner.py:562` replan fingerprint | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🔴 |
| 3 | `planner.py:650` clarify fallback | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🔴 |
| 4 | `reflect.py:32` reflect anchor | 回退链缺 `planner_input_text` | 插入 `ctx.get("planner_input_text")` | 🟡 |
| 5 | `deep_pipeline.py:131` preflight fix | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🟡 |
| 6 | `deep_pipeline.py:169` revise | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🟡 |
| 7 | `executor.py:259` fix_and_retry | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🟢 |
| 8 | `executor.py:370` run_fix_code | `ctx.get("report_text")` | `ctx.get("planner_input_text") or ctx.get("report_text")` | 🟢 |
| 9 | `server.py:544` UML detect | `detect_needs_uml(report_text)` | `detect_needs_uml(planner_input)` | 🟡 |

### 验收

- 合体文档 replan 后步骤与原始计划一致
- Reflect 审稿能检测到"代码与实验要求不符"
- Revise 修订后内容符合实验要求
- UML 检测能识别题目文本中的"类图"/"时序图"

---

## BF12 — revise_answer 不支持 code_files（P1 副作用）

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（reflect → revise → reflect 循环，代码始终修不好）  
**影响范围**：所有 Agent 模式的 reflect→revise 和手动修订

### 症状

1. Reflect 正确识别代码问题（"未实现局部访问特性"、"未使用结构体数组"）
2. Revise 执行后 → 第二轮 Reflect 再次报不同代码问题
3. 循环 2 轮后放弃，最终的代码仍未正确
4. 用户看到"输出一致性检测：部分数值与预期偏差较大"

### 根因

P1 改 prompt 让 AI 输出 `code_files` 数组后，`revise_answer` 模块有三个遗漏：

**1. Scope 映射遗漏 `code_files`**（`_SCOPE_FIELDS`）：
```python
# 修复前
"code": ["code", "language"],

# 修复后
"code": ["code", "code_files", "main_file", "language"],
```

**2. 合并后双向同步缺失**：如果 LLM 返回 `{"code": "新的正确代码"}` 但没有 `code_files`，旧的 `code_files` 数组原封不动保留在 `merged` 中。后续 `complete_lab_parsed` 看到 `code_files` 有值就不会从 `code` 重建，导致多文件路径拿到的是旧代码。

**3. REVISE_USER prompt** 未明确提 `code_files`/`main_file`，LLM 可能只输出 `code` 字段。

### 修复

**文件**：`src/python/modules/revise_answer.py`（+12 行）、`src/python/agent/prompts.py`（±1 行）

1. `_SCOPE_FIELDS` — `code` 和 `full` scope 加入 `code_files`、`main_file`
2. 合并循环后新增同步逻辑：`code` 变化但 `code_files` 未变化时，更新 `code_files[main_idx].code`
3. REVISE_USER prompt — 注明 `code_files/main_file` 用法

### 验收

- Reflect 发现代码问题 → Revise → 代码正确修改 → 第二轮 Reflect 通过
- 手动修订代码字段 → 保存后运行正常

---

## BF13 — 实训表格"实训任务"标签不在填表关键字中

**发现时间**：2026-06-04  
**严重度**：🔴 阻断（实训表格填表返回空）  
**影响范围**：label 为"实训任务"的实训报告模版

### 症状

```
training_table: no fill-target cells found in table_map
```

解析时正确检测到 `layout=training_table`，但填表时找不到可填单元格。

### 根因

`_TRAINING_TABLE_MARKERS`（检测用）包含 `"实训任务"`，但 `_training_fill_targets`（填表用）的关键字列表缺少 `"实训任务"`。检测通过但填表匹配失败。

### 修复

**文件**：`src/python/modules/fill_report.py` ±1

`_training_fill_targets` 关键字列表增加 `"实训任务"`。

---

## BF14 — JSP/HTML 混入 Java 代码未检测

**发现时间**：2026-06-04（日志 `UploadServletIO.java:2: 错误: 需要 class...`）  
**严重度**：🔴 阻断（JSP/HTML 模板混入 Java 代码 → 编译失败 → 截图空白）  
**影响范围**：LLM 生成 Web 相关 Java 代码时

### 症状

```
[19:16:31][ERROR][java] UploadServletIO.java:2: 错误: 需要 class、interface、enum 或 record
<%@ page language="java" contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
```

LLM 生成了 JSP/Servlet 混合代码，`javac` 无法编译。

### 修复

**7 个文件**：

| 文件 | 改动 |
|------|------|
| `prompts.py` | `LAB_REPORT_USER` 末尾新增「代码环境约束」块：默认禁止 Servlet/JSP/HTML 混入 Java，仅 Web 实验可用 `HttpServer` + 独立 HTML |
| `preflight.py` | `_check_execution_pattern` 新增 `jsp_template` 检测：`<%@ page`, `<html>`, `<form>` 等标记混入 Java |
| `executor.py` | `jsp_template` → 跳过执行，category=`compile_error` |
| `fix_code.py` | 新增 `jsp_template` 修复策略："移除模板部分，改为纯 Java 独立程序" |
| `deep_pipeline.py` | SSE preflight 事件携带 `exec_pattern`/`exec_message` 供前端弹窗 |
| `app.js` | preflight SSE 事件处理：代码模式有问题时 showToast；run_code 失败时也弹 toast |
| `server.py` | `/api/run-code` 已通过 `_check_execution_pattern` 自动受益 |

**前端弹窗效果**：
- 预检发现问题 → toast: "代码混合了 JSP/HTML，无法作为纯 Java 编译"
- run_code 被阻止 → toast: "代码编译失败，将在修复后重试"

---

## BF15 — training_table 填充验证假阴性

**发现时间**：2026-06-05  
**严重度**：🔴 阻断（ReAct 模式下 training_table 报告 fill_report 验证始终失败）  
**影响范围**：所有 `report_layout=training_table` 的实训报告

### 症状

```
填充后验证失败：文档中未找到答案关键字，fill_report 可能未生效（内容未匹配到任何节）
```

但进度日志显示 fill_report 实际成功填入了内容：
- `training_table fill: filled 6 cell(s)`
- `已插入实验结果截图 1 张`
- 输出文件已正确保存

### 根因

`_verify_fill_output()` 提取文档全文时只遍历 `doc.paragraphs`，不包含表格单元格内的段落。对于 training_table 布局，`_fill_training_table()` 将答案内容全部写入 `cell.paragraphs[0].text`，这些文本对 `_verify_fill_output()` 不可见。

两个检查均因此失败：
1. **字符数检查**（`char_count < 100`）：`doc.paragraphs` 只有少量节标题，总长度不足 100 字符
2. **关键词检查**：答案关键字在 full_text 中不存在（因为它们都在表格单元格里）

### 修复

**文件**：`src/python/agent/executor.py` `_verify_fill_output()`（+5 行）

`full_text` 构建逻辑从仅遍历 `doc.paragraphs` 扩展为同时遍历 `doc.tables` 所有单元格段落，确保表格型报告的填充内容也参与验证。对非表格报告无影响（空 tables 列表不产生额外内容）。

### 验收

- 现有 176 个测试全部通过
- training_table 报告 fill_report 后验证不再假阴性

---

## BF16 — training_table fill_report 连续 3 次 IndexError（合并单元格 crash）

**发现时间**：2026-06-05  
**严重度**：🔴 阻断（ReAct 模式下 training_table 报告每次 fill_report 都崩溃，连续 3 次后 Agent 降级退出）  
**影响范围**：所有含垂直合并单元格的训练表格模型训练报告

### 症状

```
(LLM 自述) 连续两次 fill_report 失败，list index out of range
(LLM 自述) 报告填充失败：listindexoutofrange
(日志) consecutive failures=3, falling back
```

LLM 重试了 3 次 fill_report 全部抛出 `IndexError: list index out of range`，触发 3 次连续失败降级。但日志中**没有堆栈信息**，无法直接定位崩溃点。

### 根因

**4 个独立缺陷**：

1. **`_fill_training_table` `cell.paragraphs[0]` 崩溃**（`fill_report.py:313`）
   - 垂直合并的 Word 单元格可能没有 `<w:p>` 子元素（paragraphs 列表为空）
   - `cell.paragraphs[0]` 直接索引触发 `IndexError`
   - 这是 `list index out of range` 的直接原因

2. **图片插入路径 `last_cell.paragraphs[-1]` 崩溃**（`fill_report.py:325,333`）
   - 填表后插入截图的代码同样对空 paragraphs 不做防护
   - 即使第 1 点修复了，这里也会在截图阶段崩溃

3. **ReAct 工具分发器静默吞异常**（`react_tools.py:125`）
   - `dispatch_tool` 的 `except Exception` 只返回 `"工具执行异常: {e}"`，不写日志
   - `list index out of range` 的错误消息不含任何定位信息，LLM 无法自我诊断
   - 应用日志中完全找不到堆栈，问题排查只能靠猜

4. **fill_report 异常处理丢失类型信息**（`executor.py:678,706`）
   - `_run_fill_report` 两个 `except` 分支只传了 `str(e)`，丢失异常类型名
   - 也没有写日志，和问题 3 叠加造成完全盲区

### 修复

**3 个文件**：

| 文件 | 改动 |
|------|------|
| `modules/fill_report.py` | (1) `cell.paragraphs[0].text = combined` → 加 `if cell.paragraphs` 守卫，空时 `cell.add_paragraph(combined)`；(2) `last_cell.paragraphs[-1]` ×2 → 加守卫并 fallback 到 `add_paragraph("")`；(3) `_insert_image_after` 移除冗余 `getparent().remove()` + 重复 `addnext` |
| `agent/react_tools.py` | `dispatch_tool` except 分支新增 `loge()` + `traceback.format_exc()`，异常信息现在写入应用日志 |
| `agent/executor.py` | `_run_fill_report` 两个 except 分支新增 `loge()` + `traceback.format_exc()`；错误消息格式改为 `f"{type(e).__name__}: {e}"` |

### 验收

- 现有 176 个测试全部通过
- 下次出现异常时日志会有完整堆栈，即使不修代码也能快速定位
- 合并单元格的表格不再 crash
- 冗余 XML 操作清理后图片插入更稳定

---

## BF17 — 节号语义未识别「实验任务」+ 列表项污染节检测

**发现时间**：2026-06-05  
**严重度**：🔴 阻断（MyBatis 等模版 `二、实验任务` 填表落空；`1.掌握…` 被当成独立节）  
**影响范围**：段落型非标准节号报告（ReAct / `/api/fill-report`）

### 症状

```
section_map={'steps': None, 'result': None, 'summary': None}
检测到: ['一、实验目的', '1.掌握MyBatis…', '2.掌握MyBatis…', '二、实验任务']
```

核心答案写入错误节或完全不写入。

### 根因

1. `_SEMANTIC_KEYWORDS["steps"]` 不含「任务」，「二、实验任务」无法映射为 `steps`
2. `detect_sections` 将 `1.xxx` / `2.xxx` 阿拉伯数字列表项当作节标题（`semantic=None` 仍入库）
3. 解析得到的 `section_map` / `semantic_overrides` 未写入 document_store，也未随 `agent/run` 传给 `fill_report`

### 修复

| 文件 | 改动 |
|------|------|
| `modules/fill_report.py` | `任务`→steps、`小结`→summary；阿拉伯数字子项无语义则跳过；`_resolve_fill_sections()` 合并缓存映射与 DA4 覆盖；核心节未匹配时 `ValueError` |
| `agent/parse_documents.py` | 解析后 `detect_docx_sections` 结果写入 bundle metadata |
| `server.py` | `/api/agent/run` 合并 `sections_detected` / `section_map` / `semantic_overrides` 等 |
| `src/renderer/app.js` | `getSectionContextPayload()` 随 run 提交；`buildFillMetadata()` 供填表 |

---

## BF18 — ReAct `run_code` 空输出误判成功

**发现时间**：2026-06-05  
**严重度**：🟡 中等（`exit=0` 但 `out=` 为空时 Agent 反复 `fix_code` 空转）  
**影响范围**：ReAct 模式 Java/SQLite 等无 stdout 场景

### 修复

`agent/react_tools.py`：`exit=0` 且输出为空时标记为失败，提示 LLM 检查依赖/classpath。

---

## BF19 — 「生成完整报告」未传 training_table metadata

**发现时间**：2026-06-05  
**严重度**：🔴 阻断（Agent 填表成功，点 Step3「生成完整报告」失败）  
**影响范围**：`training_table` 实训周报告 + 非 Agent 填表路径

### 症状

```
报告生成失败: 核心节（步骤/结果/总结）未能匹配到文档标题… 检测到: []
```

ReAct 日志显示 `training_table: filled 6 cell(s)` 已成功，但 `/api/fill-report` 走段落路径、`sections_detected=0`。

### 根因

`buildFillReportPayload()` 普通 docx 分支未设置 `payload.metadata`（缺 `report_layout` / `table_map`）。

### 修复

| 文件 | 改动 |
|------|------|
| `src/renderer/app.js` | `buildFillMetadata()` 统一附带 `report_layout`、`table_map`、节映射等 |
| `modules/fill_report.py` | metadata 缺失时 `_detect_table_layout(doc)` 自动走 `training_table` |

---

## BF20 — 思考过程仅 UI 展示、无法留存

**发现时间**：2026-06-05  
**严重度**：🟡 体验（ReAct 多轮建议刷新后丢失）  
**影响范围**：思考过程侧栏、历史复盘

### 交付

| 文件 | 改动 |
|------|------|
| `main.js` / `preload.js` | IPC：`write-thought-log`、`save-text-dialog` |
| `src/renderer/app.js` | `agentThoughtLog` 结构化记录；运行结束自动保存；侧栏/Step4 导出 |
| `src/renderer/index.html` | 侧栏「导出」、Step4「导出/打开思考过程」 |
| `agent/react_loop.py` | `done` 事件附带完整 `thought_trace` + `decision_log` |
| `agent/react_tools.py` | SSE 单条上限放宽（思考 8000 / 结果 2000 字） |

自动保存目录：`%APPDATA%\lab-solver\thought_logs\`。

---

## BF21 — 超星式空表格模版填表失败（实验内容 / UML 未写入）

**发现时间**：2026-06-05（用户 ReAct 思考过程：`fill_report` 两次失败，`检测到: []`）  
**严重度**：🔴 阻断 — 解题/截图/UML 均成功但无法写回 Word  
**影响范围**：表格型实验报告（仅 **实验名 / 实验目的 / 实验内容**，无「三/四/五」段落）

### 现象

- `render_uml` 成功（如 3 张类图），`fill_report` 报错：`核心节（步骤/结果/总结）未能匹配到文档标题`
- 根因：**不是**缺少 UML 插入能力，而是模版未识别为 `training_table`，走了段落填表且 `sections_detected=[]`

### 修复

| 文件 | 改动 |
|------|------|
| `parse_report.py` | `_TRAINING_TABLE_MARKERS` 增加 `实验内容` / `实验目的` / `实验名`；`实验名` 精确匹配防误报「实验名称」 |
| `fill_report.py` | `_training_fill_targets` 分语义：`steps`→实验内容、`objective`→实验目的、`experiment_name`→实验名；UML/截图插入 **实验内容** 格；多列表格 label→value 写入 |

Fixture：`tests/fixtures/lab_report_table.docx`；测试：`test_da3_fill.py::test_lab_report_table_fill`。

---

## BF22 — ReAct 耗尽在 run_code/fix，未填表且无图片

**发现时间**：2026-06-05（设计模式实验 12 轮全用于 fix_code，无 render_uml/screenshot/fill_report）  
**严重度**：🔴 阻断  
**影响范围**：ReAct 模式 + 多文件 Java / 设计模式类实验

### 现象

- 思考过程 12/12 轮均为 `run_code` / `fix_code`，**从未**调用 `render_uml`、`screenshot`、`fill_report`
- 即使用户看到「有文档」，也常无 UML/截图（表格单元格内 `addnext` 插图失败被静默吞掉）

### 修复

| 文件 | 改动 |
|------|------|
| `agent/react_finalize.py` | 循环结束后**自动补跑**计划内缺失的 UML / 截图 / 填表 |
| `agent/react_tools.py` | 新工具 **`finalize_report`**（一键 UML→截图→填表） |
| `agent/react_loop.py` | 轮次 16；run_code 失败 4 次注入「请 finalize_report」；收尾流水线 |
| `agent/react_prompts.py` | 填表优先；run_code 非阻塞 |
| `fill_report.py` | `_insert_images_in_cell` 在表格**单元格内**插图 |

---

## BF23 — 表格「实验目的」误填为步骤摘要或 LLM 随机内容

**发现时间**：2026-06-05（创建型设计模式实验：题目含「实验目的与原理」三条，填表却写入「简单工厂模式实现…」等无关内容）  
**严重度**：🟠 内容错误 — 填表成功但实验目的与题目不符  
**影响范围**：超星式表格模版（**实验目的** 格）；段落型报告中 `semantic=objective` 的节

### 现象

- 题目/粘贴文本明确包含 `（1）实验目的与原理` 及①②③条目
- 报告模版「实验目的」行被填入 AI 解题 `steps_analysis` 首段，或由 `_fill_other_section` LLM 重新编造

### 根因

`fill_lab` 将 `objective_text = steps_analysis.split("\n\n")[0]`，未读取 `assignment_text`；`metadata` 填表链路未透传 `assignment_text`。

### 修复

| 文件 | 改动 |
|------|------|
| `fill_report.py` | `extract_objective_from_assignment()` / `_resolve_objective_text()`；表格与段落 `objective` 节优先用题目原文 |
| `executor.py` | `_run_fill_report` 将 `ctx.assignment_text` 写入 `metadata` |
| `app.js` | `agentAssignmentText` + `buildFillMetadata()` 附带 `assignment_text` |
| `tests/test_da3_fill.py` | `TestObjectiveExtraction`；`test_lab_report_table_fill` 断言题目目的而非步骤首段 |

---

## BF24 — 生成代码含 emoji 导致 Windows GBK 运行/日志崩溃（加固）

**发现时间**：2026-06-06（设计模式实验 ReAct：`run_code` 报 `'gbk' codec can't encode '\u274c'`）  
**严重度**：🟡 高 — 浪费 fix_code 轮次，偶发阻断 run_code / 日志  
**影响范围**：LLM 在 `System.out.println` 中使用 ✅❌ 等符号；`run_code.py` 错误前缀含 emoji

### 症状

- ReAct 第 3 轮 `run_code` 失败：`regenerated run error: 'gbk' codec can't encode character '\u274c'`
- Agent 需额外调用 `fix_code` 手动要求「移除 emoji」才能继续

### 根因

1. **生成侧**：`solve_lab` prompt 未禁止 emoji，LLM 常在演示输出里加 ❌✅  
2. **预检缺失**：`preflight` 未检测代码中的 emoji，直接执行  
3. **运行侧**：`run_code.py` 错误信息前缀使用 ❌；`log_util.print` 在 GBK 控制台下遇 emoji 抛 `UnicodeEncodeError`

### 修复

| 层 | 文件 | 改动 |
|----|------|------|
| 工具 | `text_sanitize.py` | `find_emoji` / `strip_emoji` / `ascii_safe` |
| Prompt | `agent/prompts.py`, `react_prompts.py` | 禁止代码及 println 输出使用 emoji |
| 预检 | `modules/preflight.py` | `pattern=emoji_in_code` 阻断执行 |
| 修复策略 | `modules/fix_code.py` | `emoji_in_code` 专用 fix 策略 |
| 运行 | `modules/run_code.py` | 错误前缀改为 `[ERR]`，超时标记 `[TIMEOUT]` |
| 日志 | `log_util.py` | `sanitize_log_message` 去 emoji + `_safe_print` GBK 兜底 |
| 其它 | `executor.py`, `server.py`, `screenshot.py`, `app.js` | 去除/兼容 emoji 标记 |

### 验收

- `pytest tests/test_text_sanitize.py` 通过  
- 含 `System.out.println("❌")` 的 Java 在 preflight 被 `emoji_in_code` 拦截  
- `logi("test", "含 emoji ❌")` 在 Windows GBK 终端不抛异常

---

## BF25 — 工具箱「修复代码」结果未同步到「运行代码」

**发现时间**：2026-06-06（用户反馈：修复代码显示成功，但 #3 仍执行旧代码）  
**严重度**：🔴 高 — 无法在工具箱内验证修复是否有效，阻断手动调试流程  
**影响范围**：工具箱模式辅助工具「修复代码」→ `#3 运行代码` 数据流

### 症状

- `#3 运行代码` 失败后，使用底部「🔧 修复代码」工具，状态显示 ✅ 成功
- 再次执行 `#3` 仍报相同错误；展开输入框可见仍是修复前的代码
- 修复结果仅存在于 fix 工具自己的输出 JSON，未进入 run 的输入

### 根因

`executeTool('fix')` 成功后将 payload 写入 `toolState.fix.output`，但未：

1. 合并到 `toolState.solve.output.code`（`resolveToolInput('run')` 的数据源）
2. 更新 `toolState.run.input`（`buildToolCardHtml` 首次渲染后 input 已缓存旧代码，优先于 resolve）
3. 将 `#3` / `#4` / `#6` 标记为 stale

`markDownstreamStale('fix')` 无效，因 `fix` 不在顺序链 `['parse','solve','run',…]` 中。

### 修复

| 文件 | 改动 |
|------|------|
| `app.js` | 新增 `propagateFixedCodeToToolbox()`；`executeTool` 在 `toolId === 'fix'` 成功时调用；Toast 提示重新执行 #3 |

行为与已有 `fixDiagramsTool()` 回写 solve 的模式一致。

### 验收

- 修复代码成功后，`#3` 输入框显示新代码，`#3` 状态为 stale 或需重跑
- 重新执行 `#3` 使用修复后代码，不再重复旧错误

---

## BF26 — 移除运行截图（V5-5 产品决策）

**发现时间**：2026-06-06（产品复盘：IDE/终端假截图与用户真实环境不符，且偏离 V5「用户自行落笔」定位）  
**严重度**：🟡 中 — 功能删除，非 bug 修复  
**影响范围**：全栈（后端模块、Agent 计划/ReAct、工具箱、代码面板、设置页）

### 变更摘要

| 删除 | 保留 |
|------|------|
| `ide_render.py`、`modules/screenshot.py` | UML / DFD 图表渲染（`render_uml`） |
| Agent 模块 `screenshot_ide` / `screenshot_terminal` | 用户分节工作台手动上传结果图 |
| API：`/api/tool/screenshot`、`/api/run-and-screenshot` 等 | `fill_report` 插入用户提供的 `images_b64` |
| UI：工具箱 #4 截图、运行+截图、截图/终端样式设置 | 内化验证 `sample_stdout` → 结果说明 |

ReAct `react_finalize_pipeline` 补跑项改为：`render_uml` → `present_deliverable` / `fill_report`（无截图）。

详见 `../product/V5_PRODUCT_PIVOT.md` §V5-5、`CLAUDE.md` 实现状态。

---

## BF27 — ReAct 循环内 `present_deliverable` 报「未知工具」

**发现时间**：2026-06-06（运行「实验六 页面置换算法」ReAct 模式；思考过程导出 `d7922270-…`）  
**严重度**：🟡 中 — Agent 主路径终点工具在循环内不可调用，被迫 `done` 后依赖收尾补跑  
**影响范围**：`agent/registry.py` · `agent/react_tools.py` · `tests/test_registry.py`

### 现象

- ReAct 第 3 轮 LLM 按提示调用 `present_deliverable` → 观察结果：`未知工具: present_deliverable`
- Agent 第 4 轮改调 `done` 结束；orchestrator 收尾阶段才补跑 `present_deliverable`（思考过程显示为额外一轮「ReAct 未执行」）
- 系统 prompt / plan checklist 已宣传该工具，但执行层未注册

### 根因

`MODULE_REGISTRY` 中 `present_deliverable` 的 `react_alias=None`。`react_tool_schemas()` 与 `react_action_to_module()` 仅收录带 `react_alias` 的模块，故 ReAct 主循环无法分发；`executor._run_present_deliverable` 与收尾 `run_finalize` 本身正常。

### 修复

| 文件 | 变更 |
|------|------|
| `agent/registry.py` | `present_deliverable` 增加 `react_alias="present_deliverable"` 与 `react_description` |
| `agent/react_tools.py` | `_format_result_summary` 增加 `present_deliverable` 专用摘要 |
| `tests/test_registry.py` | ReAct schema 集合与 alias 映射断言补全 |

### 验收

- `react_action_to_module("present_deliverable")` → `"present_deliverable"`
- `present_deliverable` ∈ `react_tool_schemas()` 键集合（共 8 个原子工具 + `finalize_report`）
- ReAct 循环内可直接调用，收尾补跑仅作兜底（UML / 用户未勾选时的缺失项）

---

## BF28 — SSE 正常结束时误报「连接中断」

**发现时间**：2026-06-06（运行逻辑审查 RL1）  
**严重度**：🟠 高（假阳性 — 成功任务也弹错误 Toast）  
**影响范围**：全部 Agent 模式 · `src/renderer/app.js`  
**关联**：[RUNTIME_LOGIC_ISSUES.md](../architecture/RUNTIME_LOGIC_ISSUES.md) RL1

### 现象

任务正常完成、答案已生成，仍弹出「SSE 连接中断，请查看后端日志」。

### 根因

服务端 `done` 后关闭 SSE 流，浏览器 `EventSource.onerror` 常在 `agentRunId` 清空前触发；`es.onerror` 此前仅判断 `agentRunId` 存在即 Toast。

### 修复

| 文件 | 变更 |
|------|------|
| `app.js` | `agentSseClosingGracefully`；`done`/`cancelled` 同步置位；`onerror` 跳过优雅关闭 |

### 验收

- 标准 / 深度 / ReAct 跑通后无假阳性 Toast；真中断（杀后端）仍有提示  
- `tests/test_runtime_logic.py::TestRL1SseGracefulClose`

---

## BF29 — ReAct fallback 成功后 `done.ok` 仍为 false

**发现时间**：2026-06-06（RL2）  
**严重度**：🟠 高  
**影响范围**：ReAct + `fallback_on_failure: true` · `agent/react_loop.py`

### 现象

主循环 `solve_lab` 失败、收尾 `fallback_to_solve` 成功，前端仍显示「执行未完全成功」。

### 根因

`any_solve` 在 fallback **之前**读取，构建 `final["ok"]` 未重算。

### 修复

`fallback_to_solve` 后重读 `module_results.solve_lab.ok`。

### 验收

- ReAct 仅 fallback 成功时 `done.ok === true`  
- `tests/test_runtime_logic.py::TestRL2ReactFallbackDoneOk`

---

## BF30 — 标准模式 `done.ok` 恒为 true

**发现时间**：2026-06-06（RL3）  
**严重度**：🟠 高  
**影响范围**：标准模式 orchestrator + legacy · `agent/executor.py`

### 现象

`solve_lab` / `run_code` 失败，UI 仍走成功收尾。

### 根因

`_execute_standard_via_orchestrator` / legacy 末尾固定 `emit({"type": "done", "ok": True, ...})`。

### 修复

新增 `_standard_run_ok(ctx)`（`solve_lab` ∨ `solve_theory`）；`fill_report` 等非核心失败不拉低 `ok`。

### 验收

- solve 失败且无 fallback → `done.ok: false`  
- `tests/test_runtime_logic.py::TestRL3StandardRunDoneOk`

---

## BF31 — 执行阶段 `document_ids` 失效无兜底

**发现时间**：2026-06-06（RL4；补 BF1 plan→run 缺口）  
**严重度**：🟠 高  
**影响范围**：生成计划后隔一段时间再执行、或后端重启后执行

### 现象

点击「执行计划」报错：`文档缓存已过期或不存在: <uuid>`。

### 根因

`document_store._store` 内存 TTL / 重启清空；执行时仅传 `document_ids` 不重传文件（BF1 已修 parse→plan，未覆盖 plan→run）。

### 修复

| 文件 | 变更 |
|------|------|
| `server.py` | `/api/agent/run` 缓存失效时 400 + `stale_documents: true` |
| `app.js` | `postAgentRunWithDocRetry`；`buildAgentDocumentPayload({ forceReupload: true })`；`executeAgentPlan` / `runAgentPartialRerun` 接入 |

### 验收

- 计划已生成 → 重启后端 → 执行：自动重传并启动（本地仍有 `uploadedDocuments` / `currentFile`）  
- `tests/test_runtime_logic.py::TestRL4StaleDocumentRetry`

---

## BF32 — `solve_lab` 执行中无 V4 子阶段进度

**发现时间**：2026-06-06（RL5）  
**严重度**：🟡 中  
**影响范围**：标准 / 深度 / ReAct 中含代码实验的 `solve_lab` 步骤

### 现象

`solve_lab` 侧栏长期显示「执行中…」，用户不知当前在生成代码、跑沙箱还是写报告。

### 根因

`executor._run_solve_lab` 的 `on_phase` 仅写入 `ctx.pipeline_phases`，未 `emit_event`；前端无 `pipeline_phase` 处理。

### 修复

| 文件 | 变更 |
|------|------|
| `executor.py` | `on_phase` 推送 SSE `type: pipeline_phase` |
| `app.js` | `PIPELINE_PHASE_LABELS` + `handleAgentSSEEvent` 更新 Step3 详情 / 思考侧栏 |

### 验收

- 含代码实验时可见：`读题对齐` → `生成代码` → `内化验证` → `撰写报告`  
- `tests/test_runtime_logic.py::TestRL5PipelinePhaseSse`

---

## BF33 — V4 已内化验证后计划仍重复 `run_code`

**发现时间**：2026-06-06（RL6）  
**严重度**：🟡 中  
**影响范围**：默认 V4 pipeline + Planner 含 `run_code` 的计划

### 现象

`solve_lab` 内已验证/修复代码，计划又执行 `run_code`，浪费轮次且可能再次失败触发 `fix_code`。

### 根因

Planner / fallback 在报告含「代码/运行」时仍默认勾选 `run_code`；`executor._run_run_code` 未检测 `solve_session.code_status === verified`。

### 修复

| 文件 | 变更 |
|------|------|
| `planner.py` | `adjust_plan_for_v4_pipeline`；fallback 默认不勾 `run_code` |
| `prompts.py` | Planner 规则说明 V4 已含内化验证 |
| `executor.py` | `code_status=verified` 时复用 sandbox 结果并跳过执行 |

### 验收

- 默认计划：代码题仅一次内化验证；`run_code` 为可选高级步骤  
- `tests/test_runtime_logic.py::TestRL6RunCodeDedup`

---

## BF34 — ReAct `run_code` 失败提示与 V5 deliverable 矛盾

**发现时间**：2026-06-06（RL9）  
**严重度**：🟡 中  
**影响范围**：ReAct + `output_mode=deliverable`（默认）

### 现象

`run_code` 多次失败后注入：「实验报告类作业必须产出 Word 文档…」，与 V5「答案工作区复制、fill 为高级」矛盾。

### 根因

`react_loop.py`  escalation 提示写死 Word/fill_report，未按 `output_mode` 分支。

### 修复

| 文件 | 变更 |
|------|------|
| `react_loop.py` | deliverable 模式引导 `present_deliverable`，不提 Word 强制 |
| `react_prompts.py` | `build_plan_checklist` 按 `output_mode` 区分交付规则 |

### 验收

- deliverable 模式下 escalation 不含「必须产出 Word」  
- `tests/test_runtime_logic.py::TestRL9ReactDeliverablePrompts`

---

## BF35 — 三模式 `done.ok` 语义分裂（`compute_run_ok`）

**发现时间**：2026-06-06（RL7）  
**严重度**：🟡 中（维护债）  
**影响范围**：标准 / 深度 / ReAct 收尾状态不一致，修一处易漏一处

### 修复

| 文件 | 变更 |
|------|------|
| `agent/run_result.py` | 新增 `compute_run_ok(ctx)` |
| `executor.py` | `_standard_run_ok` 委托共用函数 |
| `deep_pipeline.py` / `react_loop.py` | `done.ok` 统一读 `compute_run_ok` |

### 验收

- `tests/test_runtime_logic.py::TestRL7ComputeRunOk`

---

## BF36 — Agent 执行中 JAR 同意仅跑完后弹窗

**发现时间**：2026-06-06（RL8）  
**严重度**：🟡 中  
**影响范围**：Java + `allow_curated_jars` + Agent `solve_lab` 内化验证

### 现象

验证因 `missing_jar` 跳过，用户跑完才在答案工作区看到补救弹窗。

### 修复

| 文件 | 变更 |
|------|------|
| `run_control.py` | `wait_for_jar_consent` / `respond_jar_consent` |
| `executor.py` | `allow_curated_jars` 时传 `on_jar_consent` |
| `server.py` | `POST /api/agent/jar-consent` |
| `app.js` | 处理 `jar_consent_required` SSE，中途弹窗并回传 |

### 验收

- `tests/test_runtime_logic.py::TestRL8JarConsentMidRun`

---

## BF37 — SSE 断开后无法恢复进度

**发现时间**：2026-06-06（RL10）  
**严重度**：🟡 中  
**影响范围**：长跑 / 网络抖动（单任务锁未改）

### 修复

| 文件 | 变更 |
|------|------|
| `run_control.py` | `event_log` + `get_run_events`；`iter_events(since=)` |
| `server.py` | `GET /api/agent/run-status`；events 支持 `since` |
| `app.js` | `agentSseEventIndex`、自动重连 3 次、启动文案提示勿刷新 |

### 验收

- `tests/test_runtime_logic.py::TestRL10SseReplay`

---

## BF38 — 深度模式 verify 未过但解题成功仍标失败

**发现时间**：2026-06-06（RL12）  
**严重度**：🟢 低  
**影响范围**：深度模式 `done.ok`

### 根因

`ok = verify.passed ∧ solve_ok`，与标准模式（仅看 solve 成败）不一致。

### 修复

`deep_pipeline.py` 末尾 `ok` 改为 `compute_run_ok(ctx)`；verify 结果仍经 `verification_report` 展示。

### 验收

- `tests/test_runtime_logic.py::TestRL12DeepDoneOk`

---

## BF39 — 启动时 5s 超时抢先调后端 API

**发现时间**：2026-06-06（RL11）  
**严重度**：🟢 低  
**影响范围**：应用冷启动、后端慢启动

### 现象

后端尚未就绪时，加载页消失后合规检测、日志路径等首批 API 静默失败；与「AI引擎就绪」Toast 时序不一致。

### 根因

`init()` 中 5s `setTimeout` 与 `onServerReady` 重复 bootstrap，且不等待 health/IPC 即调用 `fetchLogFilePath`、`runComplianceStartupSequence`。

### 修复

- 抽取 `runServerReadyBootstrap()` + `serverBootstrapDone` 单次守卫；
- 5s 超时仅 `hideLoading` + 本地 `loadSettings`/`renderHistory`；
- 新增 `pollServerHealth()` 作 `server-ready` IPC 慢到时的兜底；
- `onServerError` 设 `serverStartupFailed`，避免失败后仍轮询 bootstrap。

### 验收

- `tests/test_runtime_logic.py::TestRL11InitServerReady`

---

## BF40 — 三模式收尾与模块执行未共用 Orchestrator（RL7 全面编排）

**发现时间**：2026-06-06（RL7 续）  
**严重度**：🟡 中（维护债）  
**影响范围**：标准 / 深度 / ReAct 收尾链路、深度 tail legacy 循环、ReAct 工具直连 runner

### 根因

`done.ok` 虽已 `compute_run_ok` 统一，但 fallback → verify → `done` payload 三份拷贝；深度模式在 `orchestrator_enabled=false` 时仍内联 tail 循环；ReAct `execute_tool` 绕过 `RunOrchestrator`（无统一 decision/progress）。

### 修复

| 文件 | 变更 |
|------|------|
| `agent/run_result.py` | `complete_agent_run`、`build_run_done_payload`、`maybe_fallback_solve` |
| `executor.py` / `deep_pipeline.py` / `react_loop.py` | 收尾委托 `complete_agent_run` |
| `deep_pipeline.py` | tail 始终 `RunOrchestrator.run_steps`，删除 legacy 内联循环 |
| `react_loop.py` / `react_tools.py` | `ctx["_orchestrator"]`；工具经 `orch.run_module` |

### 验收

- `tests/test_runtime_logic.py::TestRL7ComputeRunOk`（含 `complete_agent_run` 顺序与三模式静态检查）

---

## BF41 — 刷新页面后 Agent 执行进度丢失

**发现时间**：2026-06-06（RL10 续）  
**严重度**：🟡 中  
**影响范围**：Step3 执行中刷新 / 崩溃后重开

### 现象

后端任务仍在跑，但前端 `agentRunId` 内存变量清空，进度条与 SSE 断开，用户无法取消或查看状态。

### 根因

RL10 仅实现同会话 SSE 重连；未持久化 `run_id`，启动时也未调用已有 `GET /api/agent/run-status` 恢复 UI。

### 修复

| 文件 | 变更 |
|------|------|
| `app.js` | `persistAgentActiveRun` / `tryRestoreAgentRunAfterLoad` / `clearAgentActiveRun`；`runServerReadyBootstrap` 触发恢复 |
| `run_control.py` | `get_active_run_id()` |
| `server.py` | `GET /api/agent/active-run` |

### 验收

- `tests/test_runtime_logic.py::TestRL10SseReplay`（含 active-run 与持久化静态检查）

---

## BF42 — Step 3 deliverable 完成后无回到主页入口

**发现时间**：2026-06-06  
**严重度**：🟡 中（UX）  
**影响范围**：Step 3 默认答案工作区主路径（`output_mode=deliverable`）

### 现象

Agent 执行完成并展示答案工作区后，用户无法明显回到 Step 1 开始新任务。仅 Word 填表成功时 `#exportSuccessPanel` 内有「处理新报告」；deliverable 主路径缺少同等入口。

### 根因

`startNew()` 仅挂在填表成功面板；`onSolveComplete()` 只展示 `#exportActionBar` 提示，无导航 CTA。

### 修复

| 文件 | 变更 |
|------|------|
| `index.html` | `#step3HomeBtn`（页头）、`#exportActionHomeBtn`（底栏） |
| `app.js` | `updateStep3CompletionActions()`；在 `finishAgentRunUI` / 执行开始 / `startNew` / 增量重跑时切换显示 |

### 验收

- deliverable 流程跑通后页头与底栏均可见「回到主页」
- 点击后回到 Step 1 且状态已重置（与「处理新报告」一致）
- 执行中与增量重跑时按钮隐藏

---

## BF44 — 仅粘贴题目时解析崩溃（`fill_target` 为 None）

**发现时间**：2026-06-08  
**严重度**：🔴 高（主路径阻断）  
**影响范围**：`POST /api/parse-report`，`assignment_only` 无 `fill_target`

### 现象

仅粘贴题目文字点「解析并继续」时报：`解析失败: 'NoneType' object has no attribute 'get'`。

### 根因

`server.py` `parse_report_route` 返回 JSON 时写死 `parsed["fill_target"].get("split_at_heading")`，`assignment_only` 场景 `fill_target` 为 `None`。

### 修复

```python
"split_at_heading": (parsed.get("fill_target") or {}).get("split_at_heading"),
```

`tests/test_phase2a2.py` 增加 `test_parse_report_route_assignment_only_text`。

---

## BF45 — 启动页长期停在「正在连接后端」（渲染层脚本崩溃 + ready 竞态）

**发现时间**：2026-06-08  
**严重度**：🔴 阻断（主界面无法进入）  
**影响范围**：Electron 启动阶段（Step0 loading overlay）

### 现象

- 后端日志显示已启动并健康检查 `200`（`/api/health` 正常）
- 页面仍停在启动遮罩「正在连接后端…」
- 控制台可复现语法错误：`Identifier 'copyBtn' has already been declared`

### 根因

1. `src/renderer/app.js` 中 `renderDeliverableWorkspace()` 重复声明 `const copyBtn`，导致渲染脚本初始化失败，`hideLoading()` 不执行。  
2. 启动握手依赖一次性 `server-ready` 事件，存在事件先发/监听后绑的竞态；即使后端已就绪，渲染层也可能错过 ready。

### 修复

| 文件 | 改动 |
|------|------|
| `src/renderer/app.js` | 删除重复 `copyBtn` 声明；启动时增加 `getServerStatus()` 主动状态拉取兜底 |
| `main.js` | 新增 `serverReady` / `serverStartError` 状态；新增 IPC `get-server-status` |
| `preload.js` | 暴露 `getServerStatus` 给渲染层 |

### 验收

- `node --check src/renderer/app.js` 通过（无语法错误）
- `npm run dev` 日志显示 `Python服务就绪` 且前端不再长期停在 loading
- 即使 `server-ready` 事件丢失，渲染层通过 `getServerStatus()` 仍能完成 bootstrap

---

## BF46 — 重新生成计划后仍报「计划已过期」

**发现时间**：2026-06-08  
**严重度**：🔴 阻断（标准模式无法启动执行）  
**影响范围**：Step2 识题预览编辑过 `assignment_text` 后的 plan→run

### 现象

- 用户已点击「生成计划」，立即执行仍返回：`计划已过期，请重新生成计划`
- 重生计划后再次执行，仍重复报错

### 根因

`plan_fingerprint` 基于 `planner_input_text` 计算。  
计划阶段 `/api/agent/plan` 已使用识题预览覆盖的 `assignment_text` 重建了 `planner_input_text`，但执行阶段 `/api/agent/run` 在仅传 `document_ids` 时没有应用同样覆盖，导致服务端重算指纹与计划阶段不一致，触发 `stale_plan` 假阳性。

### 修复

| 文件 | 改动 |
|------|------|
| `src/renderer/app.js` | `executeAgentPlan()` 请求体追加 `assignment_text: agentAssignmentText` |
| `src/python/server.py` | `/api/agent/run` 在 `resolve_agent_context(document_ids)` 后应用 `assignment_text` 覆盖（`apply_assignment_text_override`） |
| `src/renderer/app.js` | `postAgentRunWithDocRetry()` 在 `stale_plan` 且后端返回 `plan_fingerprint` 时自动重试 1 次 |

### 验收

- 在识题预览里编辑题干 → 生成计划 → 执行计划：不再立即报「计划已过期」
- 未编辑题干的普通场景行为不变

---

## BF47 — 代码完形题在合体/填表文档里漏检，误走普通编程题

**发现时间**：2026-06-08  
**严重度**：🔴 阻断（`code_cloze` 场景输出整段代码，未按空号）  
**影响范围**：`parse_documents_list` 多文档/合体文档路径（非纯 `assignment_only`）

### 现象

- 用户题面是“代码+编号空”，但计划仍走 `solve_lab` / ReAct 普通路径
- Step3 显示完整代码/报告分节，而非 `code_cloze` 空号答案工作区

### 根因

`parse_documents.py` 里 `code_cloze` 检测在一个关键分支仅对 `layout == "assignment_only"` 生效；当题干来自合体文档拆分出的 `assignment_text`（`fill_target` 存在）时，检测被跳过，`question.type` 保持 `lab_report`。

### 修复

| 文件 | 改动 |
|------|------|
| `src/python/agent/parse_documents.py` | 统一使用 `assignment_text` 作为优先检测源；在 fill_target 分支与 assignment_only 分支都补 `detect_code_cloze` 兜底，并回写 `question.type/metadata.code_cloze` |
| `src/python/server.py` | `/api/agent/plan` 与 `/api/agent/run` 增加 `code_cloze` 运行时二次判定，修复缓存题型陈旧导致的漏判 |
### 验收

- 合体文档（题干+模版）里含编号代码填空时，`question.type` 正确为 `code_cloze`
- 计划路径命中 `solve_code_cloze` + `present_deliverable`
- Step3 展示空号列表 + 复制全部空号答案

---

## BF55 — 代码完形填空 Step3 误显校验失败，约 30s 后才出现正确答案

**发现时间**：2026-06-09  
**严重度**：🟡 中（体验误导；答案实际已生成）  
**影响范围**：`code_cloze` 题型、Step 3、`verify_answer`、`auto_remediate`、标准/深度/ReAct 共用收尾

### 现象

执行到 100%（`solve_code_cloze` + `present_deliverable` 均完成）后，Step 3 先弹出「校验清单」红叉：缺少 `steps_analysis` / `result_description` / `summary` / `code`，并建议「强制重写」。用户以为解题失败；等待约半分钟后才出现空号答案工作区。

### 根因

1. **IR-9 副作用**：`verify_answer` 为 `code_cloze` 合并通用检查后，仍追加 `schema_complete`（实验报告四字段）与 `deliverable_ready`（三节正文），对完形填空恒为假失败。
2. **误触发 auto_remediate**：`revise_full` 映射到 `solve_lab`（非 `solve_code_cloze`），空跑一轮修复后才发 `done`。
3. **UI 时机**：`verification` SSE 在执行中即渲染失败面板，而 `deliverable` 要到 `done`（或 remediate 结束）才写入工作区。

### 修复

- `quality.py`：`code_cloze` 仅校验 `code_cloze_schema` + 通用项；`deliverable_ready` 改查 `blanks`；阻断项用 `code_cloze_schema` 替代 `schema_complete`。
- `executor_dirty.py`：完形填空 `revise_full` → `solve_code_cloze`。
- `executor_common.py`：`present_deliverable` 完成时 SSE `progress` 附带 `deliverable`。
- `app.js`：执行中不展示校验失败；`present_deliverable` 完成即渲染答案工作区。
- 测试：`tests/test_phase2b.py::test_verify_code_cloze_passes_without_lab_fields`。

### 验收

- Singleton / Facade 完形填空：进度 100% 后立即见空号列表，无「缺 steps_analysis」类红叉。
- 校验通过时不再误触发 `solve_lab` 重跑；`auto_remediate_rounds` 为 0。
- `pytest tests/test_phase2b.py` 通过。

---

## BF54 — 首次免责声明勾选框不可见，主按钮无法点击

**发现时间**：2026-06-08  
**严重度**：🔴 阻断（首次启动无法进入应用）  
**影响范围**：`compliance-ux.js` 首次免责弹窗、`#complianceModalCheckWrap`

### 现象

启动后弹出「免责声明」，「我已阅读并同意」按钮呈主色但点击无反应（实际为 `disabled`），用户无法继续。

### 根因

`index.html` 中 `#complianceModalCheckWrap` 带 `.is-hidden`（`display: none !important`）。`showAppModal()` 仅用 `checkWrap.style.display = 'flex'` 试图显示勾选框，被 `!important` 覆盖，勾选框始终隐藏；同时 `requireCheckbox: true` 使主按钮在未勾选时保持 `disabled`。

与 Pack F「动态面板用 `classList` 切换 `is-hidden`」约定不一致（`app.js` 的 `uiShow`/`uiHide` 已正确，合规模块未复用）。

### 修复

- `compliance-ux.js`：`showAppModal` 显示勾选区时 `classList.remove('is-hidden')`，隐藏/清理时 `classList.add('is-hidden')`

### 验收

- 清除 `localStorage.compliance` 后重启：弹窗底部可见「我已阅读并理解上述条款」勾选框  
- 未勾选时主按钮禁用；勾选后可点「我已阅读并同意」并关闭弹窗  
- JRE / jar 等复用 `complianceModal` 的弹窗仍正常（`app.js` 继续用 `uiHide(checkWrap)`）

---

## BF53 — docx 上传填空题在 fill_only 布局下漏写 metadata.code_cloze

**发现时间**：2026-06-08（R5 / Phase D 预检）  
**严重度**：🟡 中（Word 导入已 `build_question_from_document` 判 cloze，但 `parse_single_file` 二次探测用空 `assignment_text`）  
**影响范围**：含实训表格封面 + 代码填空的 `.docx`（`layout=fill_only`）

### 根因

`parse_single_file` 仅在 `layout == assignment_only` 时将 `cloze_source` 回退到 `full_text`；`fill_target` + `fill_only` 时 `assignment_text` 为空，二次 `detect_code_cloze("")` 失败，可能丢失 bundle 级 `metadata.code_cloze`（与 BF47 同类：检测层分叉未对齐）。

### 修复

- `parse_report.py`：`extract_docx_code_cloze_text` / `detect_code_cloze_for_docx` 按 body 顺序抽取表格/等宽段落代码段；`extract_docx` 写入 `metadata.code_cloze`  
- `parse_documents.py`：`assignment_text` 为空时一律回退 `full_text`；优先复用 `metadata.code_cloze` / `question.metadata.code_cloze`  
- `tests/fixtures/code_cloze_singleton.docx` + `test_phase2a2.py` R5 用例  

### 验收

- 上传 Singleton 填空 `.docx` → `question.type=code_cloze`，`blank_count >= 3`  
- `programming_lab.docx` → 仍 `lab_report`  

---

## BF52 — 遗留 `/api/solve` 未识别 code_cloze，恒走 solve_lab

**发现时间**：2026-06-08  
**严重度**：🟡 中（旧客户端 / Agent 降级路径粘贴填空题输出整段报告，无 `blanks`）  
**影响范围**：`POST /api/solve`（backward compat）

### 现象

通过遗留 `/api/solve` 提交 Singleton / Facade 填空题 → 返回 `lab_report` 结构，无 `type: code_cloze` 与 `blanks`。

### 根因

`solve()` 写死 `solve_lab()`，未复用 R2 `tool_solve` 的 `detect_code_cloze` → `call_ai(type=code_cloze)` 分支（与 BF51 同类）。

### 修复

- `server.py`：抽取 `_solve_text_cloze_or_lab` 供 `tool_solve` 与 `solve()` 共用  
- `solve()`：对 `question.full_text` / `text` 探测填空，cloze 走 `call_ai`，否则 `solve_lab`  

### 验收

- `/api/solve` + 填空例题 → `type: code_cloze` + `parsed.blanks`  
- 普通实验报告 → 仍 `solve_lab`，`include_code` / `include_uml` 行为不变  
- `tests/test_api_solve.py` 通过；`tests/test_toolbox.py::TestToolSolve` 无回归  

---

## BF51 — 工具箱 AI 解题未识别 code_cloze，恒走 solve_lab

**发现时间**：2026-06-08  
**严重度**：🟡 中（工具箱粘贴填空题输出整段实验报告，无空号结构）  
**影响范围**：`POST /api/tool/solve`、工具箱 #2 AI 解题

### 现象

粘贴 Singleton / Facade 等代码填空题到工具箱 → 执行 AI 解题 → 返回 `lab_report` 结构（`steps_analysis` / 整段代码），无 `blanks`。

### 根因

`tool_solve` 写死 `question.type = lab_report` 并调用 `solve_lab()`，未复用 `detect_code_cloze` 与 `call_ai(type=code_cloze)`（与 BF49/BF50 同类：检测/计划已有能力，独立入口未分支）。

### 修复

- `server.py` `tool_solve`：`detect_code_cloze(text)` → cloze 走 `call_ai`，否则 `solve_lab`；响应带 `type`  
- `app.js`：`formatSolveToolOutput` 在工具箱输出区展示空号列表  

### 验收

- 工具箱 + 填空例题 → `type: code_cloze` + `parsed.blanks`  
- 普通实验报告 → 仍 `type: lab_report`，`solve_lab` 行为不变  
- `tests/test_toolbox.py::TestToolSolve::test_code_cloze_branch` 通过  

---

## BF50 — 深度模式计划已是填空仍跑 solve_lab draft

**发现时间**：2026-06-08  
**严重度**：🟡 中（浪费 LLM 调用，可能污染 `module_results`）  
**影响范围**：`deep_pipeline.execute_deep_run`、code_cloze 深度执行路径

### 现象

计划步骤为 `solve_code_cloze` + `present_deliverable`，深度模式仍先 emit `solve_lab phase=draft`，再 tail 跑填空。

### 根因

`execute_deep_run` 在计划中无 `solve_lab` 时仍合成默认 `solve_lab` 步骤并进入 draft/reflect 块（与 BF49 同类：计划层已识别，执行层未分支）。

### 修复

- 新增 `agent/cloze_run.py`：`is_code_cloze_run` 与 ReAct 共用  
- `deep_pipeline.py`：填空计划跳过 draft/reflect，直接 `orch.run_steps(steps)`  
- `react_loop.py`：改为从 `cloze_run` 导入，避免重复判断逻辑

### 验收

- 深度 + 填空题：日志无 `solve_lab phase=draft`，仅 `solve_code_cloze` → `present_deliverable`  
- 普通 `lab_report` + 深度：仍走 `solve_lab` draft → reflect → tail  
- `tests/test_run_modes_golden.py::test_deep_mode_code_cloze_skips_solve_lab_draft` 通过

---

## BF49 — 计划识别填空但 ReAct 仍跑 solve_lab

**发现时间**：2026-06-08  
**严重度**：🔴 功能错误（填空题输出整段实验报告代码）  
**影响范围**：ReAct 执行、`present_deliverable`、Step3 工作区

### 现象

计划步骤为 `solve_code_cloze`，执行时 bootstrap 与 LLM 仍调用 `solve_lab`；Step3 显示步骤/代码报告布局，而非空号列表。

### 根因

1. `solve_code_cloze` 未注册 ReAct 工具（`react_alias=None`），LLM 无法调用  
2. `react_loop` AO-7 bootstrap 无条件跑 `solve_lab`  
3. `applyAgentRunDone` 只读 `solve_lab` 数据；`build_deliverable` 未写 `type`/`code_cloze` 字段

### 修复

- `registry.py`：注册 `solve_code_cloze` ReAct 工具  
- `react_loop.py`：填空计划 bootstrap `solve_code_cloze`  
- `react_prompts.py` / `react_tools.py`：填空专用规则与结果摘要  
- `deliverable.py`：交付物带 `type: code_cloze` 与 `code_cloze.blanks`  
- `app.js`：完成时优先 `solve_code_cloze` 结果

### 验收

- 填空题执行日志首步为 `solve_code_cloze OK`，Step3 为空号列表 UI

---

## BF48 — 执行计划报 `cannot access local variable 'ctx'`

**发现时间**：2026-06-08  
**严重度**：🔴 阻断（计划已识别 code_cloze，点执行即 500）  
**影响范围**：`POST /api/agent/run`（BF47 二次判定补丁引入）

### 现象

`启动执行失败: cannot access local variable 'ctx' where it is not associated with a value`

### 根因

`agent_run()` 在 `make_agent_context()` 之前用 `ctx.get(...)` 做 `code_cloze` 探测；`ctx` 此时尚未赋值，Python 3.11+ 抛 `UnboundLocalError`。

### 修复

`cloze_probe_text` 改为读取已存在的 `doc_ctx`（`assignment_text` / `planner_input_text` / `report_text`）。

### 验收

- 计划含 `solve_code_cloze` 时点击「执行计划」可正常启动 run，不再 500

---

## BF43 — Step1 仅粘贴文字不便 + Step3 代码/图只能 zip 下载

**发现时间**：2026-06-08  
**严重度**：🟡 中（UX）  
**影响范围**：Step 1 题目输入、Step 3 答案工作区预览栏

### 现象

1. 用户从超星复制题目后，仍感觉必须上传 docx；粘贴入口在弹窗/次要按钮，主界面强调「添加文档」。
2. 代码与 UML 图只能通过「下载代码 zip / 图表 zip」取出，无法在展示区直接复制。

### 修复

| 文件 | 变更 |
|------|------|
| `index.html` | Step1 `upload-mode-tab`（默认「粘贴题目」）+ `#uploadPasteText`；预览栏 `#copyPreviewBtn` |
| `app.js` | `setUploadInputMode` / `confirmUploadPaste`；`copyDeliverableCode` / `copyDeliverableDiagrams` 等 |
| `styles.css` | `.upload-paste-panel`、`.deliverable-preview-actions` |
| 文档 | `DESIGN.md`、`V5_PRODUCT_PIVOT.md`、`LAB_SOLVER_AGENT_PLAN.md` §3h、合规引导等 |

### 验收

- 仅粘贴题目文字 → 解析并继续 → 生成计划可跑通（`assignment_only`；若仍报 `NoneType .get`，见 **BF44**）
- 预览栏「复制代码」「复制图表」可用；多图可逐张复制
- zip 仍在「导出 ▾」，非唯一出口

---

## BF50 — 标准模式质量感知弱（默认不自动修复 + UI 无说明）

**发现时间**：2026-06-08  
**严重度**：🟡 中（体验 / 质量感知）  
**影响范围**：`run_mode=standard`、Step 2、设置页、`POST /api/agent/run`

### 现象

用户反馈标准模式「好像没用」「老生成错误答案」。技术上标准模式已走 V4 流水线与 `verify_answer`，但校验失败后**默认不** `auto_remediate`，且 Step 2 未展示质量保障说明，易被误认为「只生成一次、错了也不管」。

### 根因

1. `resolveAutoRemediateForRun()` 与 `server.py` 仅在 `deep` 时默认 `auto_remediate=true`
2. 设置「校验未通过时自动修复」默认未勾选且藏在高级区
3. Step 2 无当前模式 / 质量档位 / 保障项展示

### 修复

- `app.js`：`autoRemediate` 默认 `true`（schema v7 迁移）；`resolveAutoRemediateForRun` 尊重设置
- `server.py`：未传 `auto_remediate` 时 `standard`/`deep` 默认 `true`
- `index.html` + `styles.css`：`#step2ModeBanner` 质量说明条；标准模式卡片文案
- 校验 SSE / 执行结束 Toast 引导查看校验清单
- 文档：[STANDARD_MODE_QUALITY.md](../design/STANDARD_MODE_QUALITY.md)

### 验收

- Step 2 可见标准模式保障说明；设置默认勾选自动修复
- verify 失败时可触发 1 轮 auto_remediate（`tests/test_auto_remediate.py` 仍绿）

---

## IR-16 — 运行控制升级（落盘 + 可选队列）

**时间**：2026-06-09  
**条目**：[AGENT_IMPROVEMENT_RECOMMENDATIONS.md IR-16](../architecture/AGENT_IMPROVEMENT_RECOMMENDATIONS.md)

### 修复

| 文件 | 变更 |
|------|------|
| `run_event_store.py` | 新建：`{run_id}.jsonl` append / read / prune / `infer_status` |
| `run_control.py` | `try_acquire_or_queue`、FIFO drain、`run_exists`、落盘 hook |
| `config.py` | `RUN_EVENTS_DIR` |
| `server.py` | 队列模式、`queue_full`、events 支持磁盘 run |
| `executor.py` / `deep_pipeline.py` | daemon 线程 `agent-run-{id}` |
| `settings_schema.py` | `persistRunEvents`、`runQueueMode` 等 |

### 验收

- `tests/test_runtime_logic.py::TestIR16RunEventPersist`
- `tests/test_runtime_logic.py::TestIR16RunQueue`
- `tests/test_phase2a.py::test_run_fifo_queue_mode`

---

## 总结

*日志版本：2026-06-09（IR-16）。每次修复 bug 后更新本文档。RL1–RL12 详见 BF28–BF41 与 [RUNTIME_LOGIC_ISSUES.md](../architecture/RUNTIME_LOGIC_ISSUES.md)。*
