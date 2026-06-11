# 解题能手 · Lab Solver

> **实验报告内容生成器** — 上传题目与模版，AI 生成结构化答案（文字、代码、图表），由你自行落笔提交。

[![GitHub](https://img.shields.io/badge/GitHub-21136%2Flab--solver-181717?logo=github)](https://github.com/21136/lab-solver)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](requirements.txt)
[![Electron 31](https://img.shields.io/badge/Electron-31-47848F.svg)](package.json)

**Lab Solver** is a desktop app (Electron + Python) that helps students draft lab reports with their own LLM API key. It generates structured deliverables — prose, code, and diagrams — for you to review, copy, and paste into your school's template. It is **not** a ghostwriting service or an auto-submit tool.

---

## 核心能力

- **多格式读题** — 支持 `.doc` / `.docx` / `.pdf`、粘贴纯文本、题目截图（OCR + Vision）
- **结构化生成** — 实验分析、结果说明、总结、可运行代码、PlantUML / DFD 图表
- **三种运行模式**
  - **标准** — 计划 → 执行，约 2 次 LLM 调用，适合多数实验
  - **深度** — 理解 → 分阶段解题 → 审稿修订，质量更高
  - **ReAct** — 工具调用循环，复杂题目可自动编排多步
- **答案工作区（V5 主路径）** — 分节复制、下载 Markdown / docx / 代码 zip；诚信标注可选
- **内化验证（可选）** — 在本地沙箱试编译/试跑，仅用于提高生成质量，不替代你的实验环境
- **工具箱模式** — 解析、解题、图表渲染、校验等 8 个独立工具，可单步调试
- **自带 API Key** — 支持 DeepSeek、OpenAI、Claude、智谱及自定义 OpenAI 兼容端点；Key 经本机加密存储，不上传作者服务器
- **Agnes 免费档（零配置）** — 可选 **Agnes AI（内置 Key）**，无需注册或填写 Key；适合快速试玩，代码题仍推荐 DeepSeek

### 我们刻意不主打的事

根据 [V5 产品定位](docs/product/V5_PRODUCT_PIVOT.md)，本工具**不是**在线 IDE，也**不是** Word 自动填表机。自动写回 Word 模版为**高级 / 实验性**功能，版式因学校模版差异无法保证。

---

## 快速开始

### 下载安装包（推荐）

[GitHub Releases](https://github.com/21136/lab-solver/releases/latest) 提供 Windows 安装包（`.exe`），下载后双击安装即可。首次使用可在 **设置** 页选择 **Agnes AI（内置 Key）** 零配置试玩，或为 DeepSeek 等提供商填入 API Key。

> 安装包未经代码签名，Windows 可能提示 SmartScreen，选择「仍要运行」即可。

### 从源码运行

#### 环境要求

| 组件 | 版本 |
|------|------|
| Windows | 10 / 11（当前主要支持平台） |
| Python | 3.8+ |
| Node.js | 18+ |

**可选依赖**（按需安装，应用内会有引导）：

- **Tesseract OCR** — 题目截图文字识别
- **Java / GCC** — 代码内化验证
- **Microsoft Word 或 LibreOffice** — 旧版 `.doc` 转换

```bash
git clone https://github.com/21136/lab-solver.git
cd lab-solver

# Windows：一键启动（自动 pip install + npm install）
start.bat
```

或手动：

```bash
pip install -r requirements.txt
npm install
npm start
```

首次使用会弹出 **免责声明**：勾选条款后点「我已阅读并同意」。随后在 **设置** 页选择 AI 提供商：选 **Agnes AI** 可免填 Key；选 DeepSeek 等则需填入 **API Key** 与模型名称。

### 自行打包安装包（Windows，开发者）

脚本使用相对路径（`%~dp0` / `$RepoRoot`），**不绑定你的电脑路径**；克隆仓库后在项目根目录运行即可：

```bash
build-installer.bat
```

产物复制到 `installer/`（已在 `.gitignore` 中，不进入 git）。发布到 GitHub Releases：

```powershell
gh auth login   # 首次需登录
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/publish-release.ps1
```

默认创建 tag `v1.0.1` 并上传 `installer/LabSolver-Setup-1.0.0-win64.exe`。勿将安装包 commit 进 git。

### 仅启动后端 API

```bash
python src/python/server.py
```

默认监听 `http://127.0.0.1:5199`。

---

## 使用流程

```
① 上传报告 / 题目（doc · docx · pdf · 图片 · 粘贴）
        ↓
② 确认解题计划（可选：生成约束、运行模式、分节配置）
        ↓
③ 答案工作区 — 审阅 · 分节复制 · 导出
        ↓
   自行粘贴到学校模版 / 学习通 / 石墨文档
```

---

## 开发与测试

```bash
# 安装开发依赖
pip install -r requirements-dev.txt

# 运行全部 pytest
scripts\run-tests.bat

# 或
python -m pytest
```

项目包含 **50+** 测试文件，覆盖 Planner、解题流水线、ReAct、图表渲染、图片输入及 golden 回归等。

---

## 技术架构

| 层 | 技术 |
|----|------|
| 桌面壳 | Electron 31 · `main.js` · `preload.js` |
| 前端 | 原生 HTML / CSS / JS · Monaco Editor |
| 后端 | Python Flask · `src/python/server.py` |
| Agent | Planner → Executor · DeepPipeline · ReAct · 模块化 `registry` |
| 文档 | python-docx · PyMuPDF · 可选 Word COM / LibreOffice |
| 图表 | PlantUML（本地 JAR + 在线）· 便携 Graphviz（DFD） |

```
上传文档 → parse_documents → Planner → Executor / DeepPipeline / ReAct
                                              ↓
                                    Deliverable（答案包）→ Step 3 工作区
```

详细设计见 [docs/README.md](docs/README.md) 与 [CLAUDE.md](CLAUDE.md)（协作者 / AI 用项目地图）。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/product/V5_PRODUCT_PIVOT.md](docs/product/V5_PRODUCT_PIVOT.md) | 当前产品定位 |
| [docs/architecture/LAB_SOLVER_AGENT_PLAN.md](docs/architecture/LAB_SOLVER_AGENT_PLAN.md) | Agent 完整架构 |
| [DESIGN.md](DESIGN.md) | UI 设计规范 |
| [docs/features/KEY_STORAGE.md](docs/features/KEY_STORAGE.md) | API Key 本地加密方案 |
| [docs/features/HOSTED_LLM_PROVIDERS.md](docs/features/HOSTED_LLM_PROVIDERS.md) | Agnes 等托管 Key（零配置） |
| [docs/features/MODEL_REGISTRY.md](docs/features/MODEL_REGISTRY.md) | 模型 catalog 与弃用迁移 |

---

## 隐私与安全

- **BYOK**（DeepSeek / OpenAI 等）：API Key 优先通过 Electron `safeStorage` 加密保存在本机；Python 后端不持久化用户 Key
- **Agnes 托管档**：Key 存于本机 `%APPDATA%/lab-solver/hosted_agnes.key`（或环境变量 `AGNES_API_KEY`），用户不可见；详见 [HOSTED_LLM_PROVIDERS.md](docs/features/HOSTED_LLM_PROVIDERS.md)
- 实验报告全文会按你的设置发送至所选 AI 服务商用于解题
- 运行日志经脱敏后写入本机，便于排查问题

详见应用内 **隐私说明**、[KEY_STORAGE.md](docs/features/KEY_STORAGE.md) 与 [HOSTED_LLM_PROVIDERS.md](docs/features/HOSTED_LLM_PROVIDERS.md)。

---

## 免责声明

本软件仅供**课程学习与实验报告写作参考**，不构成代写或学术不端服务。

- AI 生成内容可能存在错误，请**自行核对、修改**并承担提交后果
- 请勿将 AI 输出或范文**原样照抄**提交
- 学术诚信与成绩责任由**用户本人**承担

---

## 贡献

Issue 与 Pull Request 欢迎。大型改动请先阅读 [docs/architecture/IMPLEMENTATION_PHASES.md](docs/architecture/IMPLEMENTATION_PHASES.md) 了解当前阶段边界。

---

## License

[MIT](LICENSE)

---

## English Summary

**Lab Solver** is a Windows desktop app for drafting university lab reports with your own LLM API key (DeepSeek, OpenAI, Claude, custom endpoints) or zero-config **Agnes AI (hosted key)**. Upload assignments as Word/PDF/images, choose standard/deep/ReAct solving modes, and export structured answers (text, code, UML/DFD diagrams) from a review workspace. BYOK with local key encryption, optional sandboxed code verification. Not intended for plagiarism — users must review and adapt all output before submission.

```bash
start.bat    # Windows quick start
```
