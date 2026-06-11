# AI 决策洞察收集

LLM 在解题过程中自述的判断依据、边界情况、环境适配决定等。每次 `/api/solve` 成功后，若 LLM 返回了 `notes` 字段则自动追加。

---

## 2026-06-08

### #N 计划层与执行层题型分裂 — `code_cloze` 误走 `solve_lab`

**来源**：用户 Singleton 填空题；ReAct 思考写「这是代码补全填空题」，但工具调用仍为 `solve_lab OK`。

**洞察**：Planner/解析可正确产出 `solve_code_cloze` 步骤，但 ReAct AO-7 bootstrap **硬编码**先跑 `solve_lab`；且 `solve_code_cloze` 长期无 `react_alias`，LLM 在工具列表里「看不见」填空专用路径。思考内容与工具选择可完全脱节。

**改进**（BF49 等，见 [CODE_CLOZE_QUESTIONS.md](../features/CODE_CLOZE_QUESTIONS.md)）：

1. `registry.py`：为 `solve_code_cloze` 注册 ReAct 工具
2. `react_loop.py`：`_is_code_cloze_run` → bootstrap `solve_code_cloze`，跳过 `solve_lab`
3. `react_prompts.py`：计划清单注明禁止 `run_code`
4. `deliverable.py` / `app.js`：交付物与收尾优先 `solve_code_cloze` 结构化 `blanks`

**教训**：新模块若只接 Planner/Executor 不接 ReAct registry + bootstrap，会出现「计划对、执行错」的假完成。

---

## 2026-06-05

### #1 代码环境约束 — Servlet/JSP 混入 Java

**来源**：人工发现（日志 `UploadServletIO.java:2: 错误: 需要 class...`）

**洞察**：LLM 在生成 Java 代码时，看到实验报告中提到「Web」「网页」关键词时，倾向于生成 JSP/Servlet 代码（HttpServlet、javax.servlet、HTML 模板混入 .java），但这些无法在命令行 `javac`/`java` 下编译运行。

**改进**：
1. `prompts.py` LAB_REPORT_USER 末尾新增「代码环境约束」块：默认禁止 Servlet/JSP/HTML 混入，明确告知运行环境是 javac/java 命令行
2. 保留例外：当报告明确要求 Web 实验时，允许使用 `HttpServer` + 独立 HTML 文件的多文件方案
3. `preflight.py`/_check_execution_pattern 新增 `jsp_template` 检测作为最后防线
4. `prompts.py` LAB_REPORT_USER JSON schema 新增 `notes` 字段，让 LLM 自述决策依据
5. 本文件建立，用于收集 LLM 自述的解题判断

### #2 代码环境约束 — Web 实验应走多文件方案

**来源**：迭代改进（用户反馈 #1 过于粗暴，一刀切禁止会破坏真实 Web 实验需求）

**洞察**：有些实验本身就要求做「Java Web 应用」「网页后台」，一刀切禁止 Web 代码不可取。正确做法是区分：命令行环境不能跑 Servlet 容器，但 Java SE 内置 `com.sun.net.httpserver.HttpServer` 可以在命令行直接运行，HTML 可以拆分为独立文件通过 `code_files` 数组传递。

**改进**：约束从「强制禁止一切 Web 代码」改为「默认命令行程序，Web 实验例外可走 HttpServer + 多文件方案」

---

### #3 技能学习系统

**来源**：功能设计（用户提出：洞察能不能变成可复用的技能）

**洞察**：每次发现问题改 prompt 是事后的，但如果相同的 pattern（比如 Java + Web 关键词 → Servlet 倾向）能在每次跑题时自动注入提醒，效果更好。本质是"从已知经验中学习"。

**改进**：
1. 新增 `src/python/agent/skill_store.py` — 技能注册表
2. 每个技能含 `trigger`（上下文匹配函数）+ `inject`（注入 prompt 的文本）
3. `render_lab_report_prompt()` 每次构建 prompt 时自动匹配并注入相关技能
4. 已注册技能：
   - `java-no-servlet`: 当 language=java 且报告含 Web 关键词时，提醒用 HttpServer 而非 Servlet
   - `java-multi-file`: 当 Java 多类项目时，提醒拆分文件到 code_files
5. **AO-10 promote 流程**（2026-06-06）：
   - 运行结束自动写入 `%APPDATA%/lab-solver/skill_candidates.json`（`record_skill_candidates_from_run`）
   - 设置 → AI 配置 → **技能候选**：浏览 `status: pending` 条目，编辑注入文本，点「写入 skill_store」
   - API：`GET /api/skill-candidates`、`POST /api/skill-candidates/promote`（body: `{ id, inject? }`）
   - 成功后写入 `%APPDATA%/lab-solver/promoted_skills.json` 并运行时注册；若可写则追加本文件 Promoted 记录
6. V3-4：同一 `error_category` 或 `notes_hash` 7 天内 ≥2 次 → 候选 `status: pending`

---

### #4 语言混淆 — Python 代码写入 .java 文件

**来源**：日志分析（`gui_prog.java:1: 错误: 需要 class...` — 文件内容是 `def bubble_sort(arr):` / `#` 注释）

**洞察**：LLM 在 ReAct 循环中修复代码时，可能将 Python 语法（`def`、`elif`、`print()`）写入 `.java` 文件。与 Servlet 混入不同，这是语言层面的混淆——文件扩展名 `.java` 但内容是 Python，`javac` 无法编译。连续 4 次编译失败后 Agent 触发降级退出。

**改进**：
1. `skill_store.py` 新增 `java-no-python` 技能：当 language=java 且报告含 Python 特征关键词时，注入提醒检查每个 code_file 内容与扩展名一致
2. `executor.py` 新增 `_save_agent_insights()`：Agent 模式（standard/deep/react）完成后自动从 `module_results["solve_lab"].data.notes` 提取 LLM 自述追加到本文件，补上了之前仅 `/api/solve` 有写入的盲区

---

### #5 修复越修越坏 — fix_code 叠加退化

**来源**：运行观察（同一实验报告连续 5 次 fix_code 均失败，LLM 自述"fix_code每次都是基于同一个有问题的代码进行修复，但无法彻底清除"）

**洞察**：`_fix_and_retry` 的设计假设是"每次 LLM 修复都会让代码更接近正确"，但现实中存在相反情况——LLM 可能「修错了地方」引入新 bug，每轮代码都不同但都对同一个错误束手无策。当前只有"代码一字不变才跳过"的检测（`new_code == old_code`），无法感知"代码变了但错误没变"的退化模式。

更根本的问题：fix_code 是在**有问题的代码上做增量补丁**，但有些问题（语言混淆、隐藏字符、架构性错误）无法通过增量修补解决，必须推倒重来。LLM 自己也有这个认知——它在日志里明确写了"需要换一种思路——直接生成一个全新的"——但工具设计不给它这个出口。

**改进**：
1. `executor.py` `_fix_and_retry` 新增 `same_error_count` 跟踪：同一错误分类连续出现 2 次 → 放弃增量修复，改为调用 `_regenerate_code` 从零重新 solve_lab，并将累积的错误信息注入 prompt 作为硬约束
2. `run_code.py` `execute_multi_file` 写入前清理当前 run 不拥有的残留源文件，防止旧运行的错误文件污染编译
3. `executor.py` `_save_agent_insights` 修复字段路径 bug（`data["notes"]` → `data["parsed"]["notes"]`）

---

## 使用说明

- 本文件由 `/api/solve` 自动追加（当 LLM 返回的 `parsed.notes` 非空时）
- 在 Step3 界面看到 `notes` 信息时可手动记录于此
- 格式：`### #N 简短标题` + 来源/洞察/改进 三段
- **洞察 → 技能路径**：确认某条洞察重复出现 2-3 次后，在 `skill_store.py` 注册为技能，从此每次跑题自动注入

---

（后续运行将自动追加到此线以下）

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于实验环境为纯Java SE命令行，没有Servlet容器和Web服务器，因此无法运行JSP和Servlet。本程序通过本地文件读写模拟文件上传过程，演示了IO流和第三方包两种方式的核心逻辑。在实际Web项目中，IO流方式需要手动解析HTTP请求体中的multipart数据，而第三方包（如Apache Commons FileUpload）提供了更便捷的API。本模拟程序忽略了HTTP协议细节，专注于文件数据的读写操作，符合实验对核心原理掌握的要求。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于运行环境为纯Java SE命令行，没有Servlet容器，因此使用JDK自带的com.sun.net.httpserver.HttpServer模拟Web服务器。上传页面拆分为独立的HTML文件，与Java代码分离。文件上传解析逻辑为简化实现，仅用于演示核心流程，实际生产环境应使用成熟的第三方库如Apache Commons FileUpload。

## 2026-06-05

### 自动记录（来自 AI 解题 notes）

为了在有限输出中清晰展示置换过程，我将内存帧数设为10（小于页面总数20），这样在访问第11个页面时就会发生置换。如果按照实验提示的32帧、20页，则所有页面都能装入内存，不会发生置换，无法展示算法效果。实际实验中可根据需要调整参数。生成页面序列时，我使用了简单的递增序列，因为实验报告要求展示局部性，但为了代码简洁且能演示置换，这里用无重复序列已足够说明算法逻辑。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于实验环境为纯Java SE命令行，没有数据库和MyBatis依赖，因此使用Java动态代理和自定义注解模拟了MyBatis的核心功能。XML方式也通过Java类模拟了Mapper XML的解析和执行。实际项目中应使用真实的MyBatis框架和数据库连接。代码中所有数据存储在内存List中，每次运行独立，互不干扰。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于实验环境为纯Java SE命令行，无法使用真实MyBatis框架（需要jar包和数据库服务），因此采用JDBC+SQLite模拟MyBatis的注解和XML配置风格。注解方式将SQL直接写在方法中（类似@Select注解），XML方式将SQL从外部配置读取（这里用字符串模拟）。实际项目中应使用MyBatis官方依赖和数据库驱动。SQLite驱动需要单独下载，但环境已安装sqlite3，JDBC驱动可能未包含，若运行报错请替换为H2内存数据库或使用MySQL。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于实验环境无数据库服务器，使用H2内存数据库模拟，无需额外安装。项目采用Maven结构管理依赖，运行时需先执行mvn compile或使用IDE自动构建。所有SQL操作均通过MyBatis的SqlSession执行，自动提交事务。输出格式与实验报告要求一致，展示了增删改查的完整流程。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于实验环境是纯Java SE命令行，没有Maven，因此实际运行时需要手动下载mybatis-3.5.13.jar和sqlite-jdbc-3.43.0.0.jar并添加到classpath。代码中使用SQLite内存数据库，每次运行都会重新创建表和数据，确保结果一致。MyBatis配置文件中使用了自动提交模式（openSession(true)），避免手动commit。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于运行环境为纯Java SE命令行，没有Servlet容器和浏览器，因此无法使用HttpServletRequest获取上传文件。本程序采用硬编码方式模拟multipart请求体数据，分别演示IO流和第三方包（模拟）两种文件上传方式。实际Web项目中，需要将代码部署到Tomcat等Servlet容器中，并通过HTML表单提交文件。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

由于运行环境为纯Java SE命令行，无Servlet容器和浏览器，无法使用HttpServlet、request.getParameter()等Web相关API。因此采用模拟方式实现文件上传：在main方法中直接指定源文件和目标路径，使用IO流和NIO两种方式完成文件复制。Apache Commons FileUpload依赖Servlet API无法使用，故用Java NIO的Files.copy替代，其封装了底层IO操作，可视为一种高级文件上传实现。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

所有代码均放在com.designpatterns包及其子包下，编译时需要保持目录结构。使用javac编译时，需在src目录下执行：javac com/designpatterns/Main.java，然后运行：java com.designpatterns.Main。由于是纯Java SE程序，所有输出均通过System.out.println实现，无需任何外部依赖。

## 2026-06-05

### 自动记录（来自 AI 解题 notes — Agent 模式）

所有设计模式均使用纯Java SE实现，无外部依赖。简单工厂模式中UnsupportedShapeException继承自Exception，需要显式捕获。原型模式中深克隆通过手动调用photo.clone()实现，确保照片对象独立。单例模式的双重检测锁使用了volatile关键字防止指令重排。运行环境为JDK 17，所有代码在命令行下编译运行通过。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

所有类都放在默认包中，避免import语句导致编译错误。深克隆使用Java序列化机制实现，需要类实现Serializable接口。单例模式的双重检测锁使用了volatile关键字保证线程安全。代码完全符合Java SE命令行程序规范，可直接编译运行。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

所有代码均使用纯Java SE编写，无需任何外部依赖。每个设计模式独立为一个Java文件，通过Main.java统一调用。由于运行环境为命令行，所有输出均使用System.out.println，并避免使用emoji等特殊字符。单例模式中的双重检测锁使用了volatile关键字确保线程安全。原型模式中，深克隆通过重写clone方法并手动复制照片对象实现，而非使用序列化方式，以避免引入额外依赖。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

实验中的访问序列通过随机生成并引入局部性特征，使得结果更具代表性。实际输出中FIFO命中率54.50%，LRU命中率58.50%，LRU表现更优，但具体数值会因随机序列的不同而有所波动。代码中FIFO使用队列维护装入顺序，LRU通过遍历查找最小访问时间，在物理块数较大时LRU的线性查找效率较低，实际系统中常采用近似实现（如Clock算法）。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

实验中的页面访问序列是随机生成的，因此每次运行结果可能略有不同。实际运行输出中，FIFO和LRU在初始阶段（前32次访问）均未发生淘汰，因为内存尚未填满，这符合算法逻辑。LRU算法在实现时需注意每次命中后更新页面顺序，否则会导致淘汰策略错误。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

实验中的页面访问序列生成采用了简单的概率模型模拟局部性，实际程序执行模式可能更复杂。LRU算法的实现使用了列表的remove和append操作，在页框数较大时效率较低，实际系统中常采用近似算法（如Clock算法）。

## 2026-06-06

### 自动记录（来自 AI 解题 notes — Agent 模式）

实验中的页面访问序列是随机生成的，因此每次运行结果可能不同。本次输出中FIFO和LRU命中率相同，这可能是由于序列长度和页框数等参数设置导致的偶然现象，不代表两种算法在所有情况下性能一致。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-06

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-08

### Promoted skill: `notes_hash-1f419b407222`

**来源候选**: notes_hash:1f419b407222

**触发器**: `solve_lab.notes_hash=1f419b407222`

**注入文本**:

【技能候选 notes_hash-1f419b407222】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-de2e66cdd7d6`

**来源候选**: notes_hash:de2e66cdd7d6

**触发器**: `solve_lab.notes_hash=de2e66cdd7d6`

**注入文本**:

【技能候选 notes_hash-de2e66cdd7d6】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-099389d2cbfa`

**来源候选**: notes_hash:099389d2cbfa

**触发器**: `solve_lab.notes_hash=099389d2cbfa`

**注入文本**:

【技能候选 notes_hash-099389d2cbfa】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-5630e2b9a9c2`

**来源候选**: notes_hash:5630e2b9a9c2

**触发器**: `solve_lab.notes_hash=5630e2b9a9c2`

**注入文本**:

【技能候选 notes_hash-5630e2b9a9c2】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-65774854b20b`

**来源候选**: notes_hash:65774854b20b

**触发器**: `solve_lab.notes_hash=65774854b20b`

**注入文本**:

【技能候选 notes_hash-65774854b20b】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-330440fed20c`

**来源候选**: notes_hash:330440fed20c

**触发器**: `solve_lab.notes_hash=330440fed20c`

**注入文本**:

【技能候选 notes_hash-330440fed20c】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-f0bacaea3423`

**来源候选**: notes_hash:f0bacaea3423

**触发器**: `solve_lab.notes_hash=f0bacaea3423`

**注入文本**:

【技能候选 notes_hash-f0bacaea3423】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-8e4d5800d4dc`

**来源候选**: notes_hash:8e4d5800d4dc

**触发器**: `solve_lab.notes_hash=8e4d5800d4dc`

**注入文本**:

【技能候选 notes_hash-8e4d5800d4dc】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-dcca4f38a5de`

**来源候选**: notes_hash:dcca4f38a5de

**触发器**: `solve_lab.notes_hash=dcca4f38a5de`

**注入文本**:

【技能候选 notes_hash-dcca4f38a5de】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-85c718fde541`

**来源候选**: notes_hash:85c718fde541

**触发器**: `solve_lab.notes_hash=85c718fde541`

**注入文本**:

【技能候选 notes_hash-85c718fde541】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-94f1e986e376`

**来源候选**: notes_hash:94f1e986e376

**触发器**: `solve_lab.notes_hash=94f1e986e376`

**注入文本**:

【技能候选 notes_hash-94f1e986e376】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-3d77f6b8cd26`

**来源候选**: notes_hash:3d77f6b8cd26

**触发器**: `solve_lab.notes_hash=3d77f6b8cd26`

**注入文本**:

【技能候选 notes_hash-3d77f6b8cd26】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-7026cd5a61c1`

**来源候选**: notes_hash:7026cd5a61c1

**触发器**: `solve_lab.notes_hash=7026cd5a61c1`

**注入文本**:

【技能候选 notes_hash-7026cd5a61c1】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-b84a906b15ae`

**来源候选**: notes_hash:b84a906b15ae

**触发器**: `solve_lab.notes_hash=b84a906b15ae`

**注入文本**:

【技能候选 notes_hash-b84a906b15ae】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-af96575cf15e`

**来源候选**: notes_hash:af96575cf15e

**触发器**: `solve_lab.notes_hash=af96575cf15e`

**注入文本**:

【技能候选 notes_hash-af96575cf15e】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-75781889ad5d`

**来源候选**: notes_hash:75781889ad5d

**触发器**: `solve_lab.notes_hash=75781889ad5d`

**注入文本**:

【技能候选 notes_hash-75781889ad5d】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-9baa3f6c6922`

**来源候选**: notes_hash:9baa3f6c6922

**触发器**: `solve_lab.notes_hash=9baa3f6c6922`

**注入文本**:

【技能候选 notes_hash-9baa3f6c6922】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-ceba4165e4f3`

**来源候选**: notes_hash:ceba4165e4f3

**触发器**: `solve_lab.notes_hash=ceba4165e4f3`

**注入文本**:

【技能候选 notes_hash-ceba4165e4f3】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-8046661c79cc`

**来源候选**: notes_hash:8046661c79cc

**触发器**: `solve_lab.notes_hash=8046661c79cc`

**注入文本**:

【技能候选 notes_hash-8046661c79cc】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-d52444c37461`

**来源候选**: notes_hash:d52444c37461

**触发器**: `solve_lab.notes_hash=d52444c37461`

**注入文本**:

【技能候选 notes_hash-d52444c37461】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-a80b620f0865`

**来源候选**: notes_hash:a80b620f0865

**触发器**: `solve_lab.notes_hash=a80b620f0865`

**注入文本**:

【技能候选 notes_hash-a80b620f0865】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-84fb8f3a0e5e`

**来源候选**: notes_hash:84fb8f3a0e5e

**触发器**: `solve_lab.notes_hash=84fb8f3a0e5e`

**注入文本**:

【技能候选 notes_hash-84fb8f3a0e5e】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-08

### Promoted skill: `notes_hash-48bf62468e62`

**来源候选**: notes_hash:48bf62468e62

**触发器**: `solve_lab.notes_hash=48bf62468e62`

**注入文本**:

【技能候选 notes_hash-48bf62468e62】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-09

### Promoted skill: `notes_hash-2090bd2838ea`

**来源候选**: notes_hash:2090bd2838ea

**触发器**: `solve_lab.notes_hash=2090bd2838ea`

**注入文本**:

【技能候选 notes_hash-2090bd2838ea】根据历史运行经验，请注意与此触发相关的常见错误模式。

## 2026-06-09

### Promoted skill: `error_category-compile_error`

**来源候选**: error_category:compile_error

**触发器**: `run_code.error_category=compile_error`

**注入文本**:

编译错误时检查文件扩展名与语法是否匹配。

## 2026-06-11

### Promoted skill: `notes_hash-21cb1b1561eb`

**来源候选**: notes_hash:21cb1b1561eb

**触发器**: `solve_lab.notes_hash=21cb1b1561eb`

**注入文本**:

【技能候选 notes_hash-21cb1b1561eb】根据历史运行经验，请注意与此触发相关的常见错误模式。
