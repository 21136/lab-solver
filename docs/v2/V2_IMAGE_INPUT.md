# v2 立项 — 图片题目输入（含多图处理）

**状态**：✅ 已落地（IM1–IM5 · UI-A/B · O30；**UI-C** 一图多题自动拆分仍 backlog）  
**优先级**：v2 **高**（与 [V2_DOC_TEMPLATE_ADAPTATION.md](V2_DOC_TEMPLATE_ADAPTATION.md) 并列；很多学校题在图里或「多页扫描图」）  
**关联**：[NEXT_VERSION_BACKLOG.md](../product/NEXT_VERSION_BACKLOG.md) C3（扫描 PDF 为本子集）· **[IM_OCR_FIRST.md](IM_OCR_FIRST.md)**（OCR 优先实施细节，不依赖多模态）

---

## 1. 背景与现状

### 1.1 V1 起点（立项前）

| 能力 | V1 |
|------|-----|
| Word/PDF **文字层**读题 | ✅（有限） |
| docx **内嵌图片**读题 | ❌ |
| 扫描 PDF / 拍照页 | ❌ |
| 多图合并进 Planner | ❌ |

### 1.2 当前能力（2026-06-06 · IM 已落地）

| 能力 | 模块 | 默认 |
|------|------|------|
| docx 内嵌图枚举 + 去重 | `extract_images.py` (IM1) | ✅ |
| 本地 OCR → `assignment_text` | `image_read.py` (IM2) | 设置关；正文极短/扫描 PDF 可自动 |
| 扫描 PDF 按页渲染 + OCR | `extract_pdf.render_pdf_pages` (IM3) | 无文字层自动 |
| Step1 题目图组上传/排序 | `user_upload_images.py` + UI (IM4) | 用户勾选参与识题 |
| Vision hybrid（OCR 不足回退） | `llm_client.chat_vision` (IM5) | **opt-in**，`imageReadingMode` |
| 识题预览 O30 | Step2 UI (UI-B) | 可编辑 · 确认后 plan |

**Agent 仍只吃文本**：OCR/Vision 结果在 parse 阶段合并进 `planner_input_text`，solve/plan 不调多模态（`ocr_only` 模式下）。

### 1.3 用户场景对照

| 场景 | 状态 |
|------|------|
| 粘贴题目文字 | ✅ `text_content` |
| 截图/扫描页作题目 | ✅ IM4 上传 或 IM3 扫描 PDF |
| docx 多嵌入图 | ✅ IM1 枚举 + IM2 OCR |
| 表格 + 单元格内图 | ⚠️ DA1 联动待做；图可走 IM1 |
| 一图多道题自动拆分 | 📝 UI-C backlog（现 warn + O30 手改） |

**残余目标**：DA 表格模版、UI-C 一图多题、打包内置 Tesseract（O27）。

---

## 2. v2 目标

1. 从文档或用户上传中 **枚举全部题目相关图片**（有序列表）  
2. 对每张图 **OCR 和/或 Vision** 抽出文字/结构  
3. **多图合并** 为 `assignment_text` / `image_captions[]`，供 Planner、solve 使用  
4. UI 可 **预览、勾选、调序、丢弃**（签名/装饰图）  
5. 与 C3 扫描 PDF 共用底层，但 **不局限于 PDF**

---

## 3. 图片来源 taxonomy

| `image_source` | 提取方式 |
|----------------|----------|
| `docx_inline` | 遍历 `doc.part.related_parts` / paragraph runs 内 `drawing`，按 **文档顺序** |
| `docx_table_cell` | 表格单元格内嵌图（与 DA1 表格抽取联动） |
| `pdf_page_render` | 无文字层或文字过少 → 按页渲染为图（PyMuPDF `get_pixmap`） |
| `pdf_embedded` | PDF 内嵌 XObject 图 |
| `user_upload` | Step1 多文件 `image/*`，用户指定为「题目图组」 |

---

## 4. 核心数据结构

### 4.1 `image_assets[]`（解析后）

```json
{
  "image_assets": [
    {
      "id": "img_001",
      "source": "docx_inline",
      "order": 0,
      "page_hint": 1,
      "mime": "image/png",
      "bytes_b64": "...",
      "sha256": "...",
      "nearby_text": "图1 实验要求",
      "role_guess": "assignment",
      "ocr_text": "",
      "vision_summary": ""
    }
  ],
  "image_bundle_meta": {
    "total": 4,
    "deduped": 3,
    "extraction_warnings": []
  }
}
```

### 4.2 合并进 Agent 上下文

```json
{
  "assignment_text": "（OCR/vision 合并后的全文）",
  "assignment_from_images": true,
  "image_reading_mode": "ocr_only | vision | hybrid",
  "image_sections": [
    { "image_id": "img_001", "text": "第一页：实验目的…" },
    { "image_id": "img_002", "text": "第二页：步骤要求…" }
  ]
}
```

**多图合并规则（建议）**：

| 规则 | 说明 |
|------|------|
| **顺序** | 文档流顺序 > 页码 > 用户拖拽顺序 |
| **去重** | 相同 `sha256` 合并（Word 合并单元格常 duplicate 同图） |
| **分隔** | OCR 路径：`\n\n--- 图 {order}（OCR）---\n\n`；Vision 路径可沿用 `--- 图 {order} ---`（见 [IM_OCR_FIRST.md](IM_OCR_FIRST.md) §4.1） |
| **过滤** | `role_guess=signature|decoration` 默认不进 assignment，UI 可勾选纳入 |
| **Token 预算** | 超预算时：先 OCR 全文拼 text；vision 仅对 **低 OCR 置信度** 或用户标记的页 |

---

## 5. 识别策略（OCR vs Vision）

| 模式 | 适用 | 成本 |
|------|------|------|
| `ocr_only` | 扫描件、文字为主 | 低，本地/ Tesseract |
| `vision` | 含电路图、界面截图、公式、表格图 | 高，需多模态 API |
| `hybrid` | 默认：先 OCR，空/乱码/过短再 vision | 中 |

**多模态 API（v2 需扩展 `llm_client`）**：

- 支持 `messages[].content` 为 `[{type:text},{type:image_url}]`  
- 按 **张** 或 **批** 调用（见 §6）  
- 设置页：是否启用 vision、最大张数、provider 是否支持

---

## 6. 多图处理要点（立项重点）

### 6.1 必须实现的「多图」能力

| ID | 能力 |
|----|------|
| M1 | **枚举** docx/pdf 内全部候选图，不单张 |
| M2 | **稳定排序** + 页码/锚点段落关联 |
| M3 | **去重**（hash / 感知 hash 可选） |
| M4 | **批量 OCR** 流水线，失败单张不拖死整份 |
| M5 | **合并文本** 进 `assignment_text`，Planner 无感接入 |
| M6 | UI：**缩略图条**、勾选参与识题、拖拽排序（与 `assignment_images` 顺序一致） |
| M7 | **分页 PDF**：每页一图或文字层+渲染图混合策略 |
| M8 | Token/费用：**上限 N 张 vision** + 超出提示用户缩小范围（Step1 模式提示 + Step2 warn） |

### 6.2 不建议 v2 首期做的

| 项 | 说明 |
|----|------|
| 自动区分「图内多道题」并拆分 | v2 **不自动拆分**；`multi_question_in_image` warn + O30 人工编辑（backlog：启发式子段） |
| 视频、GIF 动图 | 仅静态图 |
| 手写公式高精度 LaTeX | 依赖 vision 质量，不保证 |

---

## 7. 分阶段交付（IM 系列）

| 阶段 | ID | 内容 | 依赖 |
|------|-----|------|------|
| 1 | **IM1** | docx 内嵌图导出 + `image_assets[]` + 去重排序 | — |
| 2 | **IM2** | 批量 OCR（Tesseract）→ 合并 `assignment_text`（**IM2-a** 后端 ✅；**IM2-b** 设置/O30 待做） | IM1 |
| 3 | **IM3** | 扫描 PDF 按页渲染 + OCR（扩展 C3） | IM2 |
| 4 | **IM4** | Step1「题目图片组」多文件上传 + UI 预览/排序 | IM2 |
| 5 | **IM5** | `llm_client` vision 多模态 + hybrid 策略 + 张数上限 | IM2，可选 API |

**与 C3 关系**：C3 = **IM3** 为主；完整图片题 = **IM1–IM5**。

**与 DA 关系**：表格单元格内图 → DA1 抽表时调用 IM1 枚举 cell 内图。

---

## 8. 验收用例

| ID | 场景 | 通过标准 |
|----|------|----------|
| I1 | docx 含 3 张嵌入图（题目），1 张签名图 | 枚举 4 张；默认 3 张进 assignment；签名可过滤 |
| I2 | 同一图在合并单元格重复出现 | 去重后 1 张 |
| I3 | 5 页扫描 PDF，无文字层 | 5 页 OCR 合并；顺序正确 |
| I4 | 用户 Step1 上传 4 张 png 题目 | 预览、调序后 plan 可见合并题干 |
| I5 | hybrid：OCR 空页走 vision（mock） | 该页有 text 进入 assignment |
| I6 | 超过 vision 上限 N 张 | UI 提示选择范围，不 silent 截断 |

Fixtures：`tests/fixtures/image_input/`（合成 docx 多图、多页 pdf）。

---

## 9. 代码改造入口

| 模块 | 改动 | 状态 |
|------|------|------|
| `document/extract_images.py` | docx 枚举、hash、顺序 | ✅ IM1 |
| `document/extract_pdf.py` | 扫描 PDF 按页 `get_pixmap` → `image_assets` | ✅ IM3 |
| `document/image_read.py` | `ocr_image_asset` / `ocr_batch` / `merge_assignment_from_images` / `apply_image_reading` | ✅ IM2-a |
| `config.py` | `OCR_OK` 探测（Tesseract + pytesseract，可选依赖） | ✅ IM2-a |
| `modules/parse_report.py` | 挂 `image_assets`；§6 触发 OCR；`assignment_text` / `image_sections` | ✅ IM2-a |
| `agent/parse_documents.py` | OCR 合并段进 `assignment_text` → `planner_input_text` | ✅ IM2-a |
| `server.py` `/api/parse-report` | 接受 `enableImageOcr`；返回 `image_assets`、`assignment_text`、`image_read_summary` 等 | ✅ IM2-a（API 参数；设置页 IM2-b） |
| `llm_client.py` | `chat_vision()` / `supports_vision()` / content parts | ✅ IM5 |
| `document/user_upload_images.py` | Step1 题目图组 → `image_assets`（`source=user_upload`） | ✅ IM4 |
| `app.js` Step1 | 多图上传、缩略图条、勾选、拖拽排序、识图模式/上限提示 | ✅ IM4 + UI-A |
| `app.js` Step2 O30 | `assignment_text` / `image_sections` 可编辑、ocr/vision 来源、生成计划前确认 | ✅ UI-B |
| `settings_schema` + 设置页 | `enableImageOcr` 等开关 | ✅ IM2-b |
| `agent/planner.py` | 消费 `planner_input_text`（已有 `prompt_budget` 裁剪） | 无改动 |

---

## 10. 给 Agent 的复制指令

```
在 lab-solver 只做 v2 图片题目输入的一个阶段（见 docs/v2/V2_IMAGE_INPUT.md）：
- 本次做：IM[1-5] — [具体描述]
- 必须考虑多图：顺序、去重、合并 assignment_text
- 标准 docx 无图回归必须通过
- 补 tests/fixtures/image_input/ + test_image_input.py
- 完成后更新本文档 §11 状态表
```

---

## 11. 状态跟踪

| ID | 项 | 状态 | 备注 |
|----|-----|------|------|
| IM | 图片题目输入（总项） | ✅ 已落地 | 2026-06-06；UI-C 除外 |
| IM1 | docx 多图枚举 | ✅ 已完成 | 2026-06-04：`document/extract_images.py`、集成 `parse_report.py`/`server.py`/`parse_documents.py`、SHA-256 去重、角色猜测 |
| IM2-a | OCR 核心 + parse 集成 | ✅ 已完成 | 2026-06-06：`document/image_read.py`、`config.OCR_OK`、`parse_report`/`parse_documents`；`tests/fixtures/image_input/`；验收 O1/O2/O4/O5 |
| IM2-b | 设置开关 + O30 识题预览 | ✅ 已完成 | 2026-06-06：设置页 OCR 开关 · parse warn 引导 · Step2 识题预览；验收 O6 |
| IM3 | 扫描 PDF 多页（≈C3） | ✅ 已完成 | 2026-06-06：`render_pdf_pages` · `pdf_page_render` · `pdf_scanned` 自动 OCR · O3/I3 |
| IM4 | UI 多图上传/排序 | ✅ 已完成 | 2026-06-06：`user_upload_images.py` · Step1 缩略图条 · `assignment_images` API · I4 |
| IM5 | Vision 多模态 + hybrid | ✅ 已完成 | 2026-06-06：`llm_client.chat_vision` · `image_read.vision_batch` · hybrid 回退 · `imageVisionMaxPages` · I5/I6 |
| UI-A | Step1 题目图组 polish | ✅ 已完成 | 2026-06-06：勾选/排序与 API 一致 · hybrid/vision/上限提示 · 未勾选灰显 |
| UI-B | Step2 O30 识题预览增强 | ✅ 已完成 | 2026-06-06：`image_sections` 分节 + ocr/vision 标识 · 可编辑 · 确认后 plan · `assignment_text` 覆盖 |
| UI-C | 一图多题 | 📝 backlog | 2026-06-06：`multi_question_in_image` warn，不 silent 合并；自动拆分为后续 |
| FIX | 验收 I1–I6 / O1–O6 fixtures | ✅ 已完成 | I1–I6 · O1–O6（`test_image_input.py` + fixtures） |

---

*文档版本：2026-06-03 · 「不能解图片题 + 需多张图片处理」立项*
