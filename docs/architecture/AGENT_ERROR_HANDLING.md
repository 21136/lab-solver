# Agent 错误处理增强 — 预检 → 分类 → 策略修复 → 智能降级

**版本**: 2026-06-04  
**状态**: ✅ 已实现  
**关联**: `modules/preflight.py` · `modules/run_code.py` · `modules/fix_code.py` · `agent/executor.py`

---

## 1. 背景

V1 错误处理只有一条直线：

```
run_code 失败（任意原因）
  → fix_code（通用 prompt，无策略差异）
    → 再失败
      → MAX_CONSECUTIVE_FAILURES=2 触顶 → replan 或放弃
```

日志分析发现典型失败：

| 失败类型 | 示例 | 根因 |
|---------|------|------|
| Web 服务阻塞 | Flask `app.run()` → 超时 | LLM 不知道不能 subprocess.run Web 服务 |
| 交互输入 | `input()` → hang | 无法 headless 运行 |
| 死循环 | `while True:` 无 `break` → 超时 | 预检不及时 |
| 编译错误 | Java 缺 class → javac 报错 | 语法未检查 |
| 缺少模块 | `import cgi` → ModuleNotFoundError | Python 3.13+ 移除 |

**解决**：四层增强整合为完整闭环。

---

## 2. 完整链路

```
                    ┌─ web_server ────→ ok=False，跳过执行，直接 fix
                    │
preflight 模式检测 ─┼─ interactive ───→ ok=False，跳过执行，直接 fix
  (零 LLM)          │
                    ├─ possible_infinite → ok=True，risk=timeout_risk
                    │
                    └─ script ────────→ 正常执行

run_code 执行
  ├─ 成功 → 返回
  └─ 失败 → classify_run_error（零 LLM）
       ├─ compile_error     → fix: 语法修复 + 语言兼容
       ├─ missing_module    → fix: 标准库替代 / 去掉 import
       ├─ timeout_blocking  → fix: 去阻塞（Web/交互/死循环→脚本）
       ├─ timeout_slow      → fix: 算法优化
       └─ runtime_exception → fix: 边界条件 + 逻辑

fix 完成 → 重新 run
  ├─ 成功 → 返回
  └─ 失败 → retry（最多 3 次）
       ├─ 第 2 次 → 更激进的 prompt（换风格）
       ├─ 第 3 次 → 最终降级
       └─ 降级 → ok=True, degraded=True, 用 expected_output 替代
```

## 3. 预检模式检测

文件：`modules/preflight.py`

`_check_execution_pattern(code, language)` 用正则检测四种模式：

| pattern | ok | risk | 含义 |
|---------|-----|------|------|
| `web_server` | False | timeout_blocking | Flask/Django/http.server 阻塞进程 |
| `interactive` | False | timeout_blocking | input()/scanf/Scanner 等待输入 |
| `possible_infinite` | True | timeout_risk | while True 无 break |
| `script` | True | None | 普通脚本，可安全执行 |

`ok=False` 的模式 **直接跳过执行**，进入 fix_code 流程。

### 扩展

在 `_check_execution_pattern` 中新增正则匹配即可：

```python
if re.search(r"新模式的标记", code):
    return {"id": "exec_pattern", "ok": False, "pattern": "new_pattern", ...}
```

## 4. 错误分类器

文件：`modules/run_code.py`

`classify_run_error(output, pattern)` 返回 `{category, message, suggestion}`:

| category | 触发条件 | suggestion |
|----------|---------|-----------|
| `compile_error` | SyntaxError/编译错误/javac:/gcc: | 修复语法，确保版本兼容 |
| `missing_module` | ModuleNotFoundError/ImportError | 用标准库替代或去掉 import |
| `timeout_blocking` | 超时 + pattern 为 web_server/interactive/possible_infinite | 去阻塞 API，改写为脚本 |
| `timeout_slow` | 超时 + pattern 为 script | 优化算法复杂度 |
| `runtime_exception` | 其他错误 | 检查逻辑/边界条件 |
| `unknown` | 无输出 | 检查 print 语句 |

### 扩展

在 `classify_run_error` 中添加新分支即可：

```python
if "新错误特征" in output:
    return {"category": "new_category", "message": "...", "suggestion": "..."}
```

## 5. 修复策略

文件：`modules/fix_code.py`

`FIX_STRATEGIES` 字典，key 为 category 或 pattern，value 为注入 prompt 的策略：

```python
FIX_STRATEGIES = {
    "compile_error": "修复编译/语法错误...",
    "missing_module": "用标准库替代...",
    "timeout_blocking": "去掉 app.run()/input()/while True...",
    "timeout_slow": "优化算法复杂度...",
    "runtime_exception": "检查逻辑边界...",
    "web_server": "改写为独立脚本...",
    "interactive": "去掉交互输入...",
}
```

`_build_fix_strategy_section(category, pattern)` 优先 match pattern，fallback 到 category。

`fix_code_from_error` 新增 `category` 和 `pattern` 参数，策略注入到 fix_code prompt 末尾。

### 扩展

新增 category 后在 `FIX_STRATEGIES` 中加一条即可。

## 6. 智能重试 + 降级

文件：`agent/executor.py`

`_run_run_code` 流程：

1. 预检 → pattern
2. `web_server`/`interactive` → 跳过执行，`_fix_and_retry`
3. 执行 `execute_code`
4. 成功 → 返回
5. 失败 → `classify_run_error` → `_fix_and_retry`

`_fix_and_retry` 重试循环（`MAX_FIX_RETRIES=3`）：

```
loop:
  fix_code_from_error(category, pattern)
  ↓
  重新 run
  ├─ 成功 → return ok_result
  └─ 失败 → classify → 检查 same_error_count
       ├─ 不同错误 → 下一轮 fix
       └─ 同错 ≥2 次 → _regenerate_code（推倒重来）
```

`_regenerate_code` 重生路径（v2，2026-06-05）：
- 同一错误分类连续出现 `REGEN_THRESHOLD=2` 次时触发
- 放弃增量 fix，重新调用 `solve_lab` 从零生成代码
- 将累积错误信息作为硬约束注入 prompt（"完全放弃上一轮代码思路"）
- 重生后代码仍失败 → 直接降级，不再浪费 LLM 调用

设计理由：fix_code 是**增量补丁**，适用于拼写错误、缺 import 等局部问题。但语言混淆、隐藏字符、架构性错误无法通过增量修补解决——LLM 可能在"修错了地方"引入新 bug，每轮代码不同但错误相同，越修越坏。此时推倒重来比继续补丁更有效。

`_degrade_run_code` 最终降级：
- 返回 `ok=True`，`degraded=True`
- output 用 `expected_output`（LLM 预测的输出）替代真实执行输出
- SSE 事件携带 `error_meta.degraded=true`

`MAX_CONSECUTIVE_FAILURES` 从 2 提升到 3（`planner.py`）。

## 7. SSE 事件增强

``progress`` 事件增加 `error_meta` 字段：

```json
{
  "type": "progress",
  "module": "run_code",
  "status": "failed",
  "error": "⏱ 运行超时（15秒）",
  "error_meta": {
    "category": "timeout_blocking",
    "degraded": false,
    "degraded_reason": ""
  }
}
```

降级时：
```json
{
  "type": "progress",
  "module": "run_code",
  "status": "done",
  "error_meta": {
    "degraded": true,
    "degraded_reason": "代码执行失败(timeout_blocking): ..."
  }
}
```

## 8. 前端错误展示

Step3 进度列表增强：

- 失败时显示彩色错误类型徽章（红色=编译/超时阻塞，黄色=缺模块/超时慢，紫色=运行时异常）
- 降级时显示「已降级为文本输出」标签 + 降级原因
- 降级项标题变黄色，状态图标半透明

## 9. 关键文件

| 文件 | 职责 |
|------|------|
| `modules/preflight.py` | `_check_execution_pattern` — 模式检测 |
| `modules/run_code.py` | `classify_run_error` — 错误分类 |
| `modules/fix_code.py` | `FIX_STRATEGIES` + `_build_fix_strategy_section` — 分类 prompt |
| `modules/run_code.py` | `execute_multi_file` — 执行前清理残留源文件 |
| `agent/executor.py` | `_run_run_code` + `_fix_and_retry` + `_regenerate_code` + `_degrade_run_code` — 重试→重生→降级 |
| `agent/planner.py` | `MAX_CONSECUTIVE_FAILURES=3` |
| `app.js` | SSE 事件处理 → 错误徽章渲染 |
| `styles.css` | `.solving-error-badge` / `.solving-degraded-badge` 样式 |
