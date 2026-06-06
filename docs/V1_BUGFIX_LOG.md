# V1 错误修复日志

**用途**：记录 V1 版本从测试/使用中发现的 bug 及其修复。  
**最后更新**：2026-06-05

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
**来源文档**：[V2_CODE_EXECUTION_FIX.md](./V2_CODE_EXECUTION_FIX.md)

### 症状

上传纯实训表格 `.docx`（无"三/四/五"标题），`detect_combined_layout()` 回退为 `assignment_only`，Planner 不知道填什么、填哪里。

### 根因

`parse_single_file()` 中 `detect_combined_layout()` 找不到三/四/五标题就返回 `assignment_only`，但 `parse_report` 模块已经通过表格结构检测识别为 `training_table`，这个结果存在 metadata 里，没有被 `detect_combined_layout` 使用。

### 修复

**文件**：`src/python/agent/parse_documents.py`（+14 行）

`parse_single_file()` 在 `detect_combined_layout()` 返回 `assignment_only` 但 `metadata.report_layout == "training_table"` 时，覆盖为 `fill_only`。

详见 [V2_CODE_EXECUTION_FIX.md](./V2_CODE_EXECUTION_FIX.md) §P0A。

---

## BF4 — 快速解题路径缺失代码预检（P0B）

**发现时间**：2026-06-04（日志诊断）  
**严重度**：🟡 中等（Web 服务器代码 15 秒超时白等）  
**来源文档**：[V2_CODE_EXECUTION_FIX.md](./V2_CODE_EXECUTION_FIX.md)

### 症状

AI 生成 Flask Web 服务器代码（含 `app.run()`），快速解题后盲跑，15 秒超时。

### 根因

`preflight._check_execution_pattern()` 能检测 `web_server`/`interactive` 模式，但只在**深度模式** DeepPipeline 的 draft→preflight 阶段调用。快速解题 `/api/solve` 和标准模式执行后直接跑代码，不预检。

### 修复

**文件**：`src/python/server.py`（+18 行）

`/api/run-code` 和 `/api/run-and-screenshot` 在执行前调用 `_check_execution_pattern()`，检测到隐患 → 跳过执行 → 返回 `blocked_by_preflight: true`。

详见 [V2_CODE_EXECUTION_FIX.md](./V2_CODE_EXECUTION_FIX.md) §P0B。

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

## 总结

*日志版本：2026-06-06（BF25）。每次修复 bug 后更新本文档。*
