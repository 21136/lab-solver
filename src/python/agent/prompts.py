"""
Central prompt templates with version registry.
Modules use PROMPTS[name].render(**kwargs).
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    user_template: str
    system: str = ""
    output_schema: Optional[str] = None
    changelog: str = ""

    def render(self, **kwargs: Any) -> str:
        return self.user_template.format(**kwargs)


LAB_REPORT_USER = """你是一名大学课程助教，帮助学生完成实验报告。

【实验报告全文】
{full_text}

请认真阅读报告，理解实验要求，然后按以下JSON格式输出（只输出JSON，不要其他文字）：

```json
{{
  "course_type": "课程类型",
  "language": "编程语言：java/python/c/cpp/javascript",
  "steps_analysis": "三、实验步骤 - 思路分析（2-3段，不含代码）",
  "result_description": "四、实验结果 - 对运行结果的说明（1-2段，必填）",
  "expected_output": "模拟终端输出（多行文本，必填）",
  "summary": "五、实验总结 - 3-5句话（必填）",
  "code_files": [
    {{{{ "name": "main.py", "code": "完整可运行源码含中文注释" }}}},
    {{{{ "name": "utils.py", "code": "辅助模块源码" }}}}
  ],
  "main_file": "main.py",
  "notes": "（可选）1-3句话的解题备注：为何选择某种写法、判断依据、题目歧义的理解、环境限制的处理方式等。没有特别发现时可省略此字段。"
}}
```

要求（必须全部字段都有值，不能省略 result_description / expected_output / summary）：
- steps_analysis 只写思路，不要把 code 重复写进 steps_analysis
- 单文件项目用 code_files 放一个文件即可；多文件项目（多 class/模块）拆分到 code_files 数组，main_file 指定入口
- 向后兼容：也可用 "code" 字段放单文件源码（code_files 优先）
- code_files 放最后；前面四个文字字段必须先写完整
- expected_output 要根据代码逻辑给出真实格式的运行输出
- notes 可选：记录解题时的判断依据、边界情况、环境适配决定等，供后续改进参考

{env_section}{format_constraints}

【代码环境约束（极其重要）】
代码在命令行用 javac 编译、java 运行，无 Servlet 容器、无浏览器、无 web 服务器。
- 禁止 Servlet API（HttpServlet, javax.servlet.*, jakarta.servlet.*）
- 禁止 JSP 指令（<%@, <%, <jsp:>）
- 禁止用 response.getWriter()、request.getParameter() 等 Servlet 写法

默认：纯 Java SE 命令行程序
- public class + public static void main(String[] args)
- 用 System.out.println 输出，用硬编码数据代替外部输入
- **禁止 emoji 与装饰性 Unicode 符号**（如 ✅❌🔴⭐）：代码及 println/print 输出只允许中文汉字和 ASCII，Windows GBK 控制台无法编码 emoji

例外：仅当实验报告明确要求「网页」「Web 应用」「浏览器访问」「B/S 架构」时
- 用 Java SE 内置 com.sun.net.httpserver.HttpServer（JDK 6+ 自带，无需额外 jar）
- HTML 页面拆到独立文件放进 code_files（如 index.html、style.css），与 Java 代码分离
- 用硬编码数据代替 request.getParameter()，在 main 中启动服务器并打印访问地址
- ServerSocket 也可接受，但优先 HttpServer（更贴近实验场景）"""

LAB_REPORT_UML_APPEND = """

【UML / 设计图】报告若要求类图、时序图、用例图、状态图、ER 图、部署图等（软件工程/面向对象/数据库/架构类实验常见），必须增加 diagrams 数组（最多 12 张）：
"diagrams": [
  {{"kind": "class", "title": "简单工厂模式类图", "plantuml": "@startuml\\nclass 产品接口 {{\\n  +操作()\\n}}\\nclass 具体产品A {{\\n  +操作()\\n}}\\nclass 工厂 {{\\n  +创建产品(): 产品接口\\n}}\\n@enduml"}},
  {{"kind": "sequence", "title": "创建产品时序图", "plantuml": "@startuml\\nactor 客户端\\nparticipant 工厂\\nparticipant 具体产品A\\n客户端 -> 工厂: 创建产品()\\n工厂 --> 具体产品A: new\\n@enduml"}}
]

【分图规则（默认，极其重要）】
- **默认每张图独立**：一个设计模式 / 一个子系统 / 一层 DFD = 一张图；设计模式实验应为每个模式单独输出一张类图（可再加 1 张关键交互的时序图）。
- **仅当报告明确要求**「一张总的类图」「合并类图」「总览类图」「画在同一张图上」时，才合并为单张 PlantUML 或设置 merge_group；否则禁止合并。
- 不需要任何设计图时 diagrams 设为 []。

【kind 枚举】class | sequence | usecase | activity | state | er | deployment | component | package | flowchart | dfd
- plantuml 必须是完整可渲染的 PlantUML（含 @startuml/@enduml），类名/参与者/状态名可用中文
- kind=dfd 时使用 **dfd_json**（source_engine=graphviz），**不要**写 plantuml；顶层 / 0 层 / 1 层各一张独立图

【kind=dfd 专用 — structured_analysis 套餐】
- 触发词：数据流图、DFD、结构化分析、顶层图、0 层图
- 默认输出 2 张：顶层图 + 0 层展开（各自独立，不合并）
- dfd_json schema（每图一条 diagrams 项）：
  {{"kind": "dfd", "title": "图书管理系统顶层图", "source_engine": "graphviz", "placement_hint": "content",
    "dfd_json": {{
      "level": "顶层",
      "externals": [{{"id": "reader", "name": "读者"}}, {{"id": "admin", "name": "管理员"}}],
      "processes": [{{"id": "p0", "name": "0 图书管理系统"}}],
      "stores": [],
      "flows": [
        {{"from": "reader", "to": "p0", "label": "借还请求"}},
        {{"from": "p0", "to": "reader", "label": "借阅结果"}},
        {{"from": "admin", "to": "p0", "label": "管理指令"}},
        {{"from": "p0", "to": "admin", "label": "统计报表"}}
      ]
    }}
  }},
  {{"kind": "dfd", "title": "图书管理系统 0 层图", "source_engine": "graphviz",
    "dfd_json": {{
      "level": "0层",
      "externals": [{{"id": "reader", "name": "读者"}}, {{"id": "admin", "name": "管理员"}}],
      "processes": [
        {{"id": "p1", "name": "1.0 借还处理"}},
        {{"id": "p2", "name": "2.0 查询处理"}},
        {{"id": "p3", "name": "3.0 管理维护"}}
      ],
      "stores": [
        {{"id": "d1", "name": "D1 图书信息"}},
        {{"id": "d2", "name": "D2 借阅记录"}}
      ],
      "flows": [
        {{"from": "reader", "to": "p1", "label": "借还请求"}},
        {{"from": "p1", "to": "d1", "label": "更新库存"}},
        {{"from": "d1", "to": "p1", "label": "图书信息"}},
        {{"from": "p1", "to": "d2", "label": "写入记录"}},
        {{"from": "reader", "to": "p2", "label": "查询条件"}},
        {{"from": "p2", "to": "d1", "label": "检索"}},
        {{"from": "admin", "to": "p3", "label": "维护指令"}}
      ]
    }}
  }}
- level 取值：顶层 | 0层 | 1层；externals=外部实体(□)、processes=处理(○)、stores=数据存储(═)、flows=数据流(→)
- 每条 flow 必须有 from、to（引用上述 id）、label（数据流名称）；也可用 source 字段存放 dfd_json 的 JSON 字符串

【场景套餐摘要】（按报告关键词选用，每类至少 1 张，总张数 ≤12）
| 场景 | 触发词示例 | 默认独立图 |
| design_patterns | 设计模式、创建型、结构型、行为型 | 每模式 1 类图；可选 +1 时序图 |
| oo_design | 面向对象、类设计 | 类图 + 时序图 |
| requirements | 需求分析、用例 | 用例图 + 活动图 |
| database | 数据库、E-R、表设计 | ER 图（+ 可选类图） |
| architecture | 架构、体系结构 | 构件图 + 部署图 + 包图 |
| bs_web | B/S、Web、HttpServer | 部署图 + 时序图 |
| state_machine | 状态机、状态模式 | 状态图 + 类图 |
| structured_analysis | 数据流图、DFD、结构化分析 | DFD 顶层 + 0 层（dfd_json，分层多张，不合并） |
| algorithm | 算法、程序流程 | 流程图或活动图 |

【每类 PlantUML 中文示例（可复制改写）】
- class（类图）: @startuml\\nclass 学生 {{ -学号\\n+选课() }}\\nclass 课程 {{ -课程名 }}\\n学生 \"n\" -- \"m\" 课程\\n@enduml
- sequence（时序图）: @startuml\\nactor 用户\\nparticipant 控制器\\nparticipant 服务\\n用户 -> 控制器: 提交请求\\n控制器 -> 服务: 处理()\\n服务 --> 控制器: 结果\\n@enduml
- usecase（用例图）: @startuml\\nleft to right direction\\nactor 管理员\\nactor 普通用户\\nrectangle 系统 {{\\n  管理员 --> (用户管理)\\n  普通用户 --> (浏览信息)\\n}}\\n@enduml
- activity（活动图）: @startuml\\nstart\\n:填写表单;\\nif (校验通过?) then (是)\\n  :保存数据;\\nelse (否)\\n  :提示错误;\\nendif\\nstop\\n@enduml
- state（状态图）: @startuml\\ntitle 订单状态机\\n[*] --> 待支付 : 创建订单\\n待支付 --> 已支付 : 付款成功\\n待支付 --> 已取消 : 超时/用户取消\\n已支付 --> 已发货 : 商家发货\\n已发货 --> 已完成 : 确认收货\\n已完成 --> [*]\\n已取消 --> [*]\\nstate 待支付 {{\\n  待支付 : entry / 锁定库存\\n}}\\n@enduml
- er（ER 图）: @startuml\\ntitle 选课系统 E-R 图\\nentity 学生 {{\\n  *学号 : VARCHAR <<PK>>\\n  --\\n  姓名 : VARCHAR\\n  院系 : VARCHAR\\n}}\\nentity 课程 {{\\n  *课程号 : VARCHAR <<PK>>\\n  --\\n  课程名 : VARCHAR\\n  学分 : INT\\n}}\\nentity 教师 {{\\n  *工号 : VARCHAR <<PK>>\\n  --\\n  姓名 : VARCHAR\\n}}\\n学生 ||--o{{ 选课 : 课程\\n教师 ||--o{{ 授课 : 课程\\n@enduml
- deployment（部署图）: @startuml\\ntitle B/S 三层部署\\nnode \"客户端\" as client {{\\n  artifact \"浏览器\" as browser\\n  artifact \"HTML/CSS/JS\" as fe\\n}}\\nnode \"应用服务器\" as app {{\\n  artifact \"Tomcat\" as tomcat\\n  artifact \"Web应用.war\" as war\\n}}\\nnode \"数据库服务器\" as dbnode {{\\n  database \"MySQL\" as mysql {{\\n    artifact \"业务库\" as schema\\n  }}\\n}}\\nclient --> app : HTTP/HTTPS :8080\\napp --> dbnode : JDBC :3306\\n@enduml
- component（构件图）: @startuml\\npackage \"表示层\" {{ [界面模块] }}\\npackage \"业务层\" {{ [订单服务] }}\\npackage \"数据层\" {{ [数据访问] }}\\n[界面模块] --> [订单服务]\\n[订单服务] --> [数据访问]\\n@enduml
- package（包图）: @startuml\\npackage com.example.app {{\\n  package ui\\n  package service\\n  package dao\\n}}\\n@enduml
- flowchart（流程图）: @startuml\\nstart\\n:读入数据;\\n:计算结果;\\n:输出结果;\\nstop\\n@enduml"""

THEORY_USER = (
    '请解答以下编程/理论题，给出完整{lang}代码（用```{lang}包裹）和思路说明：\n\n{full_text}'
)

SHORT_ANSWER_USER = """请你作为软件工程助教，逐题解答下面的简答题。

【题目全文】
{full_text}

要求：
- 每题单独一段，格式：**第N题** 或 **题目标题**，然后换行写答案
- 答案用中文，简洁但完整，每题 3-8 句
- 纯文字输出，不需要代码，不需要 JSON
- 不要重复题目原文"""

CODE_CLOZE_USER = """你是一名软件工程助教。请解答下面的「代码完形填空」题。

【题面全文】
{full_text}

要求：
1. 必须按空号逐一作答，输出结构化 JSON。
2. answer 必须是可直接粘贴进代码的最小片段（除非题面已有分号，否则不要额外补分号）。
3. 若是设计模式题，请给一句 pattern_note（简洁说明考点）。
4. 如果题面可推断语言，用 language 字段标注（如 java/python/javascript），否则留空字符串。
5. 仅输出 JSON，不要解释文字，不要 markdown。

输出格式：
```json
{{
  "type": "code_cloze",
  "language": "java",
  "blanks": {{
    "1": {{ "answer": "abstract class", "brief": "抽象类修饰符" }},
    "2": {{ "answer": "fo.read(fileName)", "brief": "读取文件" }}
  }},
  "completed_code": "",
  "pattern_note": "本题考查外观模式的门面封装调用链"
}}
```"""


PLANNER_USER = """你是一名大学实验报告解题助手。根据【实验报告全文】生成**执行计划**（只输出 JSON，不要其它文字）。

【可用模块】（module 必须从下列 ID 选取，按顺序排列合理执行流）
{module_catalog}

【用户画像默认值】（仅用于 params 默认，不得单独新增无报告依据的步骤）
- 默认编程语言: {default_language}
- 倾向 UML: {prefer_uml}

【报告元数据】（若有）
{metadata_block}

【实验报告全文】
{report_text}

{v4_block}{behavior_block}
【规则】
1. 每个步骤必须含 module、params、reason、evidence、source、confidence、default_checked。
2. evidence 必须是报告原文中的短引文片段；无依据的步骤不要加入。
3. 用户画像只能影响 params（如 language、include_uml），不能因画像单独增加步骤。
4. 纯理论/无代码关键词时优先 solve_theory 或仅 solve_lab，**禁止** run_code / render_uml。
5. V4 开启时 solve_lab 已含内化沙箱验证（run_code_sandbox）；勿默认加入 run_code（仅高级复验可选，default_checked=false）。
6. 用户约束含 skip_validation 时，**禁止**插入 run_code。
7. 默认计划末尾含 present_deliverable（汇编答案供用户复制）；仅当用户明确要求写回 Word 时才含 fill_report。
8. confidence 为 low 的步骤：default_checked=false，reason 须写清为何不确定；并在 clarifications 附 default_reason 引用该 reason。
9. fill_scope 为 skip / user_provided 的节不要安排 solve_lab 覆盖该节内容。

【分节设置】（若有）
{sections_block}

【答题模版格式参考】（若有；仅影响 params/篇幅建议，不得单独新增无报告依据的步骤）
{format_block}

输出 JSON 格式：
```json
{{
  "steps": [
    {{
      "module": "solve_lab",
      "params": {{ "language": "java", "include_uml": false }},
      "reason": "…",
      "evidence": "…",
      "source": "report",
      "confidence": "high",
      "default_checked": true
    }}
  ],
  "clarifications": [
    {{
      "id": "q1",
      "question": "…",
      "options": [{{ "label": "…", "affects": ["render_uml"] }}],
      "default": "…",
      "default_reason": "…"
    }}
  ]
}}
```"""

UNDERSTAND_PLAN_USER = """你是实验报告解题规划专家。先**理解**作业要求，再给出**执行计划**（只输出 JSON）。

【作业原文节选】
{assignment_excerpt}

【报告全文（可能截断）】
{report_text}

【可用模块】
{module_catalog}

【用户画像】语言={default_language}，UML倾向={prefer_uml}
【分节设置】
{sections_block}

【答题模版格式参考】
{format_block}

规则：
1. understand 只分析不写作；grading_points[].evidence 必须是 assignment_excerpt 中的原文子串。
2. plan.steps 的 module 只能从可用模块中选；evidence 须来自报告原文。
3. 不要因画像单独增加无报告依据的步骤。

```json
{{
  "understand": {{
    "summary": "对作业要求的简要理解",
    "grading_points": [
      {{ "point": "评分点", "evidence": "原文子串" }}
    ],
    "risks": ["可能遗漏的要求"]
  }},
  "plan": {{
    "steps": [
      {{
        "module": "solve_lab",
        "params": {{ "language": "java", "include_uml": false }},
        "reason": "…",
        "evidence": "…",
        "source": "report",
        "confidence": "high",
        "default_checked": true
      }}
    ],
    "clarifications": []
  }}
}}
```"""

REFLECT_USER = """你是实验报告审稿人。对照**作业原文**审查草稿，禁止重写全文，只列 issues。

【作业原文（最高优先级）】
{assignment_raw}

【理解摘要】
{understand_json}

【草稿摘要】
{draft_json}

【老师约束】
{teacher_rules}

【填表范围】
{fill_scope}

若理解与原文冲突，设 misunderstood=true 并在 issues 说明。与原文冲突时以原文为准。

```json
{{
  "pass": true,
  "misunderstood": false,
  "issues": [
    {{ "field": "result_description", "severity": "major", "message": "…", "fix_hint": "…" }}
  ],
  "fix_hints": []
}}
```"""

CODE_ONLY_USER = """你是一名大学课程助教。请**只生成可运行源码**，不要写实验报告文字。

【实验要求摘要】
{task_summary}

{constraints_block}
{format_constraints}
{env_section}

只输出 JSON（不要其他文字）：
```json
{{
  "code_files": [
    {{{{ "name": "main.py", "code": "完整可运行源码含中文注释" }}}}
  ],
  "main_file": "main.py",
  "language": "{language}"
}}
```

要求：
- 编程语言必须为 **{language}**
- 单文件优先；多文件仅当题目明确要求多类/多模块
- 命令行可运行，禁止 Servlet/JSP/Web 服务器阻塞模式
- println/print 输出只用中文和 ASCII，禁止 emoji
"""

SOLVE_DIAGRAMS_USER = """根据实验要求与已验证代码结构，**只生成设计图**（不要报告文字字段）。

【题目摘要】
{task_summary}

【代码结构摘要（类名/方法名）】
{code_summary}

【报告相关段落】
{report_excerpt}

只输出 JSON（不要其它文字）：
```json
{{
  "diagrams": []
}}
```

{uml_rules}
"""

WRITE_REPORT_TEXT_USER = """根据已生成代码与（若有）实际运行输出，撰写实验报告文字字段。只输出 JSON：

【题目摘要】
{task_summary}

【编程语言】{language}

【代码状态】{code_status_note}

【实际运行输出】
{sample_stdout}

【代码摘要】
{code_summary}

{format_constraints}

```json
{{
  "steps_analysis": "实验步骤/思路分析（2-3段，不含完整代码）",
  "result_description": "根据上方【实际运行输出】描述结果，不要编造未出现的数值",
  "summary": "实验总结 3-5 句",
  "notes": "（可选）解题备注"
}}
```
"""

FIX_CODE_USER = """修复以下 {language} 代码的运行/语法问题。只输出 JSON：

```json
{{
  "code_files": [
    {{{{ "name": "main.py", "code": "完整可运行源码" }}}}
  ],
  "main_file": "main.py",
  "language": "{language}",
  "steps_analysis": "可选，仅当需要同步修改时",
  "result_description": "可选",
  "expected_output": "可选",
  "summary": "可选"
}}
```

{env_section}
【当前代码文件】
{code_files_text}

【错误信息】
{error_output}

【报告节选】
{report_excerpt}
"""

REVISE_USER = """根据用户反馈修订实验报告 JSON 的指定字段。只输出 JSON，字段与 solve_lab 相同（code_files/main_file 用于多文件；code 向后兼容）。

【仅修订字段】{scope_fields}
【当前内容】
{current_json}

【报告节选】
{report_excerpt}

【用户反馈】
{feedback}
{verification_hint}

【模版提示】
{format_hint}
"""

SECTION_BRIEF_USER = """你是实验报告分节输入分类器。用户在一节的多行输入框中可能混写「本节正文」与「老师要求」。
只分类，不生成正文。节 ID: {section_id}

【用户输入】
{input_text}

输出 JSON（只输出 JSON）：
```json
{{
  "types": ["user_content", "constraints"],
  "user_content": "若整段是用户要自己填入的正文则填此处，否则省略",
  "constraints": [
    {{ "text": "必须出现的原话或规则", "section": "summary", "position": "end", "exact": true }}
  ],
  "suggested_mode": "auto|user_provided|skip",
  "note": "简短说明"
}}
```"""


def render_plan_prompt(
    report_text: str,
    profile: dict,
    metadata: dict | None = None,
    module_catalog: list[str] | None = None,
    sections_block: str = "",
    format_spec: dict | None = None,
    *,
    v4_pipeline: bool = False,
    skip_validation: bool = False,
) -> str:
    from agent.template_analyzer import to_format_constraints

    meta = metadata or {}
    meta_lines = [f"- {k}: {v}" for k, v in meta.items() if v][:12]
    metadata_block = "\n".join(meta_lines) if meta_lines else "（无）"
    catalog = module_catalog or [
        "solve_lab",
        "solve_theory",
        "run_code",
        "render_uml",
        "present_deliverable",
    ]
    fmt = to_format_constraints(format_spec)
    v4_lines: list[str] = []
    if v4_pipeline:
        v4_lines.append(
            "【V4 流水线】solve_lab 已内含读题对齐、写代码、内化沙箱验证与写报告；"
            "默认勿加入 run_code（仅高级复验可选）。"
        )
    if skip_validation:
        v4_lines.append("【用户约束 skip_validation】禁止插入 run_code。")
    v4_block = "\n".join(v4_lines)
    if v4_block:
        v4_block += "\n"
    from agent.user_profile import behavior_hints_block

    behavior_block = behavior_hints_block(profile)
    return PROMPTS["planner"].render(
        report_text=report_text,
        module_catalog=", ".join(catalog),
        default_language=profile.get("default_language", "java"),
        prefer_uml="是" if profile.get("prefer_uml") else "否",
        metadata_block=metadata_block,
        sections_block=sections_block or "（无）",
        format_block=fmt or "（无）",
        v4_block=v4_block,
        behavior_block=behavior_block,
    )


PROMPTS: dict[str, PromptTemplate] = {
    "planner": PromptTemplate(
        name="planner",
        version="1.4.0",
        user_template=PLANNER_USER,
        output_schema="plan_json_v1",
        changelog="AO-9: C2 behavior_hints_block from failure_modules",
    ),
    "section_brief": PromptTemplate(
        name="section_brief",
        version="1.0.0",
        user_template=SECTION_BRIEF_USER,
        output_schema="section_brief_v1",
        changelog="Phase 2a.2: parse-section-brief LLM classify",
    ),
    "lab_report": PromptTemplate(
        name="lab_report",
        version="1.2.0",
        user_template=LAB_REPORT_USER,
        output_schema="lab_report_json_v1",
        changelog="L4: env_section injected — Python version, removed modules, available packages, Java/C/Node status",
    ),
    "lab_report_uml": PromptTemplate(
        name="lab_report_uml",
        version="1.1.0",
        user_template=LAB_REPORT_UML_APPEND,
        changelog="Phase A DG: kind 扩展、分图规则、场景套餐、12 张上限",
    ),
    "theory": PromptTemplate(
        name="theory",
        version="1.0.0",
        user_template=THEORY_USER,
        changelog="Phase 1.1: non-lab_report solve path",
    ),
    "short_answer": PromptTemplate(
        name="short_answer",
        version="1.0.0",
        user_template=SHORT_ANSWER_USER,
        changelog="Theory Q&A: pure short-answer papers",
    ),
    "code_cloze": PromptTemplate(
        name="code_cloze",
        version="1.0.0",
        user_template=CODE_CLOZE_USER,
        output_schema="code_cloze_v1",
        changelog="Phase B: code cloze structured blanks output",
    ),
    "understand_plan": PromptTemplate(
        name="understand_plan",
        version="1.0.0",
        user_template=UNDERSTAND_PLAN_USER,
        output_schema="understand_plan_v1",
        changelog="Phase 2b B1: merged understand+plan",
    ),
    "reflect": PromptTemplate(
        name="reflect",
        version="1.0.0",
        user_template=REFLECT_USER,
        output_schema="reflect_v1",
        changelog="Phase 2b B1: assignment-anchored reflect",
    ),
    "code_only": PromptTemplate(
        name="code_only",
        version="1.0.0",
        user_template=CODE_ONLY_USER,
        changelog="V5-1 / V4 Phase 1: code generation only",
    ),
    "write_report_text": PromptTemplate(
        name="write_report_text",
        version="1.0.0",
        user_template=WRITE_REPORT_TEXT_USER,
        changelog="V5-1 / V4 Phase 2: report text from verified stdout",
    ),
    "solve_diagrams": PromptTemplate(
        name="solve_diagrams",
        version="1.0.0",
        user_template=SOLVE_DIAGRAMS_USER,
        changelog="AO-11 / V4 Phase 3: diagrams decoupled from code generation",
    ),
    "fix_code": PromptTemplate(
        name="fix_code",
        version="1.1.0",
        user_template=FIX_CODE_USER,
        changelog="L4: env_section injected — language-specific runtime constraints for code repair",
    ),
    "revise_answer": PromptTemplate(
        name="revise_answer",
        version="1.0.0",
        user_template=REVISE_USER,
        changelog="Phase 2b B3: scoped revise",
    ),
}


def record_prompt_version(ctx: dict | None, key: str, version: str | None = None) -> None:
    """Record a prompt template version into ctx.prompt_versions (IR-15)."""
    if ctx is None or not key:
        return
    ver = version
    if not ver:
        tpl = PROMPTS.get(key)
        ver = tpl.version if tpl else ""
    if not ver:
        return
    versions = ctx.get("prompt_versions")
    if not isinstance(versions, dict):
        versions = {}
        ctx["prompt_versions"] = versions
    versions[key] = ver


def merge_prompt_versions(ctx: dict | None, versions: dict[str, str] | None) -> None:
    """Merge multiple prompt versions into ctx (IR-15)."""
    if ctx is None or not versions:
        return
    for key, ver in versions.items():
        if key and ver:
            record_prompt_version(ctx, str(key), str(ver))


def record_plan_prompt_version(ctx: dict | None, plan: dict | None) -> None:
    """Record plan-phase prompt version from PlanResult (planner or understand_plan)."""
    record_prompt_version(ctx, "planner", PROMPTS["planner"].version)
    if not plan:
        return
    pv = (plan.get("prompt_version") or "").strip()
    if not pv:
        return
    if pv == PROMPTS["understand_plan"].version:
        record_prompt_version(ctx, "understand_plan", pv)
    elif pv != PROMPTS["planner"].version:
        record_prompt_version(ctx, "planner", pv)


# Back-compat aliases for direct imports
LAB_PROMPT = LAB_REPORT_USER
LAB_PROMPT_UML = LAB_REPORT_UML_APPEND


def render_lab_report_prompt(
    full_text: str,
    include_uml: bool = False,
    lang_hint: str = "",
    section_map: dict | None = None,
    format_constraints: str = "",
    language: str = "",
) -> str:
    """Build the lab_report user prompt with section-priority budget and env context."""
    from agent.prompt_budget import fit_budget
    from config import (
        _any_runtime_available,
        build_c_env_section,
        build_java_env_section,
        build_js_env_section,
        build_python_env_section,
    )

    budgeted = fit_budget(
        full_text,
        budget_tokens=3000,
        preserve_sections=["步骤", "结果", "要求"],
        section_map=section_map,
    )
    fmt = (format_constraints or "").strip()

    # Build runtime environment section for all languages
    env_parts = [build_python_env_section(), build_java_env_section(),
                 build_c_env_section(), build_js_env_section()]
    env_section = "\n".join(p for p in env_parts if p)
    if env_section:
        env_section = "\n【运行环境】代码必须能在以下环境运行：\n" + env_section + "\n"
    if not _any_runtime_available():
        env_section += (
            "\n⚠️ 此机器未安装任何编程语言运行时（Python/Java/C/Node 均不可用）。"
            "请生成详细的算法描述或伪代码（用中文注释说明逻辑），"
            "不要依赖 import 第三方库。代码放在 code 字段。\n"
        )
    if env_section:
        env_section += "\n"

    prompt = PROMPTS["lab_report"].render(
        full_text=budgeted,
        format_constraints=("\n" + fmt) if fmt else "",
        env_section=env_section,
    ) + lang_hint

    # Inject learned skills based on context
    from agent.skill_store import build_skill_injection
    ctx = {"language": language or "", "full_text": budgeted}
    skill_block = build_skill_injection(ctx)
    if skill_block:
        prompt += "\n" + skill_block + "\n"

    if include_uml:
        prompt += PROMPTS["lab_report_uml"].render()
    return prompt


def _build_env_section(language: str = "") -> str:
    from config import (
        _any_runtime_available,
        build_c_env_section,
        build_java_env_section,
        build_js_env_section,
        build_python_env_section,
    )

    env_parts = [
        build_python_env_section(),
        build_java_env_section(),
        build_c_env_section(),
        build_js_env_section(),
    ]
    env_section = "\n".join(p for p in env_parts if p)
    if env_section:
        env_section = "\n【运行环境】代码必须能在以下环境运行：\n" + env_section + "\n"
    if not _any_runtime_available():
        env_section += (
            "\n⚠️ 此机器未安装任何编程语言运行时。"
            "仍请生成完整源码结构；验证可能跳过。\n"
        )
    return env_section


def render_code_only_prompt(
    task_summary: str,
    *,
    language: str = "python",
    constraints_block: str = "",
    format_constraints: str = "",
) -> str:
    from agent.prompt_budget import fit_budget

    budgeted = fit_budget(task_summary or "", budget_tokens=2500, preserve_sections=["步骤", "要求"])
    fmt = (format_constraints or "").strip()
    return PROMPTS["code_only"].render(
        task_summary=budgeted,
        language=language or "python",
        constraints_block=constraints_block or "",
        format_constraints=("\n" + fmt) if fmt else "",
        env_section=_build_env_section(language),
    )


def render_solve_diagrams_prompt(
    *,
    task_summary: str,
    code_summary: str,
    report_excerpt: str,
) -> str:
    from agent.prompt_budget import fit_budget

    excerpt = fit_budget(report_excerpt or "", budget_tokens=1500, preserve_sections=["类图", "UML", "设计"])
    return PROMPTS["solve_diagrams"].render(
        task_summary=(task_summary or "")[:600],
        code_summary=(code_summary or "")[:2000],
        report_excerpt=excerpt,
        uml_rules=LAB_REPORT_UML_APPEND.strip(),
    )


def render_write_report_prompt(
    *,
    task_summary: str,
    language: str,
    code_summary: str,
    sample_stdout: str,
    code_status: str,
    degraded: bool = False,
    format_constraints: str = "",
) -> str:
    if code_status == "verified" and sample_stdout.strip():
        status_note = "代码已通过内化验证，结果说明必须引用实际输出。"
    elif degraded:
        status_note = "代码未能运行，请在结果说明中注明并以预期行为描述。"
    elif code_status == "skipped":
        status_note = "未执行内化验证（无运行时或用户跳过），可基于代码逻辑描述预期结果。"
    else:
        status_note = "根据代码逻辑与可用输出撰写。"
    fmt = (format_constraints or "").strip()
    return PROMPTS["write_report_text"].render(
        task_summary=task_summary[:3000],
        language=language or "python",
        code_status_note=status_note,
        sample_stdout=sample_stdout.strip() or "（无实际输出）",
        code_summary=code_summary or "（无代码）",
        format_constraints=("\n" + fmt) if fmt else "",
    )


def render_theory_prompt(full_text: str, lang: str = "python") -> str:
    from agent.prompt_budget import fit_budget

    budgeted = fit_budget(full_text, budget_tokens=1500, preserve_sections=[])
    return PROMPTS["theory"].render(lang=lang, full_text=budgeted)


def render_short_answer_prompt(full_text: str) -> str:
    from agent.prompt_budget import fit_budget

    budgeted = fit_budget(full_text or "", budget_tokens=2000, preserve_sections=[])
    return PROMPTS["short_answer"].render(full_text=budgeted)


def render_code_cloze_prompt(full_text: str) -> str:
    from agent.prompt_budget import fit_budget

    budgeted = fit_budget(full_text or "", budget_tokens=1800, preserve_sections=[])
    return PROMPTS["code_cloze"].render(full_text=budgeted)
