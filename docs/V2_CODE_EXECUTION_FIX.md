# V2 代码执行改进计划

**来源**：2026-06-04 日志诊断 → `app.log` 16:07-16:08 会话。

## 问题诊断

用户上传 `第十周实训报告_学号_姓名.docx`（实训表格模版），快速解题后代码运行超时。

日志关键行：

```
[16:07:56] parse_documents docs=1 fill=… layout=assignment_only  ← 误判
[16:07:56] parse          multi-doc sections_detected=0 layout=training_table  ← 正确
[16:08:21] ai 解题 type=lab_report lang=python
[16:08:40] run 执行 lang=python len=2489
[16:08:55] run 完成 error=True out_len=11  ← 15 秒超时
```

根因三条：

| # | 问题 | 表现 |
|---|------|------|
| 1 | 训练表格报告无"三/四/五"标题 → `detect_combined_layout` 误判为 `assignment_only` | Planner 不知道填什么、填哪里 |
| 2 | AI 生成 Flask Web 服务器代码（`exec.py` 含 `app.run()`），训练表格场景 LLM 乱猜 | 执行阻塞 15s 超时 |
| 3 | `run_code.py` 只支持单文件；多文件 Java/Python/C 项目无法编译运行 | 多 class 拆文件 → `javac` 找不到依赖；Python `import` 本地模块报 `ModuleNotFoundError` |

---

## 改进方案

### A. 修复训练表格布局误判

**文件**：`src/python/agent/parse_documents.py`

**现状**：`detect_combined_layout()` 找不到 `三/四/五` 标题就回退到 `assignment_only`。但 `parse_report` 模块（`build_question_from_document`）已经通过表格结构检测正确识别了 `training_table` 布局，这个结果在 `parse_single_file` 的 `question.type` 里，但没有回传给布局判定。

**改动**：

1. `parse_single_file()` 在调用 `detect_combined_layout()` 后，检查 `question` 对象中的实际类型和章节检测结果
2. 如果 `question.type == 'lab_report'` 且 `detect_combined_layout` 返回 `assignment_only`，覆盖为 `fill_only`（至少有实训表格可填）
3. 把 `parse_report` 阶段检测到的 `sections_detected` / `table_map` / `report_layout` 信息回传到 `parse_single_file` 的返回值中，确保 `parse_documents_list` 里 `fill_target` 的 `full_text` 不为空

**预期效果**：实训表格报告不再被误判为纯题目，Planner 能看到待填结构。

### B. 快速解题路径增加代码预检

**文件**：`src/python/server.py`、`src/python/modules/preflight.py`、`src/python/modules/fix_code.py`

**现状**：`preflight.check_code()` 能检测 `web_server` / `interactive` / `possible_infinite` 模式，但只在**深度模式 DeepPipeline** 的 draft→preflight 阶段调用。快速解题 `/api/solve` 和标准模式 `solve_lab` 执行后直接跑代码，不预检。

**改动**：

1. `/api/solve` 和标准模式 executor 在 `run_code` 前调用 `preflight.check_code()`
2. 检测到 `web_server` / `interactive` 时：
   - **不执行**代码（避免 15s 白等）
   - 返回 `run_result` 标注 `blocked_by_preflight: true` + `pattern` + `message`
   - 自动触发 `fix_code`（一次），prompt 注明"去掉 Web 服务/交互输入，改为直接执行核心逻辑并 print"
3. `fix_code.py` 已支持按 `FIX_STRATEGIES` 分类修复，新增 `exec_pattern` 策略：针对 `web_server` → 去掉 `app.run()` / 改为 `if __name__` 测试块；针对 `interactive` → 用硬编码输入替换 `input()`/`scanf()`

**预期效果**：Flask 服务器代码不再盲跑 15s 超时，一次 fix 后得到可执行的脚本。

### C. 多文件代码执行

**文件**：`src/python/modules/run_code.py`、`src/python/modules/solve_lab.py`、`src/python/modules/screenshot.py`、`src/renderer/app.js`、`src/renderer/index.html`、`src/renderer/styles.css`

#### C1 后端：`run_code.py` 新增多文件执行

```python
# 新接口
def execute_multi_file(
    files: list[dict],   # [{name: "main.py", code: "..."}, {name: "utils.py", code: "..."}]
    language: str,
    main_file: str,      # "main.py"
    work_dir: Path = None,
) -> tuple[str, bool]:
```

**行为**：

| 语言 | 编译/执行方式 |
|------|--------------|
| Python | 所有 `.py` 写入 `work_dir`，`python main.py` 执行（其他模块可 `import`） |
| Java | 所有 `.java` 写入 `work_dir`，`javac *.java` 一次编译全部，然后运行主类 |
| C | 所有 `.c` 写入 `work_dir`，`gcc *.c -o out.exe` 链接编译 |
| C++ | 所有 `.cpp` 写入 `work_dir`，`g++ *.cpp -o out.exe` 链接编译 |
| JavaScript | 只执行主文件（Node 的 `require` 自动解析同目录） |

**向后兼容**：保留 `execute_code(code, language)` 单文件接口。当 `solve_lab` 返回的是旧格式 `code: string` 时自动包装为单文件。

#### C2 Prompt 改动：`solve_lab` 输出多文件

`prompts.py` 中 `LAB_PROMPT` 和 `SOLVE_PROMPT` 的 output schema 扩展：

```json
{
  "code_files": [
    {"name": "main.py", "code": "..."},
    {"name": "utils.py", "code": "..."}
  ],
  "main_file": "main.py"
}
```

向后兼容：仍接受 `"code": "..."` 字符串，Executor 自动包装。

#### C3 前端：Monaco 多文件 tab

**最小改动方案**（不引入文件树）：

- 代码面板顶部加一行 tab 栏（文件名的 pill 按钮）
- 点击 tab 切换 Monaco 内容
- "运行"按钮传多文件到后端
- 截图时只截当前激活的文件（或第一个文件）

**HTML 新增**：
```html
<div class="code-file-tabs" id="codeFileTabs" style="display:none">
  <!-- 动态生成 file-tab 按钮 -->
</div>
```

**`app.js` 新增状态**：
```js
let currentCodeFiles = [];      // [{name, code}, ...]
let currentMainFile = '';
```

**`showCodePanel` 改签名**：接受 `{files, mainFile}` 或向后兼容 `(question, code, language, index)`。

**运行按钮**：多文件时调用新 API `/api/run-code-multi`，单文件时仍走 `/api/run-code`。

#### C4 截图适配

`screenshot.py` / `ide_render.py` 的 IDE 截图也需要支持多文件 tab 效果：在截图顶部绘制文件 tab 栏，当前文件高亮。

---

## 实施顺序

| 优先级 | 模块 | 预估改动量 | 依赖 | 状态 |
|--------|------|-----------|------|------|
| **P0** | A — 修复训练表格布局误判 | `parse_documents.py` ~15 行 | 无 | ✅ 完成 2026-06-04 |
| **P0** | B — 快速解题代码预检 | `server.py` ~20 行、`preflight.py` ~10 行、`fix_code.py` ~15 行 | 无 | ✅ 完成 2026-06-04 |
| **P1** | C1 — 多文件后端 | `run_code.py` ~80 行 | A, B 完成后 | ✅ 完成 2026-06-04 |
| **P1** | C2 — Prompt 多文件 schema | `prompts.py` ~30 行、`lab_parse.py` ~15 行、`llm_client.py` ~5 行、`executor.py` ~40 行、`fix_code.py` ~25 行 | C1 | ✅ 完成 2026-06-04 |
| **P1** | C3 — Monaco 多文件 tab | `app.js` ~100 行、`index.html` ~2 行、`styles.css` ~25 行、`server.py` ~35 行 | C1 | ✅ 完成 2026-06-04 |
| **P2** | C4 — 截图多文件 tab | `ide_render.py` ~40 行 | C3 | ⏸ |

**建议**：P0 两个 bug 修完立即验证，再开始 P1 多文件支持。

---

## 验收标准

### A 验收
- 上传纯实训表格 `.docx`（无"三/四/五"标题），`parse_documents` 返回 `layout=fill_only` 或 `layout=training_table`，而非 `assignment_only`
- `fill_target.full_text` 非空

### B 验收
- 快速解题 AI 返回 Flask 代码 → 不执行，`run_result` 含 `blocked_by_preflight: true`
- 自动 fix 一次 → 去掉 `app.run()` → 可执行
- 正常代码（print 脚本）不受影响，仍直接执行

### C 验收
- AI 返回 `code_files: [{main.py}, {utils.py}]` → 两个文件都写入 TEMP_DIR，`python main.py` 能 import utils
- Java 两个 public class → 写入两个 `.java`，`javac *.java` 编译通过
- Monaco 显示文件 tab，切换文件不丢代码
- 截图正常（至少覆盖单文件向后兼容）

---

## P0 实现记录 (2026-06-04)

### P0A — 修复训练表格布局误判

**文件**：`src/python/agent/parse_documents.py`

**改动**（+14 行）：
1. `parse_single_file()` L170 之后：`detect_combined_layout` 返回 `assignment_only` 但 metadata 中 `report_layout == "training_table"` 时，覆盖为 `fill_only`；同时修正 `resolved_role`（`assignment` → `fill_target`）
2. 返回字典新增 `report_layout` 和 `table_map` 字段，从 metadata 传播

**关键逻辑**：`modules/parse_report.py` 的 `_detect_table_layout()` 通过遍历表格单元格匹配 `_TRAINING_TABLE_MARKERS`（"实训步骤及内容"等）正确检测到 training_table，结果存入 metadata。`parse_single_file` 现在利用这个结果纠正 `detect_combined_layout` 的误判。

### P0B — 快速解题代码预检

**文件**：`src/python/server.py`

**改动**（+18 行）：
1. `/api/run-code`：`execute_code()` 前调用 `_check_execution_pattern()`，若检测到 `web_server`/`interactive` 则跳过执行，返回 `blocked_by_preflight: true` + `preflight_pattern` + `preflight_message`
2. `/api/run-and-screenshot`：同上

**已有基础设施**（无需改动）：
- `modules/preflight.py`：`_check_execution_pattern()` 已实现 web_server/interactive/possible_infinite 检测
- `modules/fix_code.py`：`FIX_STRATEGIES` 已包含 `web_server`、`interactive` 策略
- `agent/executor.py`：`_run_run_code()` 已在标准模式中实现了 preflight → fix_code → retry 完整闭环

## P1 实现记录 (2026-06-04)

### P1 C1 — 多文件后端

**文件**：`src/python/modules/run_code.py`

**改动**（+110 行）：
1. `execute_multi_file(files, language, main_file, work_dir)` — 多文件执行入口
   - 所有文件写入 `work_dir`（默认 TEMP_DIR）
   - Python: `python main.py`（其他模块可 `import`）
   - Java: `javac *.java` 全量编译，然后 `java -cp work_dir MainClass`
   - C/C++: 通配符 `gcc *.c -o out.exe` / `g++ *.cpp -o out.exe`
   - JavaScript: `node main.js`
2. `_run_java_multi(work_dir, main_file)` — 辅助：Java 多文件编译运行
3. `_compile_run_multi(compiler, work_dir, glob_pattern, out_name)` — 辅助：C/C++ 多文件编译运行
4. `execute_code()` 单文件接口保持不变，向后兼容

### P1 C2 — Prompt 多文件 schema

**文件**：`src/python/agent/prompts.py`、`src/python/modules/lab_parse.py`、`src/python/llm_client.py`、`src/python/agent/executor.py`、`src/python/modules/fix_code.py`

**改动**：
1. `prompts.py`：`LAB_REPORT_USER` output schema 新增 `code_files` 数组 + `main_file` 字段，向后兼容 `code` 字段。末尾追加「代码环境约束」块：禁用 Servlet/JSP/HTML 混入，默认生成 Java SE 命令行程序，仅 Web 相关实验可用 `HttpServer` + 独立 HTML 文件。`FIX_CODE_USER` 同步更新
2. `lab_parse.py`：`parse_lab_json()` 新增提取 `code_files`/`main_file` 字段。`complete_lab_parsed()` 添加规范化逻辑：无 `code_files` 但有 `code` 时自动包装为 `[{name, code}]`。新增 `_guess_filename(parsed)` 根据语言推断文件名
3. `llm_client.py`：`call_ai()` 和 `call_claude()` 返回值新增 `code_files`、`main_file`
4. `executor.py`：
   - 新增 `_guess_filename_from_lang()` 辅助
   - `_run_run_code()` 改为从 `solve_data.code_files` 读取，单 `code` 自动包装；多文件时调用 `execute_multi_file`
   - `_fix_and_retry()` 支持多文件修复与重执行
   - `_run_fix_code()` 支持多文件
5. `fix_code.py`：
   - `fix_code_from_error()` 新增 `code_files`、`main_file` 参数，prompt 中展示多文件
   - 新增 `_ext_for_lang()` 辅助
   - `apply_fix_to_solve_data()` 支持合并 `code_files`/`main_file`

### P1 C3 — Monaco 多文件 tab

**文件**：`src/renderer/app.js`、`src/renderer/index.html`、`src/renderer/styles.css`、`src/python/server.py`

**改动**：
1. `server.py`：新增 `/api/run-code-multi` 端点（含 preflight 预检）
2. `index.html`：代码面板内新增 `<div class="code-file-tabs" id="codeFileTabs">`
3. `styles.css`：新增 `.code-file-tabs`、`.code-file-tab`、`.code-file-tab.active` 样式
4. `app.js`：
   - 新增状态：`currentCodeFiles`（数组）、`currentMainFile`（入口文件名）
   - `showCodePanel()` 支持两种调用：单文件 `(q, codeStr, lang, idx)` 或多文件 `(q, codeFiles[], lang, idx, mainFile)`
   - 新增 `renderCodeFileTabs()` — 渲染 tab 栏，仅多文件时显示
   - 新增 `switchCodeFile(name)` — 切换 tab，保存当前编辑内容
   - 新增 `_showFileInMonaco(name, monacoLang)` — 从 `currentCodeFiles` 加载
   - `runCode()` — 运行前保存当前编辑器内容到 `currentCodeFiles`；多文件时调用 `/api/run-code-multi`；向后兼容单文件
   - `closeCodePanel()` — 重置 `currentCodeFiles`/`currentMainFile`
   - `onSolveComplete()`、`solveQuestion()`、`applyAgentRunDone()` — 传递 `code_files`/`main_file`

**向后兼容**：所有旧路径保留。单文件 `code` 字符串输入在 `lab_parse.complete_lab_parsed()` 中自动转换为 `code_files` 数组形式。`showCodePanel` 仍接受第一种调用方式。Monaco tab 仅在 `code_files.length > 1` 时显示。

### C4 — 截图多文件 tab（P2，待实施）

**文件**：`src/python/modules/screenshot.py`、`src/python/modules/ide_render.py`

**计划**：`ide_render.py` 的 `save_ide_screenshot_pages()` 接收可选 `file_tabs: list[str]` + `active_file: str`，在截图顶部绘制文件 tab 栏。`render_ide_screenshot_file()` 透传这些参数。P1 的 Monaco tab 功能验证通过后再实施。
