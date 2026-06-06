PlantUML 本地渲染（推荐）
========================

本目录用于放置 plantuml.jar。解题能手渲染 UML 时**优先使用本地 JAR**，
仅当本地失败且设置中勾选了「UML 允许在线渲染」时，才回退到 PlantUML 官方在线服务。

文件
----
  plantuml.jar   — PlantUML 可执行 JAR（约 21 MB）
                   下载：https://plantuml.com/download
                   或 GitHub Release：
                   https://github.com/plantuml/plantuml/releases

Java 运行环境
-------------
本地渲染需要本机已安装 JRE/JDK（java 命令可用）。

  检查：在终端执行
    java -version

  应看到类似 OpenJDK 17 的版本信息。若未安装，可安装：
    - Eclipse Temurin：https://adoptium.net/
    - Oracle JDK：https://www.oracle.com/java/technologies/downloads/

  解题能手会按以下顺序查找 Java：
    1. %APPDATA%\lab-solver\jre\*\bin\java.exe（应用自带 JRE，若有）
    2. 系统 PATH 中的 java / java.exe

渲染优先级（uml_render.py）
---------------------------
  1. 本地：java -jar plantuml.jar -tpng …（需 plantuml.jar + Java）
  2. 在线：PlantUML 官方 PNG 服务（deflate 编码，失败时尝试 hex 编码）

  本地成功则直接返回，不会访问网络。可避免 Word/WPS 报告中因在线 URL 编码
  不兼容而出现「bad URL」「HUFFMAN」等错误占位图。

便携 Graphviz（标准 DFD）
=========================

标准数据流图（DFD）使用 **便携 Graphviz**，与 plantuml.jar 同级分发，
**不要求用户自行安装** Graphviz。

目录结构（须整包保留 bin + lib，不能只拷 dot.exe）
--------------------------------------------------
  graphviz/
    bin/
      dot.exe          — Windows 渲染入口
    lib/               — dot 依赖的 DLL（便携 zip 自带）

获取方式（开发 / 打包）
-----------------------
  在项目根目录执行：

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch-graphviz-portable.ps1

  脚本会从 Graphviz 官方 Release 下载 Windows x64 zip 并解压到本目录。
  大体积目录已加入 .gitignore；CI / 打包前需运行上述脚本。

  dot 查找顺序（dfd_render.py）：
    1. src/python/assets/graphviz/bin/dot.exe（便携，优先）
    2. 系统 PATH 中的 dot（开发机兜底，非用户必需）
    3. 均未找到 → 报错「未找到便携 Graphviz，请检查 assets/graphviz 是否完整」

Graphviz 快速自测
-----------------
  1) 检查便携 dot 版本：

    src\python\assets\graphviz\bin\dot.exe -V

  2) 渲染 DFD 样例 PNG（无需系统 Graphviz）：

    cd src\python
    python -c "import json, tempfile; from pathlib import Path; from dfd_render import render_dfd_png; sample={'kind':'dfd','title':'样例顶层图','dfd_json':{'level':'顶层','externals':[{'id':'user','name':'用户'}],'processes':[{'id':'p0','name':'0 系统'}],'stores':[],'flows':[{'from':'user','to':'p0','label':'请求'},{'from':'p0','to':'user','label':'响应'}]}}; p=Path(tempfile.gettempdir())/'dfd_test.png'; render_dfd_png(sample,p); print('OK',p,p.stat().st_size,'bytes')"

  输出含 OK 且字节数 > 100，说明便携 Graphviz + DFD 管道正常。

  3) 通过 API 查看环境状态：

    GET /api/runtime-status  →  diagram_tools.graphviz_ok 应为 true

PlantUML 快速自测（命令行）
---------------------------
  在项目根目录执行：

    cd src\python
    python -c "from pathlib import Path; import tempfile; from uml_render import render_plantuml_png; p=Path(tempfile.gettempdir())/'uml_test.png'; render_plantuml_png('@startuml\nclass A\nclass B\nA-->B\n@enduml', p, allow_online=False); print('OK', p, p.stat().st_size, 'bytes')"

  输出含 OK 且字节数 > 100，说明本地 JAR + Java 工作正常。

在解题能手 UI 中确认走本地渲染
------------------------------
  方法一（最可靠）：
    设置 → 取消勾选「UML 允许在线渲染」→ 重新运行「渲染 UML 图」或 ReAct 流程。
    若仍能生成正常类图/时序图（非带错误文字的占位图），则一定走的是本地 JAR。

  方法二（默认即可）：
    已放置 plantuml.jar 且 java -version 正常时，即使勾选在线渲染，程序也会
    先尝试本地；本地成功则不会请求 plantuml.com。

  方法三（看结果质量）：
    思考过程 / ReAct 轮次中应显示「UML 渲染完成，共 N 张」，且插入 Word 的
    图为正常 UML，而非含 “bad URL”“Syntax Error” 等英文错误文字的 PNG。

  方法四（断网验证）：
    断开网络后仅保留本地 JAR，取消在线渲染勾选，渲染仍成功即可确认。

未放置 jar 时
-------------
  可在设置中勾选「UML 允许在线渲染」使用 PlantUML 官方服务（需联网）。
  复杂中文类图可能因在线编码问题失败，建议始终配置本地 jar。

未放置 graphviz/ 时
-------------------
  DFD 渲染将失败并提示检查 assets/graphviz 目录完整性。
  请运行 scripts\fetch-graphviz-portable.ps1，勿引导用户去官网单独安装 Graphviz。
