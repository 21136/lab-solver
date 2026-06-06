"""IM1: docx embedded image extraction tests."""

import base64
import hashlib
import io
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "python"))

from document.extract_images import (
    _body_texts,
    _guess_role,
    _image_pixel_size,
    _nearby_text,
    _sha256_hex,
    extract_docx_images,
)
from modules.parse_report import build_question_from_document, extract_docx

# ── helpers ────────────────────────────────────────────────────────────


def _make_test_docx(paragraphs_before=0, images=None, paragraphs_after=0):
    """Create a temp docx with optional images at a known position. Returns path."""
    from docx import Document
    from docx.shared import Inches

    if images is None:
        images = []
    doc = Document()
    for text in (paragraphs_before if isinstance(paragraphs_before, list)
                 else [f"Para {i}" for i in range(paragraphs_before)]):
        doc.add_paragraph(str(text))
    for img_path in images:
        doc.add_picture(str(img_path), width=Inches(2))
    for text in (paragraphs_after if isinstance(paragraphs_after, list)
                 else [f"Para after {i}" for i in range(paragraphs_after)]):
        doc.add_paragraph(str(text))

    tmp = tempfile.gettempdir() / Path(f"test_img_{hash(str(images))}.docx")
    # Use a simpler path
    tmp = Path(tempfile.gettempdir()) / f"test_im1_{len(images)}img.docx"
    doc.save(str(tmp))
    return tmp


def _make_test_png(width=200, height=100, color="red"):
    """Create a small test PNG in a temp file. Returns path."""
    img = Image.new("RGB", (width, height), color=color)
    tmp = Path(tempfile.gettempdir()) / f"test_{width}x{height}_{color}.png"
    img.save(str(tmp))
    return tmp


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── unit tests ─────────────────────────────────────────────────────────


class TestSha256:
    def test_deterministic(self):
        assert _sha256_hex(b"hello") == _sha256_hex(b"hello")

    def test_different_data(self):
        assert _sha256_hex(b"hello") != _sha256_hex(b"world")


class TestImagePixelSize:
    def test_known_size(self):
        tmp = _make_test_png(200, 100)
        blob = tmp.read_bytes()
        w, h = _image_pixel_size(blob)
        assert w == 200
        assert h == 100

    def test_invalid_blob(self):
        w, h = _image_pixel_size(b"not an image")
        assert w == 0
        assert h == 0


class TestGuessRole:
    def test_signature_keyword(self):
        assert _guess_role("请在此处签名", 300, 300) == "signature"
        assert _guess_role("盖章处", 300, 300) == "signature"

    def test_signature_size(self):
        assert _guess_role("", 150, 50) == "signature"

    def test_decoration_keyword(self):
        assert _guess_role("学校logo", 300, 300) == "decoration"

    def test_decoration_size(self):
        assert _guess_role("", 40, 40) == "decoration"

    def test_assignment_keyword(self):
        assert _guess_role("实验目的", 300, 300) == "assignment"
        assert _guess_role("电路图如下", 300, 300) == "assignment"

    def test_assignment_by_size(self):
        assert _guess_role("", 500, 400) == "assignment"

    def test_unknown(self):
        assert _guess_role("", 250, 150) == "unknown"


class TestNearbyText:
    def test_surrounding_text(self):
        texts = ["one", "", "two", "three", ""]
        result = _nearby_text(texts, 1)  # center element
        assert "one" in result
        assert "two" in result

    def test_edge_position(self):
        texts = ["first", "second", "third"]
        result = _nearby_text(texts, 0)  # first element
        assert "second" in result
        assert "first" not in result

    def test_empty_texts(self):
        result = _nearby_text([], 0)
        assert result == ""


class TestBodyTexts:
    def test_empty(self):
        assert _body_texts([]) == []


# ── integration tests ──────────────────────────────────────────────────


class TestExtractDocxImages:
    def test_no_images(self):
        path = _make_test_docx(paragraphs_before=3)
        result = extract_docx_images(path)
        assert result["image_assets"] == []
        assert result["image_bundle_meta"]["total"] == 0
        assert result["image_bundle_meta"]["deduped"] == 0

    def test_single_image(self):
        img = _make_test_png(300, 200, "blue")
        path = _make_test_docx(
            paragraphs_before=["实验目的"],
            images=[img],
            paragraphs_after=["请完成实验"],
        )
        result = extract_docx_images(path)
        assert len(result["image_assets"]) == 1
        asset = result["image_assets"][0]
        assert asset["source"] == "docx_inline"
        assert asset["mime"] == "image/png"
        assert asset["order"] == 0
        assert len(asset["bytes_b64"]) > 0
        assert asset["sha256"] == _sha256_file(img)
        assert "实验目的" in asset["nearby_text"]
        assert "请完成实验" in asset["nearby_text"]

    def test_multiple_images_ordered(self):
        img1 = _make_test_png(300, 200, "red")
        img2 = _make_test_png(400, 300, "green")
        img3 = _make_test_png(500, 400, "blue")
        path = _make_test_docx(
            paragraphs_before=["Start"],
            images=[img1, img2, img3],
            paragraphs_after=["End"],
        )
        result = extract_docx_images(path)
        assert len(result["image_assets"]) == 3
        assert result["image_assets"][0]["order"] == 0
        assert result["image_assets"][1]["order"] == 1
        assert result["image_assets"][2]["order"] == 2
        # Verify ordering through sha256
        assert result["image_assets"][0]["sha256"] == _sha256_file(img1)
        assert result["image_assets"][1]["sha256"] == _sha256_file(img2)
        assert result["image_assets"][2]["sha256"] == _sha256_file(img3)

    def test_dedup_same_image(self):
        img = _make_test_png(200, 100, "red")
        path = _make_test_docx(
            paragraphs_before=[],
            images=[img, img],  # same image twice
            paragraphs_after=["End"],
        )
        result = extract_docx_images(path)
        assert len(result["image_assets"]) == 1
        assert result["image_bundle_meta"]["total"] == 2
        assert result["image_bundle_meta"]["deduped"] == 1

    def test_role_assignment_with_context(self):
        img = _make_test_png(600, 400, "white")
        path = _make_test_docx(
            paragraphs_before=["实验目的及要求", "1. 验证欧姆定律"],
            images=[img],
            paragraphs_after=["请完成实验并记录数据"],
        )
        result = extract_docx_images(path)
        assert result["image_assets"][0]["role_guess"] == "assignment"

    def test_large_image_is_assignment(self):
        img = _make_test_png(800, 600)
        path = _make_test_docx(images=[img])
        result = extract_docx_images(path)
        assert result["image_assets"][0]["role_guess"] == "assignment"

    def test_small_image_is_signature(self):
        img = _make_test_png(150, 40)
        path = _make_test_docx(images=[img])
        result = extract_docx_images(path)
        assert result["image_assets"][0]["role_guess"] == "signature"

    def test_bytes_b64_valid_base64(self):
        img = _make_test_png(100, 100)
        path = _make_test_docx(images=[img])
        result = extract_docx_images(path)
        b64 = result["image_assets"][0]["bytes_b64"]
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0
        assert decoded == Path(img).read_bytes()

    def test_page_hint(self):
        img = _make_test_png(100, 100)
        path = _make_test_docx(images=[img])
        result = extract_docx_images(path)
        assert result["image_assets"][0]["page_hint"] >= 1

    def test_ocr_vision_fields_present(self):
        img = _make_test_png(100, 100)
        path = _make_test_docx(images=[img])
        result = extract_docx_images(path)
        assert result["image_assets"][0]["ocr_text"] == ""
        assert result["image_assets"][0]["vision_summary"] == ""


# ── parse_report integration tests ─────────────────────────────────────


class TestParseReportIntegration:
    def test_extract_docx_has_image_assets(self):
        img = _make_test_png(300, 200)
        path = _make_test_docx(
            paragraphs_before=["题目要求"],
            images=[img],
        )
        full_text, metadata = extract_docx(path)
        assert "image_assets" in metadata
        assert len(metadata["image_assets"]) == 1
        assert "image_bundle_meta" in metadata

    def test_extract_docx_no_images(self):
        path = _make_test_docx(paragraphs_before=["纯文本报告"], images=[])
        full_text, metadata = extract_docx(path)
        assert metadata.get("image_assets") == []
        assert metadata.get("image_bundle_meta", {}).get("total") == 0

    def test_build_question_has_image_fields(self):
        img = _make_test_png(300, 200)
        path = _make_test_docx(
            paragraphs_before=["实验报告正文"],
            images=[img],
        )
        question, metadata, full_text, warnings = build_question_from_document(
            path, "test.docx"
        )
        assert "image_assets" in question
        assert len(question["image_assets"]) == 1
        assert "image_bundle_meta" in question

    def test_build_question_no_images(self):
        path = _make_test_docx(paragraphs_before=["纯文本"])
        question, metadata, full_text, warnings = build_question_from_document(
            path, "test.docx"
        )
        assert question.get("image_assets") == []
        assert question["image_bundle_meta"]["total"] == 0

    def test_warnings_with_images(self):
        img = _make_test_png(500, 400)
        path = _make_test_docx(
            paragraphs_before=["题目"],
            images=[img],
        )
        question, metadata, full_text, warnings = build_question_from_document(
            path, "test.docx"
        )
        assert len(warnings) >= 1
        # Should mention images since text is short
        codes = [w.get("code") for w in warnings]
        assert "short_text_with_images" in codes or "short_text" in codes

    def test_multiple_assignment_images_warning(self):
        img = _make_test_png(600, 400)
        path = _make_test_docx(
            paragraphs_before=["题目"],
            images=[img, _make_test_png(600, 400, "blue"),
                    _make_test_png(600, 400, "green")],
        )
        question, metadata, full_text, warnings = build_question_from_document(
            path, "test.docx"
        )
        codes = [w.get("code") for w in warnings]
        assert "multiple_assignment_images" in codes

    def test_standard_docx_regression(self):
        """V1 standard docx with no images must still parse correctly."""
        path = _make_test_docx(
            paragraphs_before=[
                "实验目的：验证欧姆定律",
                "实验原理：R=U/I",
                "三、实验步骤",
                "1. 连接电路",
                "2. 测量数据",
                "四、实验结果",
                "数据如下...",
                "五、实验总结",
                "本次实验成功验证了欧姆定律",
            ]
        )
        question, metadata, full_text, warnings = build_question_from_document(
            path, "test.docx"
        )
        assert len(full_text) > 50
        assert question.get("image_assets") == []
        assert question["image_bundle_meta"]["total"] == 0
        # Standard sections should still be detected
        assert "实验目的" in full_text
        assert "实验步骤" in full_text


# ── multi-doc integration ──────────────────────────────────────────────


class TestMultiDocIntegration:
    def test_parse_single_file_has_image_assets(self):
        """parse_single_file should propagate image_assets to metadata."""
        img = _make_test_png(300, 200)
        docx_path = _make_test_docx(
            paragraphs_before=["实验要求"],
            images=[img],
        )
        from agent.parse_documents import parse_single_file

        file_bytes = docx_path.read_bytes()
        bundle = parse_single_file(file_bytes, "test.docx", role="fill_target")
        assert "image_assets" in bundle["metadata"]
        assert len(bundle["metadata"]["image_assets"]) == 1

    def test_parse_documents_list_collects_images(self):
        """parse_documents_list should aggregate images from all docs."""
        img = _make_test_png(300, 200)
        docx_path = _make_test_docx(
            paragraphs_before=["实验步骤", "实验内容较多"],
            images=[img],
        )
        from agent.parse_documents import parse_documents_list

        docs = [{
            "file_data": base64.b64encode(docx_path.read_bytes()).decode(),
            "file_name": "report.docx",
            "role": "fill_target",
        }]
        result = parse_documents_list(docs)
        # The fill_target's bundle should be in _bundles
        bundles = result.get("_bundles") or []
        assert len(bundles) >= 1
        meta = bundles[0].get("metadata") or {}
        assert len(meta.get("image_assets") or []) == 1
