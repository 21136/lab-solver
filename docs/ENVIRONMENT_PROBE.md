# L4 — 运行时环境探测 & Prompt 注入

**版本**: 2026-06-04  
**状态**: ✅ 已实现  
**关联**: `config.py` · `agent/prompts.py` · `modules/fix_code.py`

---

## 1. 背景

LLM 生成代码时不知道本地运行环境，导致：

- `import cgi` → Python 3.13+ 已移除（PEP 594），ModuleNotFoundError
- `import matplotlib` → 用户没装，跑不起来
- 生成的 Java 代码在没 JDK 的机器上编译失败
- 用了 matplotlib 但系统没装 → 无法运行

**解决思路**：启动时探测环境，每次 LLM 生成代码前将环境信息注入 prompt。

---

## 2. 探测内容

`config.py` 模块导入时一次性探测并缓存：

| 语言 | 探测内容 | 函数 |
|------|---------|------|
| Python | `sys.version`、PEP 594 已移除模块（19 个）、常用 pip 库是否存在 | `get_python_env()` |
| Java | javac/java 路径、JDK 版本 | `get_java_env()` |
| C/C++ | gcc/g++ 是否可用 | `get_c_env()` |
| Node.js | node 是否可用 | `get_node_env()` |

各探测独立运行，任一失败不影响其他探测，也不影响主流程。

---

## 3. Prompt 注入位置

### 3.1 `render_lab_report_prompt()`（标准模式 + 快速解题）

注入全部四种语言的 env section，LLM 根据选定语言读取对应部分：

```
【运行环境】代码必须能在以下环境运行：
当前 Python 环境：3.14.0
以下模块已在 Python 3.13+ 移除，禁止 import：cgi, cgitb, smtpd, ...
已安装的第三方库（可直接 import）：numpy, requests, flask, ...
当前 Java 环境可用
Java 版本：openjdk version "17.0.13" ...
当前 C/C++ 环境：gcc 可用，g++ 可用
当前环境：Node.js 可用
```

`LAB_REPORT_USER` 末尾还包含「代码环境约束」块：禁止 Servlet/JSP/HTML 混入 Java，默认生成纯 Java SE 命令行程序；仅当报告明确要求 Web 时允许使用 `com.sun.net.httpserver.HttpServer` + 独立 HTML 文件放进 `code_files`。

### 3.2 `FIX_CODE_USER`（fix_code 修代码）

根据当前代码语言只注入对应 env section（语言已知，只给相关环境）。

### 3.3 Planner / understand-plan / reflect / revise / section-brief

**不注入**环境信息。这些 prompt 不生成代码，注入无意义且浪费 token。

---

## 4. 扩展方式

### 新增要探测的 pip 库

编辑 `config.py` 中的 `_COMMON_PIP_PACKAGES` 元组。

### 新增要检查的已移除模块

编辑 `config.py` 中的 `_PEP594_REMOVED` 元组。Python 3.14+ 可能继续移除。

### 为其他 prompt 注入环境

在目标 prompt 的 `render()` 调用中增加 `env_section=` 参数。构建 env section 时使用 `config` 中的 `build_xxx_env_section()`。

---

## 5. 性能

- 探测在首次 import config 时运行一次，模块级缓存
- Python import 探测: ~0.1s（19 个已移除模块 + 17 个 pip 库的 try/import）
- Java/C/Node 探测: ~0.05s（shutil.which + 一次 subprocess for Java 版本）
- Prompt 字符串拼接: ~0ms（纯字符串操作）
- 对 LLM 调用增加约 200-400 字符 token 消耗

---

## 6. 安装引导流程（零环境场景）

### 6.1 触发时机

文档解析成功后，前端调用 `GET /api/runtime-status` 检查环境：

```
有任一运行时 → 正常流程，Step2 显示环境状态栏
零运行时     → 弹出安装引导弹窗
```

### 6.2 弹窗内容

弹窗使用与合规引导相同的 `complianceModal` DOM 容器，显示四种语言的安装状态：

- ✅ 已安装 → 显示版本号
- ❌ 未安装 → [⬇️ 下载] 按钮 + 安装说明
- Java 额外提供 [⚡ 一键安装 JRE] 应用内置下载

### 6.3 用户可选操作

| 操作 | 行为 |
|------|------|
| 点击任一「下载」按钮 | 通过 `shell.openExternal` 在默认浏览器打开国内镜像下载页 |
| 点击「一键安装 JRE」 | 调用 `/api/download-jre` 自动下载安装 |
| 点击「重新检测」 | 重新调用 `/api/runtime-status`，如有环境则关闭弹窗 |
| 点击「跳过安装，使用伪代码」 | 关闭弹窗，后续 `run_code` 步骤默认不勾选 |
| 关闭弹窗 | 同上，跳过安装 |

### 6.4 Planner 降级

`_fallback_plan()` 检查 `_any_runtime_available()`：
- 所有运行时不可用 → `run_code`、`screenshot_*` 的 `default_checked=False`，reason 注明「本地无编程环境」
- 目标语言不可用但其他语言可用 → 同上，reason 注明「{lang} 运行时不可用」

### 6.5 Prompt 降级

`render_lab_report_prompt()` 在零环境时追加：
> ⚠️ 此机器未安装任何编程语言运行时。请生成详细的算法描述或伪代码（用中文注释说明逻辑），不要依赖 import 第三方库。代码放在 code 字段。

### 6.6 国内镜像源

| 语言 | 镜像 | URL |
|------|------|-----|
| Python | npmmirror（淘宝） | `https://npmmirror.com/mirrors/python/` |
| Java | 华为云镜像 | `https://mirrors.huaweicloud.com/openjdk/` |
| MinGW-w64 | GitHub（niXman） | `https://github.com/niXman/mingw-builds-binaries/releases` |
| Node.js | npmmirror（淘宝） | `https://npmmirror.com/mirrors/node/` |

下载 URL 定义在 `config.py` 的 `RUNTIME_DOWNLOAD_GUIDES` 字典中，按需更新。

### 6.7 Step2 环境状态栏

解析成功后，`detectInfoCard` 下方渲染 `.runtime-status-bar`，显示每种语言的可用状态：
- 🟢 已安装 → 绿色徽章 + 版本号
- 🔴 未安装 → 红色徽章
- 🔄 刷新按钮 → 重新检测并可选打开安装引导

### 6.8 图表引擎状态（工具箱 + runtime-status）

`GET /api/runtime-status` 除 `runtimes`（Python/Java/C/Node）外，还返回 **`diagram_tools`**（及顶层 `plantuml_jar_ok` / `java_ok` / `graphviz_ok`）：

| 字段 | 含义 |
|------|------|
| `plantuml_jar_ok` | `assets/plantuml.jar` 是否存在 |
| `java_ok` | 本地 JRE 或 PATH 中 `java` 是否可用（PlantUML 本地渲染） |
| `graphviz_ok` | 便携 `assets/graphviz/bin/dot` 是否可执行（标准 DFD） |

**工具箱模式**进入时在 `#toolboxDiagramStatus` 展示上述三项，便于调试图表渲染。Graphviz 缺失时不引导用户去官网安装，应运行 `scripts/fetch-graphviz-portable.ps1`（见 `src/python/assets/README.txt`）。

---

## 7. 关键文件

| 文件 | 职责 |
|------|------|
| `config.py` | 探测函数 + `get_all_runtime_status()` + `get_diagram_tools_status()` + `RUNTIME_DOWNLOAD_GUIDES` |
| `server.py` | `/api/runtime-status` 端点（含 `diagram_tools`）；`/api/parse-report` 返回 `runtimes_available` |
| `agent/prompts.py` | `render_lab_report_prompt` + `FIX_CODE_USER` 注入 env section / 伪代码指引；`LAB_REPORT_USER` 含代码环境约束（禁 Servlet/JSP，Web 实验走 HttpServer） |
| `agent/planner.py` | `_fallback_plan` 环境感知：无运行时跳过 run_code/screenshot |
| `modules/fix_code.py` | 根据代码语言注入对应 env section |
| `main.js` / `preload.js` | `open-external-url` IPC → `shell.openExternal` |
| `app.js` | `checkAndPromptRuntimes()`、`renderRuntimeStatusBar()`；工具箱 `refreshToolboxDiagramStatus()` |
| `styles.css` | `.runtime-status-bar`、`.runtime-badge`、`.runtime-modal-*` 样式 |
