"""Generate OCR test fixtures (run once if PNGs missing)."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent

_PAGE_TEXTS = (
    "第1页：实验目的。验证欧姆定律。",
    "第2页：实验原理。R 等于 U 除以 I。",
    "第3页：实验步骤。连接电路并测量。",
    "第4页：实验数据。记录电压电流值。",
    "第5页：实验总结。完成本次实验。",
)

_I4_PAGE_TEXTS = (
    "图1：实验目的。掌握欧姆定律验证方法。",
    "图2：实验器材。电源、电阻箱、电压表。",
    "图3：实验步骤。按电路图连接并测量。",
    "图4：数据记录。填写下表并计算误差。",
)


def _load_font(size: int = 28):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def make_text_png(path: Path, text: str, size: tuple[int, int] = (800, 200)) -> None:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), text, fill="black", font=_load_font())
    img.save(path)


def _page_png_bytes(text: str, size: tuple[int, int] = (595, 842)) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 120), text, fill="black", font=_load_font(24))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_scanned_pdf(path: Path, page_texts: tuple[str, ...] = _PAGE_TEXTS) -> None:
    """Image-only PDF (no text layer) for IM3 acceptance."""
    import fitz

    doc = fitz.open()
    try:
        for text in page_texts:
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=_page_png_bytes(text))
        doc.save(str(path))
    finally:
        doc.close()


def make_i4_assignment_pngs(out_dir: Path | None = None) -> list[Path]:
    """Four assignment page PNGs for IM4 / I4 acceptance."""
    target = out_dir or OUT
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, text in enumerate(_I4_PAGE_TEXTS, start=1):
        path = target / f"assignment_page{i}.png"
        make_text_png(path, text, size=(720, 280))
        paths.append(path)
    return paths


def make_vision_blank_png(path: Path) -> None:
    """Mostly blank page — OCR returns empty; Vision fallback test (IM5 / I5)."""
    img = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), "（低对比度）", fill="#f0f0f0", font=_load_font())
    img.save(path)


def make_i5_vision_pages(out_dir: Path | None = None, count: int = 6) -> list[Path]:
    """Six small pages for vision limit test (IM5 / I6)."""
    target = out_dir or OUT
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, count + 1):
        path = target / f"vision_page{i}.png"
        make_text_png(path, f"Vision页{i}：实验要求段落 {i}。", size=(640, 240))
        paths.append(path)
    return paths


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_text_png(OUT / "ocr_simple_zh.png", "实验目的：验证欧姆定律。要求：测量电阻电压。")
    make_text_png(OUT / "ocr_simple_en.png", "Lab purpose: verify Ohm law. Measure R and V.")
    make_vision_blank_png(OUT / "vision_blank_page.png")
    make_scanned_pdf(OUT / "scanned_5page.pdf")
    make_i4_assignment_pngs(OUT)
    make_i5_vision_pages(OUT)
    print("wrote", sorted(OUT.glob("*")))
