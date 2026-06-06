# API Key 存储：Electron safeStorage 与风险说明

> Phase 3 子集 `phase3-key-storage` — safeStorage 落地 + 文档留档 + 设置页提示。  
> Python 后端**不**持久化 Key；运行日志经脱敏后写入 `app.log`。

---

## 1. 现状（已实现）

| 项目 | 说明 |
|------|------|
| 首选存储 | 主进程 `safeStorage.encryptString` → Base64 密文写入 `localStorage['settings'].apiKeyEncrypted` |
| 降级存储 | `isEncryptionAvailable() === false` 时保留明文 `apiKey`，并 Toast 提示用户 |
| 实现文件 | `src/main/settings-store.js`（IPC）、`src/renderer/app.js`（迁移/读写）、`preload.js` |
| 内存使用 | 解密后的 Key 仅保留在渲染进程 `_runtimeApiKey`，供 API 请求 body 使用 |
| 服务端持久化 | **无** — Python 后端不将 Key 写入磁盘或数据库 |
| 日志 | `src/python/log_util.py` 对 `api_key`、`Bearer …`、`sk-…` 等模式脱敏后再写 `app.log` |

首次启动若检测到旧版明文 `apiKey`，会在加密可用时自动迁移为 `apiKeyEncrypted` 并删除明文字段（`schema_version` 递增至 2）。

---

## 2. Electron `safeStorage` 调研摘要

官方文档：[safeStorage | Electron](https://www.electronjs.org/docs/latest/api/safe-storage)

### 2.1 API

```javascript
const { safeStorage } = require('electron');

safeStorage.isEncryptionAvailable();   // 当前环境是否可用 OS 级加密
safeStorage.encryptString(plainText);  // string → Buffer（密文）
safeStorage.decryptString(buffer);     // Buffer → string（明文）
```

须在主进程调用；渲染进程通过 IPC（`settings-store:encrypt-api-key` / `decrypt-api-key`）访问。

### 2.2 各平台行为

| 平台 | 底层机制 | `isEncryptionAvailable()` |
|------|----------|---------------------------|
| **Windows** | DPAPI（与用户/机器绑定） | `ready` 后一般为 `true` |
| **macOS** | Keychain | Keychain 可用时为 `true` |
| **Linux** | GNOME libsecret、KWallet 等 | 需桌面密钥环；否则可能为 `false` |

Linux 无密钥环时可退化为弱于系统密钥环的加密，仍优于长期明文；本应用在不可用时**显式降级**并提示用户。

### 2.3 已知限制

- **跨机器/重装系统**：DPAPI / Keychain 密文通常无法在新环境解密；用户需重新填写 Key。
- **调用 LLM 时**：Key 仍会进入 HTTPS 请求头/body；风险在「本地静态存储」而非传输（依赖 TLS + 用户所选厂商）。
- **DevTools**：调试时仍可能通过内存或 IPC 看到明文；safeStorage 主要防「磁盘上被其他程序直接读取明文」。

---

## 3. 设置页用户提示（与 UI 一致）

设置页 API Key 表单项下方 `#keyStorageNotice`（标题固定为 **Key 存于本机**），正文由 `updateKeyStorageNotice()` 按加密可用性切换：

**系统加密可用（Windows/macOS 常见）：**

> 经操作系统加密（safeStorage）后保存在本机，不会上传至软件作者服务器；调用 AI 时经 HTTPS 发送至您选择的厂商。请勿在公共或共享电脑上保存 Key。

**系统加密不可用（降级）：**

> 系统加密不可用，Key 以明文保存在本机浏览器存储中，不会上传至软件作者服务器；调用 AI 时经 HTTPS 发送至您选择的厂商。请勿在公共或共享电脑上保存 Key。

降级时另有一次性 Toast：

> 系统密钥环不可用，API Key 将以明文保存在本机存储中。请勿在公共或共享电脑上保存 Key。

---

## 4. 风险说明

### 4.1 已缓解

- Key **不会**上传至本软件作者服务器（仅发往用户配置的 AI 厂商）。
- 后端日志**不会**记录完整 Key（见 `log_util._KEY_PATTERNS`；验收见 `tests/test_log_util.py`）。
- 设置页 **password** 输入框 + 上述「Key 存于本机」说明，提醒勿在公共电脑保存。

### 4.2 残余风险

| 风险 | 严重度 | 说明 |
|------|--------|------|
| 降级路径明文 localStorage | 中 | Linux 无密钥环或加密失败时，LevelDB 中仍可能存明文 |
| 内存与 DevTools | 低～中 | 调试或恶意扩展可读取运行时 Key |
| 请求 body 中的 Key | 低 | 仅 localhost Python 进程；不写入服务端文件 |
| 用户误分享 settings 备份 | 低 | 若未来加「导出设置」须排除 Key 字段 |

---

## 5. 验收对照

- [x] 本文档记录 safeStorage 能力与风险
- [x] 设置页文案与 §3 一致（`index.html` + `app.js` `updateKeyStorageNotice`）
- [x] Key 不进 `app.log`（`log_util.sanitize_log_message` + `tests/test_log_util.py`）
- [x] 不修改 Agent 核心与 PDF 导出

---

## 6. 参考

- [Electron safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
- 项目内：`src/main/settings-store.js`、`src/renderer/app.js`、`src/python/log_util.py`
