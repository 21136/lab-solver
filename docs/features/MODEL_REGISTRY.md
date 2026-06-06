# LLM 模型注册表与弃用迁移

**版本**: 2026-06-06  
**状态**: ✅ 已落地  
**关联**: `src/python/model_registry.py` · `GET /api/llm-models` · 设置页模型下拉

---

## 1. 问题

设置页若**硬编码**各厂商 model id（如 `deepseek-chat`），厂商弃用后：

- 老用户 localStorage 里仍是旧 id
- 新安装仍选到失效模型
- 需改 HTML + JS + Python 多处

---

## 2. 方案概览

| 层 | 职责 |
|----|------|
| **`model_registry.py`** | 唯一 catalog、弃用别名、API 请求解析（含 DeepSeek thinking） |
| **`GET /api/llm-models`** | 前端拉取模型列表，弃用后**只改 Python 一处** |
| **设置迁移 v6** | `deepseek-chat` / `deepseek-reasoner` → `deepseek-v4-flash` |
| **`llm_client`** | 发请求前 `resolve_model_for_api()`，自动加 `thinking` / `reasoning_effort` |

---

## 3. DeepSeek V4 迁移（2026-07-24 截止）

| 旧 id（将弃用） | 新 id | 模式 |
|----------------|-------|------|
| `deepseek-chat` | `deepseek-v4-flash` | 非思考 `thinking: disabled` |
| `deepseek-reasoner` | `deepseek-v4-flash` | 思考 `thinking: enabled` |

V4 不再用两个 model 名区分推理，而是用**同一 model + 参数**：

```json
{
  "model": "deepseek-v4-flash",
  "thinking": { "type": "enabled" },
  "reasoning_effort": "high"
}
```

本应用规则：

- **标准 run_mode** + `deepseek-v4-flash` → `thinking: disabled`
- **深度 run_mode** + `deepseek-v4-flash` / `deepseek-v4-pro` → `thinking: enabled`
- 用户 settings 里仍只存 catalog id（如 `deepseek-v4-flash`），不再存 `deepseek-reasoner`

---

## 4. 维护者：如何更新 catalog

编辑 **`src/python/model_registry.py`** 中 `_PROVIDER_MODELS`：

```python
_PROVIDER_MODELS = {
    "deepseek": [
        {"id": "deepseek-v4-flash", "label": "...", "default": True, ...},
        # 新增 deepseek-v4-xxx 时在此追加
    ],
    "agnes": [
        {"id": "agnes-2.0-flash", ...},  # Agnes 改名时改 id + 加 deprecated_aliases
    ],
}
```

若需兼容旧 id，加入 `_DEPRECATED_ALIASES`：

```python
_DEPRECATED_ALIASES = {
    "agnes-2.0-flash": {"api_model": "agnes-3.0-flash", "thinking": "disabled"},
}
```

然后：

1.  bump `MODEL_CATALOG_VERSION`（可选，便于前端缓存失效）
2.  必要时 bump `SETTINGS_SCHEMA_VERSION` 并在 `app.js` `mergeSettings` 写迁移
3.  跑 `pytest tests/test_model_registry.py`

前端 **FALLBACK_MODEL_CATALOG**（`app.js`）应与 Python 保持同步；后端不可用时作离线兜底。

---

## 5. API

### `GET /api/llm-models`

返回 `catalog_version`、`providers`、`defaults`、`deprecated_aliases`。

设置页 `ensureModelCatalog()` 启动时拉取；`onProviderChange()` 动态渲染 `#modelSelect`。

---

## 6. 自定义 API

`custom` provider 仍允许任意 model 字符串；catalog 仅提供占位 `custom-model`，用户可在后续版本改为文本输入（未实现）。

---

## 7. 验收

- [x] 新默认 `deepseek-v4-flash`
- [x] 旧 settings 自动迁移
- [x] 深度模式走 thinking 参数而非换 model 名
- [x] `tests/test_model_registry.py`
