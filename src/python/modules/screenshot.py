"""Terminal and IDE style screenshots."""

import base64
import re
from pathlib import Path

from config import IDE_RENDER_OK, LANG_FILENAMES, PIL_OK, TEMP_DIR
from log_util import loge, logi

if IDE_RENDER_OK:
    from ide_render import save_ide_screenshot_pages

if PIL_OK:
    from PIL import Image, ImageDraw, ImageFont


def paths_to_b64(paths):
    out = []
    for p in paths:
        out.append(base64.b64encode(Path(p).read_bytes()).decode())
    return out


def render_ide_screenshot_file(
    code,
    output,
    language,
    filename="",
    chrome_style="windows",
    terminal_profile="",
    terminal_cwd="",
    terminal_custom="",
    full_layout=True,
):
    """保存 IDE 风格截图到临时目录，返回路径列表。"""
    out_path = str(TEMP_DIR / "ide_screenshot.png")
    if IDE_RENDER_OK:
        fname = filename or LANG_FILENAMES.get((language or "").lower(), "main.txt")
        paths = save_ide_screenshot_pages(
            code or "// 运行代码",
            output,
            language,
            out_path,
            filename=fname,
            chrome_style=chrome_style,
            terminal_profile=terminal_profile,
            terminal_cwd=terminal_cwd,
            terminal_custom=terminal_custom,
            full_layout=full_layout,
        )
        logi(
            "screenshot",
            f"IDE截图 {len(paths)} 页: {paths[0]}"
            + (f" ...共{len(paths)}张" if len(paths) > 1 else ""),
        )
        return paths
    return [render_terminal_image(output, f"{language.upper()} 运行结果")]


def render_terminal_image(text, title="Output"):
    if not PIL_OK:
        raise Exception("Pillow未安装，请运行: pip install Pillow")

    BG = (12, 12, 12)
    FG = (204, 204, 204)
    GREEN = (80, 200, 120)
    TITLE_BG = (30, 30, 30)
    TITLE_FG = (180, 180, 180)
    DOT_R = (255, 95, 87)
    DOT_Y = (255, 189, 46)
    DOT_G = (40, 200, 64)

    FONT_SIZE = 14
    LINE_H = 22
    PAD_X = 16
    PAD_Y = 12
    TITLE_H = 36

    lines = text.split("\n")
    width = max(600, max((len(l) for l in lines), default=40) * 8 + PAD_X * 2)
    height = TITLE_H + PAD_Y * 2 + len(lines) * LINE_H + 20

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, width, TITLE_H], fill=TITLE_BG)
    for i, (color, x) in enumerate([(DOT_R, 14), (DOT_Y, 34), (DOT_G, 54)]):
        draw.ellipse([x - 6, TITLE_H // 2 - 6, x + 6, TITLE_H // 2 + 6], fill=color)
    draw.text((width // 2, TITLE_H // 2), title, fill=TITLE_FG, anchor="mm")

    draw.line([0, TITLE_H, width, TITLE_H], fill=(50, 50, 50), width=1)

    font = None
    for font_path in [
        "C:/Windows/Fonts/msyhmono.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_path, FONT_SIZE)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    y = TITLE_H + PAD_Y
    draw.text((PAD_X, y), f"> {title}", fill=GREEN, font=font)
    y += LINE_H

    for line in lines:
        color = (255, 100, 100) if line.startswith(("[ERR]", "❌")) or "Error" in line else FG
        draw.text((PAD_X, y), line, fill=color, font=font)
        y += LINE_H

    out_path = str(TEMP_DIR / "terminal_screenshot.png")
    img.save(out_path)
    logi("screenshot", f"终端截图已生成: {out_path} ({width}x{height})")
    return out_path
