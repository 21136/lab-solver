"""VS Code 风格 UI 图标（超采样抗锯齿，不依赖本机 codicon 字体）"""
from __future__ import annotations

from functools import lru_cache

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore

# VS Code Dark+ 侧栏 / 活动栏近似色
FG_ACTIVE = (255, 255, 255, 255)
FG_MUTED = (150, 150, 150, 230)
FOLDER = (220, 183, 105, 255)
PY_BLUE = (48, 113, 170, 255)
PY_YELLOW = (255, 212, 0, 255)
MD_BLUE = (66, 165, 245, 255)
JSON_ORANGE = (236, 151, 76, 255)
DOC_GRAY = (180, 180, 180, 255)


def _ss(size: int, supersample: int = 4) -> int:
    return max(size, 8) * supersample


@lru_cache(maxsize=128)
def get_ui_icon(name: str, size: int = 24) -> 'Image.Image':
    """返回 RGBA 图标，size 为逻辑像素。"""
    if not Image:
        raise RuntimeError('Pillow required')
    S = _ss(size)
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fn = _DRAWERS.get(name, _draw_file_generic)
    fn(draw, S, size)
    out = img.resize((size, size), Image.Resampling.LANCZOS)
    return out


def paste_icon(base: 'Image.Image', icon: 'Image.Image', cx: int, cy: int):
    x = cx - icon.width // 2
    y = cy - icon.height // 2
    base.paste(icon, (x, y), icon)


def _draw_files(draw, S: int, logical: int):
    c = FG_ACTIVE
    m = S // 8
    # 后层文档
    draw.rounded_rectangle([m + S // 10, m + S // 6, S * 45 // 100, S * 72 // 100], radius=S // 20, outline=c, width=max(1, S // 32))
    # 前层
    draw.rounded_rectangle([m, m, S * 78 // 100, S * 82 // 100], radius=S // 20, outline=c, width=max(1, S // 32))
    draw.polygon([
        (S * 62 // 100, m), (S * 78 // 100, m), (S * 78 // 100, S * 22 // 100),
        (S * 62 // 100, S * 22 // 100),
    ], fill=c)


def _draw_search(draw, S: int, logical: int):
    c = FG_MUTED
    lw = max(1, S // 28)
    r = S * 22 // 100
    ox, oy = S * 34 // 100, S * 32 // 100
    draw.ellipse([ox - r, oy - r, ox + r, oy + r], outline=c, width=lw)
    draw.line([ox + r - 2, oy + r - 2, S * 78 // 100, S * 78 // 100], fill=c, width=lw)


def _draw_scm(draw, S: int, logical: int):
    c = FG_MUTED
    lw = max(1, S // 32)
    cx = S // 2
    draw.line([cx, S * 18 // 100, cx, S * 82 // 100], fill=c, width=lw)
    draw.line([cx, S * 28 // 100, S * 28 // 100, S * 48 // 100], fill=c, width=lw)
    draw.line([cx, S * 52 // 100, S * 72 // 100, S * 78 // 100], fill=c, width=lw)
    for px, py in [(S * 28 // 100, S * 48 // 100), (cx, S * 28 // 100), (S * 72 // 100, S * 78 // 100)]:
        draw.ellipse([px - S // 16, py - S // 16, px + S // 16, py + S // 16], fill=c)


def _draw_run(draw, S: int, logical: int):
    c = FG_MUTED
    lw = max(1, S // 32)
    draw.rounded_rectangle([S * 18 // 100, S * 20 // 100, S * 30 // 100, S * 80 // 100], radius=S // 40, outline=c, width=lw)
    draw.polygon([
        (S * 38 // 100, S * 28 // 100), (S * 38 // 100, S * 72 // 100), (S * 78 // 100, S * 50 // 100),
    ], fill=c)


def _draw_extensions(draw, S: int, logical: int):
    c = FG_MUTED
    g = S * 22 // 100
    gap = S * 10 // 100
    x0, y0 = S * 22 // 100, S * 22 // 100
    for row in range(2):
        for col in range(2):
            x1 = x0 + col * (g + gap)
            y1 = y0 + row * (g + gap)
            draw.rounded_rectangle([x1, y1, x1 + g, y1 + g], radius=S // 50, outline=c, width=max(1, S // 36))


def _draw_settings(draw, S: int, logical: int):
    c = FG_MUTED
    cx, cy = S // 2, S // 2
    r1, r2 = S * 22 // 100, S * 34 // 100
    draw.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], outline=c, width=max(1, S // 32))
    import math
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        x1 = cx + int(r1 * 1.15 * math.cos(rad))
        y1 = cy + int(r1 * 1.15 * math.sin(rad))
        x2 = cx + int(r2 * math.cos(rad))
        y2 = cy + int(r2 * math.sin(rad))
        draw.line([x1, y1, x2, y2], fill=c, width=max(1, S // 36))


def _draw_account(draw, S: int, logical: int):
    c = FG_MUTED
    cx = S // 2
    draw.ellipse([cx - S // 6, S * 22 // 100, cx + S // 6, S * 42 // 100], fill=c)
    draw.ellipse([cx - S * 28 // 100, S * 48 // 100, cx + S * 28 // 100, S * 82 // 100], fill=c)


def _draw_chevron_down(draw, S: int, logical: int):
    c = FG_MUTED
    cx, cy = S // 2, S // 2
    w = S // 5
    draw.polygon([(cx - w, cy - w // 2), (cx + w, cy - w // 2), (cx, cy + w // 2)], fill=c)


def _draw_chevron_right(draw, S: int, logical: int):
    c = FG_MUTED
    cx, cy = S // 2, S // 2
    w = S // 5
    draw.polygon([(cx - w // 2, cy - w), (cx - w // 2, cy + w), (cx + w // 2, cy)], fill=c)


def _draw_folder_open(draw, S: int, logical: int):
    m = S // 10
    body = [m, S * 38 // 100, S - m, S - m]
    tab = [m, S * 30 // 100, S * 48 // 100, S * 42 // 100]
    draw.rectangle(body, fill=FOLDER)
    draw.rectangle(tab, fill=FOLDER)
    draw.line([m + 2, S - m - 2, S - m - 2, S - m - 2], fill=(160, 130, 70, 255), width=max(1, S // 40))


def _draw_folder_closed(draw, S: int, logical: int):
    m = S // 8
    draw.rectangle([m, S * 36 // 100, S - m, S - m], fill=FOLDER)
    draw.rectangle([m, S * 28 // 100, S * 46 // 100, S * 40 // 100], fill=FOLDER)


def _draw_python(draw, S: int, logical: int):
    m = S // 10
    draw.rectangle([m, m, S - m, S - m], fill=PY_BLUE)
    draw.rectangle([m, S // 2, S - m, S - m], fill=PY_YELLOW)
    # 简化蛇形高光
    draw.ellipse([S * 55 // 100, S * 22 // 100, S * 72 // 100, S * 38 // 100], fill=(255, 255, 255, 80))
    draw.ellipse([S * 28 // 100, S * 58 // 100, S * 45 // 100, S * 74 // 100], fill=(255, 255, 255, 60))


def _draw_markdown(draw, S: int, logical: int):
    m = S // 10
    draw.rectangle([m, m, S - m, S - m], fill=MD_BLUE)
    # M
    lw = max(2, S // 12)
    draw.line([m + S // 6, S - m - 2, m + S // 6, m + S // 5], fill=(255, 255, 255, 255), width=lw)
    draw.line([S - m - S // 6, S - m - 2, S - m - S // 6, m + S // 5], fill=(255, 255, 255, 255), width=lw)
    draw.line([m + S // 6, m + S // 5, S // 2, S * 45 // 100], fill=(255, 255, 255, 255), width=lw)
    draw.line([S // 2, S * 45 // 100, S - m - S // 6, m + S // 5], fill=(255, 255, 255, 255), width=lw)


def _draw_json(draw, S: int, logical: int):
    m = S // 10
    draw.rectangle([m, m, S - m, S - m], fill=JSON_ORANGE)
    f = ImageFont_load(S)
    if f:
        draw.text((S * 28 // 100, S * 22 // 100), '{}', fill=(255, 255, 255, 255), font=f)


def _draw_file_generic(draw, S: int, logical: int):
    c = DOC_GRAY
    m = S // 8
    draw.rounded_rectangle([m, m + S // 8, S - m, S - m], radius=S // 16, outline=c, width=max(1, S // 28))
    draw.line([m + S // 6, S * 42 // 100, S - m - S // 5, S * 42 // 100], fill=c, width=max(1, S // 32))
    draw.line([m + S // 6, S * 54 // 100, S - m - S // 4, S * 54 // 100], fill=c, width=max(1, S // 32))


def ImageFont_load(S: int):
    try:
        from PIL import ImageFont
        for p in ('C:/Windows/Fonts/consola.ttf', 'C:/Windows/Fonts/segoeui.ttf'):
            try:
                return ImageFont.truetype(p, S // 4)
            except Exception:
                continue
    except Exception:
        pass
    return None


def file_icon_name(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return {
        'py': 'python',
        'md': 'markdown',
        'json': 'json',
    }.get(ext, 'file')


_DRAWERS = {
    'files': _draw_files,
    'search': _draw_search,
    'scm': _draw_scm,
    'run': _draw_run,
    'extensions': _draw_extensions,
    'settings': _draw_settings,
    'account': _draw_account,
    'chevron-down': _draw_chevron_down,
    'chevron-right': _draw_chevron_right,
    'folder-open': _draw_folder_open,
    'folder-closed': _draw_folder_closed,
    'python': _draw_python,
    'markdown': _draw_markdown,
    'json': _draw_json,
    'file': _draw_file_generic,
}
