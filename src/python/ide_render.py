"""仿 VS Code 界面：上方代码编辑区 + 底部终端输出（用于实验报告截图）"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    from ide_ui_icons import file_icon_name, get_ui_icon, paste_icon
    UI_ICONS_OK = True
except ImportError:
    UI_ICONS_OK = False

try:
    from pygments import lex
    from pygments import lexers
    from pygments.token import Token
    PYGMENTS_OK = True
except ImportError:
    PYGMENTS_OK = False


# VS Code Dark+ 近似配色
C = {
    'window_bg': (30, 30, 30),
    'title_bg': (37, 37, 38),
    'title_fg': (204, 204, 204),
    'tab_bar': (37, 37, 38),
    'tab_active': (30, 30, 30),
    'tab_inactive': (45, 45, 45),
    'tab_fg': (204, 204, 204),
    'editor_bg': (30, 30, 30),
    'gutter_bg': (30, 30, 30),
    'line_num': (133, 133, 133),
    'border': (62, 62, 62),
    'panel_bg': (30, 30, 30),
    'panel_tab_bg': (37, 37, 38),
    'panel_tab_active': (30, 30, 30),
    'panel_tab_fg': (204, 204, 204),
    'output_fg': (204, 204, 204),
    'output_err': (244, 71, 71),
    'output_ok': (78, 201, 176),
    'prompt': (78, 201, 176),
    'win_caption': (37, 37, 38),
    'win_caption_btn': (45, 45, 45),
    'win_close': (232, 17, 35),
    'win_icon': (0, 122, 204),
    'dot_r': (255, 95, 87),
    'dot_y': (255, 189, 46),
    'dot_g': (40, 200, 64),
    'activity_bg': (51, 51, 51),
    'activity_border': (69, 69, 69),
    'activity_active_border': (255, 255, 255),
    'sidebar_bg': (37, 37, 38),
    'sidebar_header': (128, 128, 128),
    'sidebar_fg': (204, 204, 204),
    'sidebar_muted': (150, 150, 150),
    'status_bg': (0, 122, 204),
    'status_fg': (255, 255, 255),
    'active_file': (38, 79, 120),
    'folder_icon': (220, 180, 90),
    'icon_py_blue': (55, 118, 180),
    'icon_py_yellow': (255, 212, 59),
    'icon_md': (81, 174, 227),
    'icon_json': (198, 120, 66),
    'icon_java': (215, 72, 62),
    'icon_doc': (156, 156, 156),
}

LANG_FILENAMES = {
    'python': 'main.py',
    'java': 'Main.java',
    'c': 'main.c',
    'cpp': 'main.cpp',
    'javascript': 'main.js',
    'js': 'main.js',
}

FONT_CJK = [
    'C:/Windows/Fonts/msyhmono.ttf',
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simsun.ttc',
]
FONT_LATIN = [
    'C:/Windows/Fonts/CascadiaMono.ttf',
    'C:/Windows/Fonts/consola.ttf',
    'C:/Windows/Fonts/lucon.ttf',
]

# 2x 像素密度导出，插入 Word 缩小显示时仍清晰（接近 Retina 截图）
RENDER_SCALE = 2
BASE_WIDTH = 1280
FULL_LAYOUT = True  # 完整 VS Code 窗口（侧栏+状态栏）

_CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\uff00-\uffef]')


def _is_cjk(ch: str) -> bool:
    return bool(ch) and bool(_CJK_RE.match(ch))


def _load_one(paths, size):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def _font_pair(size: int):
    """中文用 CJK 字体，英文/符号用 Consolas，避免注释和输出乱码"""
    font_cjk = _load_one(FONT_CJK, size)
    font_latin = _load_one(FONT_LATIN, size)
    fallback = font_cjk or font_latin or ImageFont.load_default()
    return font_latin or fallback, font_cjk or fallback


def _char_width(draw, ch, font_latin, font_cjk):
    f = font_cjk if _is_cjk(ch) else font_latin
    try:
        return draw.textlength(ch, font=f)
    except Exception:
        return 8 if ord(ch) < 128 else 14


def _text_width(draw, text, font_latin, font_cjk):
    return sum(_char_width(draw, ch, font_latin, font_cjk) for ch in text)


def _draw_text(draw, x, y, text, color, font_latin, font_cjk):
    cx = x
    for ch in text:
        f = font_cjk if _is_cjk(ch) else font_latin
        draw.text((cx, y), ch, fill=color, font=f)
        cx += _char_width(draw, ch, font_latin, font_cjk)
    return cx


def _lexer_for(language: str):
    lang = (language or 'python').lower()
    mapping = {
        'python': 'python',
        'java': 'java',
        'c': 'c',
        'cpp': 'cpp',
        'javascript': 'javascript',
        'js': 'javascript',
    }
    name = mapping.get(lang, lang)
    try:
        return lexers.get_lexer_by_name(name)
    except Exception:
        return lexers.get_lexer_by_name('text')


def _token_color(ttype):
    if ttype in Token.Comment:
        return (106, 153, 85)
    if ttype in Token.String:
        return (206, 145, 120)
    if ttype in Token.Keyword:
        return (86, 156, 214)
    if ttype in Token.Name.Function:
        return (220, 220, 170)
    if ttype in Token.Number:
        return (181, 206, 168)
    if ttype in Token.Operator:
        return (212, 212, 212)
    return (212, 212, 212)


def _highlight_lines(code: str, language: str) -> list[list[tuple[str, tuple]]]:
    if not code.strip():
        return [[('', C['output_fg'])]]
    if PYGMENTS_OK:
        try:
            lexer = _lexer_for(language)
            lines: list[list[tuple[str, tuple]]] = [[]]
            for ttype, value in lex(code, lexer):
                parts = value.split('\n')
                for i, part in enumerate(parts):
                    if i > 0:
                        lines.append([])
                    if part:
                        lines[-1].append((part, _token_color(ttype)))
            if lines and any(lines):
                return lines
        except Exception:
            pass
    # 简易高亮兜底
    lines = []
    kw = re.compile(
        r'\b(void|int|char|float|double|if|else|for|while|return|include|'
        r'public|class|static|void|new|def|import|print|printf|main)\b'
    )
    for line in code.split('\n'):
        segs = []
        pos = 0
        for m in kw.finditer(line):
            if m.start() > pos:
                segs.append((line[pos:m.start()], C['output_fg']))
            segs.append((m.group(), C['output_ok']))
            pos = m.end()
        if pos < len(line):
            segs.append((line[pos:], C['output_fg']))
        if not segs:
            segs = [(line, C['output_fg'])]
        lines.append(segs)
    return lines


def _draw_segments(draw, x, y, segments, font_latin, font_cjk):
    cx = x
    for text, color in segments:
        if not text:
            continue
        cx = _draw_text(draw, cx, y, text, color, font_latin, font_cjk)


def _wrap_lines(lines: list[str], max_chars: int = 96) -> list[str]:
    """过长行折行，避免横向裁切"""
    out = []
    for line in lines:
        if len(line) <= max_chars:
            out.append(line)
            continue
        while len(line) > max_chars:
            out.append(line[:max_chars])
            line = line[max_chars:]
        if line:
            out.append(line)
    return out


def render_ide_screenshot(
    code: str,
    output: str,
    language: str = 'python',
    filename: str | None = None,
    window_title: str | None = None,
    width: int = 920,
    max_code_lines: int | None = None,
    full_output: bool = True,
) -> 'Image.Image':
    """生成 VS Code 风格：代码编辑区 + 底部终端输出"""
    if not PIL_OK:
        raise RuntimeError('Pillow 未安装')

    code = (code or '').replace('\r\n', '\n').replace('\r', '\n')
    output = (output or '(无输出)').replace('\r\n', '\n').replace('\r', '\n')

    fname = filename or LANG_FILENAMES.get((language or '').lower(), 'main.txt')
    title = window_title or f'Visual Studio Code — {fname}'

    pages = render_ide_screenshot_pages(
        code, output, language, filename=filename, window_title=window_title,
        width=width, max_code_lines=max_code_lines,
    )
    return pages[0]


# 分页：固定逻辑字号，物理像素按 RENDER_SCALE 放大
FONT_SIZE = 14
LINE_H = 22
CODE_PREVIEW_MAX = 10
FIRST_PAGE_OUTPUT_LINES = 20
CONT_PAGE_OUTPUT_LINES = 32


def _chunk_lines(lines: list[str], first: int, rest: int) -> list[list[str]]:
    if not lines:
        return [[]]
    chunks = [lines[:first]]
    i = first
    while i < len(lines):
        chunks.append(lines[i:i + rest])
        i += rest
    if not chunks[0] and len(chunks) == 1:
        return [[]]
    return [c for c in chunks if c is not None]


def _normalize_chrome(style: str) -> str:
    return 'mac' if (style or '').lower() in ('mac', 'macos', 'darwin') else 'windows'


def _window_title(fname: str, chrome_style: str, page_index: int = 1, page_total: int = 1) -> str:
    chrome = _normalize_chrome(chrome_style)
    if page_total > 1 and page_index > 1:
        return f'终端输出 ({page_index}/{page_total}) - {fname}'
    if chrome == 'mac':
        return f'Visual Studio Code — {fname}'
    return f'{fname} - Visual Studio Code'


def render_ide_screenshot_pages(
    code: str,
    output: str,
    language: str = 'python',
    filename: str | None = None,
    window_title: str | None = None,
    width: int = BASE_WIDTH,
    max_code_lines: int | None = None,
    chrome_style: str = 'windows',
    terminal_profile: str = '',
    terminal_cwd: str = '',
    terminal_custom: str = '',
    full_layout: bool | None = None,
) -> list:
    """输出过长时拆成多页，每页保持相同字号"""
    if not PIL_OK:
        raise RuntimeError('Pillow 未安装')

    code = (code or '').replace('\r\n', '\n').replace('\r', '\n')
    output = (output or '(无输出)').replace('\r\n', '\n').replace('\r', '\n')
    fname = filename or LANG_FILENAMES.get((language or '').lower(), 'main.txt')
    chrome = _normalize_chrome(chrome_style)
    use_full = FULL_LAYOUT if full_layout is None else bool(full_layout)

    out_lines = output.split('\n')
    if out_lines and out_lines[-1] == '':
        out_lines = out_lines[:-1]
    out_lines = _wrap_lines(out_lines)

    chunks = _chunk_lines(out_lines, FIRST_PAGE_OUTPUT_LINES, CONT_PAGE_OUTPUT_LINES)
    if len(chunks) == 1 and len(out_lines) <= FIRST_PAGE_OUTPUT_LINES:
        title = window_title or _window_title(fname, chrome, 1, 1)
        return [_render_ide_page(
            code, language, fname, title, chunks[0], width=width,
            show_code=True, page_index=1, page_total=1,
            max_code_lines=max_code_lines or CODE_PREVIEW_MAX,
            show_run_prompt=True, chrome_style=chrome,
            terminal_profile=terminal_profile, terminal_cwd=terminal_cwd,
            terminal_custom=terminal_custom, full_layout=use_full,
        )]

    total = len(chunks)
    images = []
    for i, chunk in enumerate(chunks):
        title = window_title if (i == 0 and window_title) else _window_title(fname, chrome, i + 1, total)
        img = _render_ide_page(
            code, language, fname, title, chunk, width=width,
            show_code=(i == 0),
            page_index=i + 1, page_total=total,
            max_code_lines=max_code_lines or CODE_PREVIEW_MAX,
            show_run_prompt=(i == 0),
            chrome_style=chrome,
            terminal_profile=terminal_profile, terminal_cwd=terminal_cwd,
            terminal_custom=terminal_custom, full_layout=use_full,
        )
        images.append(img)
    return images


def _S(n: float, scale: int = RENDER_SCALE) -> int:
    return max(1, int(round(n * scale)))


def _save_png(img: 'Image.Image', path: str):
    """高质量 PNG，避免过度压缩导致发糊"""
    img.save(str(path), format='PNG', optimize=False, compress_level=2)


def _draw_windows_titlebar(draw, W, title_h, title, font_ui_latin, font_ui_cjk, scale):
    """Windows 11 风格标题栏：左侧图标+标题，右侧最小化/最大化/关闭"""
    draw.rectangle([0, 0, W, title_h], fill=C['win_caption'])

    icon = _S(16, scale)
    ix = _S(12, scale)
    iy = (title_h - icon) // 2
    draw.rectangle([ix, iy, ix + icon, iy + icon], fill=C['win_icon'])
    draw.rectangle([ix + _S(3, scale), iy + _S(3, scale), ix + icon - _S(3, scale), iy + icon - _S(3, scale)],
                   fill=(30, 30, 30))

    tx = ix + icon + _S(10, scale)
    _draw_text(draw, tx, title_h // 2 - _S(6, scale), title, C['title_fg'], font_ui_latin, font_ui_cjk)

    btn_w = _S(46, scale)
    x_min = W - btn_w * 3
    cy = title_h // 2
    lw = max(1, scale)

    # 最小化
    draw.rectangle([x_min, 0, x_min + btn_w, title_h], fill=C['win_caption'])
    draw.line([x_min + btn_w // 4, cy, x_min + btn_w * 3 // 4, cy], fill=C['title_fg'], width=lw)

    # 最大化
    x_max = x_min + btn_w
    draw.rectangle([x_max, 0, x_max + btn_w, title_h], fill=C['win_caption'])
    s = _S(5, scale)
    draw.rectangle([x_max + btn_w // 2 - s, cy - s, x_max + btn_w // 2 + s, cy + s],
                   outline=C['title_fg'], width=lw)

    # 关闭
    x_close = W - btn_w
    draw.rectangle([x_close, 0, W, title_h], fill=C['win_close'])
    d = _S(6, scale)
    draw.line([W - btn_w // 2 - d, cy - d, W - btn_w // 2 + d, cy + d], fill=(255, 255, 255), width=lw)
    draw.line([W - btn_w // 2 - d, cy + d, W - btn_w // 2 + d, cy - d], fill=(255, 255, 255), width=lw)


def _draw_mac_titlebar(draw, W, title_h, title, font_ui_latin, font_ui_cjk, scale):
    """macOS 风格标题栏：红黄绿按钮 + 居中标题"""
    draw.rectangle([0, 0, W, title_h], fill=C['title_bg'])
    r = _S(5, scale)
    for col, x in [(C['dot_r'], _S(14, scale)), (C['dot_y'], _S(34, scale)), (C['dot_g'], _S(54, scale))]:
        cy_dot = title_h // 2
        draw.ellipse([x - r, cy_dot - r, x + r, cy_dot + r], fill=col)
    tw = _text_width(draw, title, font_ui_latin, font_ui_cjk)
    _draw_text(draw, (W - tw) // 2, title_h // 2 - _S(6, scale), title, C['title_fg'], font_ui_latin, font_ui_cjk)


def _run_command_for_file(fname: str, language: str) -> str:
    base = fname.rsplit('.', 1)[0] if '.' in fname else fname
    lang = (language or '').lower()
    if lang == 'java':
        return f'javac {fname} && java {base}' if base != 'Main' else f'java {base}'
    if lang == 'python':
        return f'python {fname}'
    if lang in ('c', 'cpp'):
        return f'{base}.exe' if lang == 'c' else f'./{base}'
    if lang in ('javascript', 'js'):
        return f'node {fname}'
    return fname


def _terminal_prompt_and_cmd(
    fname: str,
    language: str,
    chrome_style: str,
    terminal_profile: str = '',
    terminal_cwd: str = '',
    terminal_custom: str = '',
) -> tuple[str, str]:
    """根据用户配置的终端类型生成提示符与运行命令"""
    profile = (terminal_profile or '').strip().lower()
    chrome = _normalize_chrome(chrome_style)
    cwd = (terminal_cwd or '').strip()
    cmd = _run_command_for_file(fname, language)

    if profile == 'custom' and terminal_custom.strip():
        prompt = terminal_custom.strip()
        if not prompt.endswith(' '):
            prompt += ' '
        return prompt, cmd

    if profile == 'win_cmd':
        path = cwd or 'C:\\Users\\Student\\Desktop\\lab'
        return f'{path}> ', cmd

    if profile == 'win_gitbash':
        path = cwd.replace('\\', '/') if cwd else '/c/Users/Student/project'
        return f'{path} $ ', cmd

    if profile == 'mac_zsh' or (chrome == 'mac' and not profile):
        path = cwd or '~/Documents/project'
        return f'user@MacBook-Pro {path} % ', cmd

    if profile == 'mac_bash':
        return 'bash-3.2$ ', cmd

    if profile == 'mac_ps':
        path = cwd or '/Users/student/project'
        return f'PS {path}> ', cmd

    # 默认 win_powershell（Windows 窗口样式时）
    path = cwd or 'C:\\Users\\Student\\Desktop\\lab'
    return f'PS {path}> ', cmd


def _project_name_from_fname(fname: str, terminal_cwd: str) -> str:
    if terminal_cwd:
        import os
        base = os.path.basename(terminal_cwd.rstrip('\\/'))
        if base:
            return base
    return 'lab-project'


def _sidebar_entries(fname: str, language: str) -> list[tuple[str, str, int]]:
    """精简文件树，避免堆太多假文件。"""
    lang = (language or 'python').lower()
    items: list[tuple[str, str, int]] = [('__root__', 'folder_root', 0), (fname, 'file', 1)]
    if lang == 'python':
        for f in ('requirements.txt', 'README.md'):
            if f != fname:
                items.append((f, 'file', 1))
    elif lang == 'java' and fname != 'Main.java':
        items.append(('Main.java', 'file', 1))
    else:
        items.append(('README.md', 'file', 1))
    return items


def _paste_ui(img, name: str, cx: int, cy: int, scale: int, icon_px: int | None = None):
    if not UI_ICONS_OK:
        return
    px = icon_px or _S(22, scale)
    paste_icon(img, get_ui_icon(name, px), cx, cy)


def _draw_activity_bar(img, draw, x, y, h, scale):
    w = _S(48, scale)
    draw.rectangle([x, y, x + w, y + h], fill=C['activity_bg'])
    draw.line([x + w - 1, y, x + w - 1, y + h], fill=C['activity_border'], width=max(1, scale))
    cx = x + w // 2
    icon_px = _S(24, scale)
    kinds = ['files', 'search', 'scm', 'run', 'extensions']
    iy = y + _S(4, scale)
    for i, kind in enumerate(kinds):
        cy = iy + _S(16, scale)
        if i == 0:
            bar_top = cy - _S(16, scale)
            draw.rectangle(
                [x, bar_top, x + _S(2, scale), bar_top + _S(32, scale)],
                fill=C['activity_active_border'],
            )
        _paste_ui(img, kind, cx, cy, scale, icon_px)
        iy += _S(40, scale)
    _paste_ui(img, 'account', cx, y + h - _S(72, scale), scale, _S(22, scale))
    _paste_ui(img, 'settings', cx, y + h - _S(36, scale), scale, _S(22, scale))
    return w


def _draw_sidebar(img, draw, x, y, w, h, fname, project_name, scale, language: str = 'python'):
    font_sm = _font_pair(_S(12, scale))
    font_xs = _font_pair(_S(11, scale))
    font_cap = _font_pair(_S(11, scale))
    draw.rectangle([x, y, x + w, y + h], fill=C['sidebar_bg'])

    header_h = _S(30, scale)
    cap = '资源管理器'
    _draw_text(draw, x + _S(12, scale), y + _S(8, scale), cap, C['sidebar_muted'], font_cap[0], font_cap[1])
    # 标题行右侧操作（省略号）
    dots_x = x + w - _S(36, scale)
    for i, dx in enumerate((0, _S(6, scale), _S(12, scale))):
        draw.ellipse(
            [dots_x + dx, y + _S(14, scale), dots_x + dx + _S(3, scale), y + _S(17, scale)],
            fill=C['sidebar_muted'],
        )

    fy = y + header_h
    row_h = _S(22, scale)
    icon_sz = _S(16, scale)
    chev_sz = _S(10, scale)

    for label, kind, depth in _sidebar_entries(fname, language):
        if kind == 'folder_root':
            chev_x = x + _S(14, scale)
            _paste_ui(img, 'chevron-down', chev_x, fy + row_h // 2, scale, chev_sz)
            _paste_ui(img, 'folder-open', x + _S(32, scale), fy + row_h // 2, scale, icon_sz)
            display = project_name if project_name else 'workspace'
            _draw_text(draw, x + _S(48, scale), fy + _S(4, scale), display, C['sidebar_fg'], font_sm[0], font_sm[1])
        elif kind == 'file':
            base = label.rsplit('/', 1)[-1]
            active = base == fname.rsplit('/', 1)[-1]
            if active:
                draw.rectangle([x + _S(2, scale), fy, x + w - _S(2, scale), fy + row_h], fill=C['active_file'])
            ix = x + _S(28, scale) + depth * _S(12, scale)
            _paste_ui(img, file_icon_name(base), ix, fy + row_h // 2, scale, icon_sz)
            _draw_text(draw, ix + _S(20, scale), fy + _S(4, scale), base, C['sidebar_fg'], font_sm[0], font_sm[1])
        fy += row_h

    outline_y = min(fy + _S(12, scale), y + h - _S(56, scale))
    draw.line([x, outline_y, x + w, outline_y], fill=C['border'], width=max(1, scale))
    for i, title in enumerate(('大纲', '时间线')):
        oy = outline_y + _S(8, scale) + i * _S(22, scale)
        _paste_ui(img, 'chevron-right', x + _S(14, scale), oy + _S(8, scale), scale, chev_sz)
        _draw_text(draw, x + _S(28, scale), oy, title, C['sidebar_muted'], font_xs[0], font_xs[1])


def _draw_status_bar(draw, x, y, W, fname, language, scale):
    h = _S(22, scale)
    draw.rectangle([x, y, x + W, y + h], fill=C['status_bg'])
    font_sm = _font_pair(_S(10, scale))
    left = f'  ⎇ main  {fname}  '
    _draw_text(draw, x + _S(8, scale), y + _S(4, scale), left, C['status_fg'], font_sm[0], font_sm[1])
    right = f'UTF-8  LF  {language.upper()}  Spaces: 4  '
    tw = _text_width(draw, right, font_sm[0], font_sm[1])
    _draw_text(draw, x + W - tw - _S(8, scale), y + _S(4, scale), right, C['status_fg'], font_sm[0], font_sm[1])
    return h


def _draw_run_prompt(
    draw, pad_x, oy, fname, font_latin, font_cjk, scale, chrome_style,
    language='python', terminal_profile='', terminal_cwd='', terminal_custom='',
):
    prompt, cmd = _terminal_prompt_and_cmd(
        fname, language, chrome_style, terminal_profile, terminal_cwd, terminal_custom)
    _draw_text(draw, pad_x, oy, prompt, C['prompt'], font_latin, font_cjk)
    pw = _text_width(draw, prompt, font_latin, font_cjk)
    _draw_text(draw, pad_x + pw, oy, cmd, C['output_fg'], font_latin, font_cjk)


def _render_ide_page(
    code, language, fname, title, out_lines, width=BASE_WIDTH,
    show_code=True, page_index=1, page_total=1,
    max_code_lines=10, show_run_prompt=True,
    scale: int = RENDER_SCALE,
    chrome_style: str = 'windows',
    terminal_profile: str = '',
    terminal_cwd: str = '',
    terminal_custom: str = '',
    full_layout: bool = True,
):
    W = _S(width, scale)
    line_h = _S(LINE_H, scale)
    pad_x = _S(12, scale)
    gutter_w = _S(44, scale)
    font_latin, font_cjk = _font_pair(_S(FONT_SIZE, scale))
    font_ui_latin, font_ui_cjk = _font_pair(_S(12, scale))
    font_sm_latin, font_sm_cjk = _font_pair(_S(11, scale))

    title_h = _S(32, scale)
    tab_h = _S(28, scale)
    panel_tab_h = _S(26, scale)
    code_h = 0
    code_lines = []

    if show_code and code.strip():
        code_lines = _highlight_lines(code, language)
        total_code_lines = len(code.split('\n'))
        if len(code_lines) > max_code_lines:
            code_lines = code_lines[:max_code_lines]
            code_lines.append([(f'// ... 完整代码共 {total_code_lines} 行，见实验步骤', C['line_num'])])
        code_h = pad_x * 2 + len(code_lines) * line_h

    extra_terminal_lines = 0
    if page_total > 1:
        extra_terminal_lines += 1  # 分页提示行
    if show_run_prompt:
        extra_terminal_lines += 1

    out_h = pad_x * 2 + (len(out_lines) + extra_terminal_lines) * line_h
    status_h = _S(22, scale) if full_layout else 0
    body_inner_h = tab_h + code_h + (1 if code_h else 0) + panel_tab_h + out_h + _S(4, scale)
    height = title_h + body_inner_h + status_h + _S(4, scale)

    img = Image.new('RGB', (W, height), C['window_bg'])
    draw = ImageDraw.Draw(img)

    if _normalize_chrome(chrome_style) == 'mac':
        _draw_mac_titlebar(draw, W, title_h, title, font_ui_latin, font_ui_cjk, scale)
    else:
        _draw_windows_titlebar(draw, W, title_h, title, font_ui_latin, font_ui_cjk, scale)

    body_y = title_h
    body_h = height - title_h - status_h

    if full_layout:
        act_w = _draw_activity_bar(img, draw, 0, body_y, body_h, scale)
        side_w = _S(240, scale)
        _draw_sidebar(img, draw, act_w, body_y, side_w, body_h, fname,
                      _project_name_from_fname(fname, terminal_cwd), scale, language)
        mx = act_w + side_w
        mw = W - mx
    else:
        mx, mw = 0, W

    y = body_y
    draw.rectangle([mx, y, mx + mw, y + tab_h], fill=C['tab_bar'])
    tab_w = min(_S(220, scale), _S(40, scale) + int(_text_width(draw, fname, font_ui_latin, font_ui_cjk)))
    draw.rectangle([mx + _S(8, scale), y + _S(4, scale), mx + _S(8, scale) + tab_w, y + tab_h - _S(2, scale)], fill=C['tab_active'])
    _draw_text(draw, mx + _S(20, scale), y + tab_h // 2 - _S(6, scale), fname, C['tab_fg'], font_ui_latin, font_ui_cjk)
    _draw_text(draw, mx + _S(8, scale) + tab_w - _S(22, scale), y + tab_h // 2 - _S(6, scale), '×', C['line_num'], font_ui_latin, font_ui_cjk)
    y += tab_h

    if code_h:
        draw.rectangle([mx, y, mx + mw, y + code_h], fill=C['editor_bg'])
        cy = y + pad_x
        for i, segs in enumerate(code_lines, 1):
            _draw_text(draw, mx + pad_x, cy, str(i), C['line_num'], font_latin, font_cjk)
            _draw_segments(draw, mx + gutter_w + pad_x, cy, segs, font_latin, font_cjk)
            cy += line_h
        y += code_h
        draw.line([mx, y, mx + mw, y], fill=C['border'], width=max(1, scale))
        y += max(1, scale)

    draw.rectangle([mx, y, mx + mw, y + panel_tab_h], fill=C['panel_tab_bg'])
    for i, label in enumerate(['终端', '问题', '输出', '调试控制台']):
        tx = mx + _S(8, scale) + i * _S(72, scale)
        if i == 0:
            draw.rectangle([tx, y + _S(3, scale), tx + _S(56, scale), y + panel_tab_h - _S(2, scale)], fill=C['panel_tab_active'])
        if i < 3:
            _draw_text(draw, tx + _S(8, scale), y + panel_tab_h // 2 - _S(5, scale), label, C['panel_tab_fg'], font_sm_latin, font_sm_cjk)
    y += panel_tab_h

    draw.rectangle([mx, y, mx + mw, body_y + body_h - status_h], fill=C['panel_bg'])
    oy = y + pad_x

    if page_total > 1:
        banner = f'──── 终端输出 第 {page_index}/{page_total} 页 ────'
        _draw_text(draw, mx + pad_x, oy, banner, C['line_num'], font_latin, font_cjk)
        oy += line_h

    if show_run_prompt:
        _draw_run_prompt(
            draw, mx + pad_x, oy, fname, font_latin, font_cjk, scale, chrome_style,
            language=language, terminal_profile=terminal_profile,
            terminal_cwd=terminal_cwd, terminal_custom=terminal_custom,
        )
        oy += line_h

    for line in out_lines:
        is_err = bool(re.search(r'error|错误|exception|失败', line, re.I))
        color = C['output_err'] if is_err else C['output_fg']
        _draw_text(draw, mx + pad_x, oy, line, color, font_latin, font_cjk)
        oy += line_h

    if full_layout:
        _draw_status_bar(draw, 0, height - status_h, W, fname, language, scale)

    return img


def save_ide_screenshot(code, output, language, out_path, **kwargs) -> str:
    paths = save_ide_screenshot_pages(code, output, language, out_path, **kwargs)
    return paths[0]


def save_ide_screenshot_pages(code, output, language, out_path, **kwargs) -> list[str]:
    """保存截图；多页时生成 ide_screenshot_p1.png, _p2.png ..."""
    pages = render_ide_screenshot_pages(code, output, language, **kwargs)
    base = Path(out_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    if len(pages) == 1:
        p = str(base)
        _save_png(pages[0], p)
        return [p]
    stem = base.stem
    suffix = base.suffix or '.png'
    parent = base.parent
    for i, img in enumerate(pages, 1):
        p = str(parent / f'{stem}_p{i}{suffix}')
        _save_png(img, p)
        paths.append(p)
    return paths
