# v2 立项 — 图片题目输入（含多图处理）

**状态**：📋 已立项，未开发  
**优先级**：v2 **高**（与 [V2_DOC_TEMPLATE_ADAPTATION.md](./V2_DOC_TEMPLATE_ADAPTATION.md) 并列；很多学校题在图里或「多页扫描图」）  
**关联**：[NEXT_VERSION_BACKLOG.md](./NEXT_VERSION_BACKLOG.md) C3（扫描 PDF 为本子集）

---

## 1. 背景：V1 不能「读题」，更不能「读多图题」

### V1 现状

| 能力 | 支持 |
|------|------|
| 从 Word/PDF **文字层**读题 | ✅（有限） |
| docx **内嵌图片**读题 | ❌ |
| 扫描 PDF / 拍照页 | ❌（仅 warn，见 C3 方向） |
| LLM **视觉/多模态**输入 | ❌（`llm_client` 仅纯文本 prompt） |
| **多张**题目图（多页、多嵌入图） | ❌ |

V1 图片相关能力全是 **输出**：运行截图、UML 渲染、填表插入 `images_b64`、分节工作台手动上传**结果图**。

### 用户真实场景（需多图）

| 场景 | 说明 |
|------|------|
| **超星 / 慕课作业页可复制文字** | ✅ Step1「粘贴题目 / 要求」→ `text_content`；与空模板 docx 组合即可（2026-06-05） |
| 实验要求页是 **截图/扫描图** | 段落几乎为空，warn `possible_missing_figures` |
| 一份 docx **多张嵌入图** | 第 1 页封面、第 2–4 页题目、第 5 页数据表 |
| **扫描 PDF 多页** | 每页一张图，无文字层 |
| Step1 **用户多选图片**当题目 | 目前无「上传题目图片组」入口 |
| 实训报告 **表格 + 单元格内图片** | 表格文字 + 图混排 |

**结论**：不仅要 OCR/视觉「能读一张图」，还要 **提取顺序、去重、合并、控 token、可选分页识题**。

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
| **分隔** | 合并时用 `\n\n--- 图 {order} ---\n\n` 保留溯源 |
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
| M6 | UI：**缩略图条**、勾选参与识题、拖拽排序 |
| M7 | **分页 PDF**：每页一图或文字层+渲染图混合策略 |
| M8 | Token/费用：**上限 N 张 vision** + 超出提示用户缩小范围 |

### 6.2 不建议 v2 首期做的

| 项 | 说明 |
|----|------|
| 自动区分「图内多道题」并拆分 | 可先合并识题，人工分节 |
| 视频、GIF 动图 | 仅静态图 |
| 手写公式高精度 LaTeX | 依赖 vision 质量，不保证 |

---

## 7. 分阶段交付（IM 系列）

| 阶段 | ID | 内容 | 依赖 |
|------|-----|------|------|
| 1 | **IM1** | docx 内嵌图导出 + `image_assets[]` + 去重排序 | — |
| 2 | **IM2** | 批量 OCR（Tesseract）→ 合并 `assignment_text` | IM1 |
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

## 9. 代码改造入口（预估）

| 模块 | 改动 |
|------|------|
| 新建 `document/extract_images.py` | docx/pdf 枚举、hash、顺序 |
| 新建 `document/image_read.py` | OCR batch、vision batch、merge |
| `modules/parse_report.py` | 解析后挂 `image_assets`；正文过短时自动尝试读图 |
| `llm_client.py` | `chat_vision()` / content parts |
| `server.py` `/api/parse-report` | 返回 `image_assets`、合并后的 `assignment_text` |
| `app.js` Step1 | 多图上传、缩略图条、排序 |
| `agent/planner.py` | `planner_input_text` 含 image 合并段（已有 budget 可裁剪） |

---

## 10. 给 Agent 的复制指令

```
在 lab-solver 只做 v2 图片题目输入的一个阶段（见 docs/V2_IMAGE_INPUT.md）：
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
| IM | 图片题目输入（总项） | 🔄 进行中 | 2026-06-03，含多图 |
| IM1 | docx 多图枚举 | ✅ 已完成 | 2026-06-04：`document/extract_images.py`、集成 `parse_report.py`/`server.py`/`parse_documents.py`、SHA-256 去重、角色猜测、34 个测试 |
| IM2 | 批量 OCR + 合并 | ⏳ 待做 | |
| IM3 | 扫描 PDF 多页（≈C3） | ⏳ 待做 | |
| IM4 | UI 多图上传/排序 | ⏳ 待做 | |
| IM5 | Vision 多模态 + hybrid | ⏳ 待做 | |
| FIX | 验收 I1–I6 fixtures | ⏳ 待做 | I1(枚举4张)已通过，I2(去重)已通过

---

*文档版本：2026-06-03 · 「不能解图片题 + 需多张图片处理」立项*
