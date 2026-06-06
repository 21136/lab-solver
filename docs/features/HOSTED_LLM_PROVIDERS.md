# 托管 LLM 提供商（内置 API Key）

**版本**: 2026-06-06  
**状态**: ✅ 已落地（Agnes AI）  
**关联**: [KEY_STORAGE.md](KEY_STORAGE.md) · `src/python/hosted_providers.py` · `src/python/llm_client.py` · 设置页 AI 配置

---

## 1. 背景

多数用户不愿自行注册 LLM 厂商、绑卡、填写 API Key。对部分**免费或开发者赞助**的模型，应用可在本机 Python 后端持久化一把 Key，用户选择对应提供商时**零配置**开玩。

与「用户 BYOK」并存：

| 模式 | 适用 provider | 用户是否填 Key |
|------|---------------|----------------|
| BYOK（默认） | DeepSeek、OpenAI、Claude、智谱、自定义 | 是 |
| **托管** | Agnes AI | **否** |

---

## 2. 用户侧行为

1. 设置 → **AI 配置** → 选择 **Agnes AI（免费·内置 Key）**
2. **不显示** API Key 输入框；展示「内置免费 Key」说明（`#hostedKeyNotice`）
3. 可直接 **测试连接**、**保存设置**、开始解题
4. 后端在每次 LLM 调用前通过 `resolve_llm_settings()` 注入托管 Key，**忽略**请求 body 中的空 `api_key`

### 2.1 能力边界（Agnes）

- 模型固定为 `agnes-2.0-flash`（OpenAI 兼容：`https://apihub.agnes-ai.com/v1`）
- **无**深度模式专用推理模型（不映射 `deepseek-reasoner`）
- **不支持** Vision 识图；题目截图请开 **OCR** 或改用 DeepSeek 等多模态 provider
- 代码题质量未经金样本充分验证，文档与 UI 均标注「实验性」；难题仍推荐 DeepSeek

---

## 3. 开发者 / 发行配置

### 3.1 Key 存储位置（优先级从高到低）

1. 环境变量 `AGNES_API_KEY`（见项目根 `.env.example`）
2. 本机文件 `%APPDATA%/lab-solver/hosted_agnes.key`（Windows；与 `config.APP_DATA` 一致）

文件内容为单行 Key 明文；写入时尝试 `0600` 权限。该路径**不在 git 仓库内**。

### 3.2 首次写入（Seed）

**方式 A — 应用内自动迁移（推荐）**

1. 开发者曾在设置里保存过 Agnes Key（`safeStorage` / localStorage）
2. 选择 provider = `agnes` 并 **保存设置**，或重启应用等待后端就绪
3. 前端调用 `POST /api/hosted-providers/agnes/seed`（仅当尚未配置时成功）
4. 成功后清除用户侧 Key 字段，后续一律走托管文件

**方式 B — 环境变量**

```bash
# .env（勿提交 git）
AGNES_API_KEY=your_key_here
```

**方式 C — 手动写文件**

```text
%APPDATA%\lab-solver\hosted_agnes.key
```

写入时请**勿用** PowerShell `Set-Content -Encoding utf8`（会带 BOM 导致连接报 `latin-1` 编码错误）。推荐用应用内 Seed、`save_hosted_api_key`，或 Python：

```python
from hosted_providers import save_hosted_api_key
save_hosted_api_key("agnes", "sk-...")
```

读取端已自动剥离 UTF-8 BOM（2026-06-06 修复）。

### 3.3 检查是否已配置

```http
GET /api/hosted-providers/status
```

响应示例：

```json
{
  "agnes": { "configured": true, "hosted": true }
}
```

---

## 4. 后端接口

| 路由 | 说明 |
|------|------|
| `GET /api/hosted-providers/status` | 各托管 provider 是否已配置 |
| `POST /api/hosted-providers/agnes/seed` | 一次性写入 Key（body: `api_key`）；已配置时返回 `already_configured` |

所有原 LLM 路由（`/api/solve`、`/api/agent/*`、`/api/test-connection`、`/api/tool/*`）在 `provider=agnes` 时经 `_llm_settings_from_request()` / `resolve_llm_settings()` 统一解析，无需客户端传 Key。

---

## 5. 代码地图

| 文件 | 职责 |
|------|------|
| `src/python/hosted_providers.py` | 托管 Key 读写、`resolve_llm_settings`、`llm_settings_error` |
| `src/python/server.py` | `_llm_settings_from_request`、status/seed 路由 |
| `src/python/llm_client.py` | `PROVIDER_URLS["agnes"]` |
| `src/renderer/app.js` | `isHostedProvider`、`needsUserApiKey`、`syncHostedProviderUI`、`seedHostedAgnesIfNeeded` |
| `src/renderer/index.html` | Agnes 预设、`#hostedKeyNotice`、隐藏 `#apiKeyGroup` |
| `tests/test_hosted_providers.py` | 单元测试 |

---

## 6. 安全与隐私

### 6.1 与用户 BYOK 的差异

| 项目 | BYOK | 托管 Agnes |
|------|------|------------|
| Key 存于 | Electron safeStorage（渲染进程） | Python `APP_DATA/hosted_agnes.key` |
| 是否上传作者服务器 | 否（直连接所选厂商） | 否（本机后端直连 Agnes） |
| 用户能否看到 Key | 可粘贴/可改 | 不可见 |
| 分发安装包风险 | 无内置 Key | **安装包或本机文件含 Key 时可被提取** |

### 6.2 残余风险

- 桌面版内置 Key 无法做到完全保密；仅适合**免费额度、实验档**定位
- 需在 Agnes 侧关注用量与滥用；后续可加本地限流 / 每日局数（未实现）
- 日志仍经 `log_util` 脱敏，禁止打印完整 Key

### 6.3 隐私说明文案

应用内合规说明仍以 [KEY_STORAGE.md](KEY_STORAGE.md) 为准；选择 Agnes 时 Key **不经用户输入**，由本机后端读取托管文件发往 Agnes API。

---

## 7. 扩展新托管 Provider

1. 在 `hosted_providers.HOSTED_PROVIDERS` 注册 id
2. `llm_client.PROVIDER_URLS` 增加 endpoint
3. 设置页 `onProviderChange` 增加 models / hints
4. 可选：增加 `hosted_{provider}.key` 与 seed 路由
5. 更新本文档与 README

---

## 8. 验收

- [x] `provider=agnes` 且无用户 Key 时可测试连接、解题
- [x] 设置页隐藏 API Key 输入
- [x] Seed 仅写入一次；已配置时不覆盖
- [x] `pytest tests/test_hosted_providers.py` 通过
- [x] `.env.example` 含 `AGNES_API_KEY` 占位
