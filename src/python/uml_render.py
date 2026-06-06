"""PlantUML 渲染：类图、时序图等 UML（本地 JAR 优先，可选在线）"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zlib
from pathlib import Path

try:
    import urllib.request
except ImportError:
    urllib = None  # type: ignore

ASSETS_DIR = Path(__file__).resolve().parent / 'assets'
PLANTUML_JAR = ASSETS_DIR / 'plantuml.jar'
APP_DATA = Path(os.environ.get('APPDATA', tempfile.gettempdir())) / 'lab-solver'
JRE_DIR = APP_DATA / 'jre'
MAX_DIAGRAMS = 12

_DFD_PATTERN = re.compile(
    r'数据流图|DFD|dfd|结构化分析|顶层图|0层图|一层图|'
    r'外部实体.*处理.*数据存储|数据存储.*数据流',
    re.I,
)
_UML_PATTERN = re.compile(
    r'类图|时序图|顺序图|用例图|活动图|状态图|状态转换|状态机|'
    r'ER图|E-R图|E-R|实体联系|实体关系|部署图|构件图|组件图|包图|'
    r'流程图|UML|PlantUML|plantuml|设计模式|设计图.*类|画出.*图|绘制.*图',
    re.I,
)
_KIND_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ('class', re.compile(r'类图|设计模式|UML类|面向对象设计', re.I)),
    ('sequence', re.compile(r'时序图|顺序图|交互图|消息序列', re.I)),
    ('usecase', re.compile(r'用例图|参与者|需求分析', re.I)),
    ('activity', re.compile(r'活动图|业务流程(?!.*数据流)', re.I)),
    ('state', re.compile(r'状态图|状态转换|状态机|状态模式', re.I)),
    ('er', re.compile(r'ER图|E-R图|E-R|实体联系|实体关系|数据库设计', re.I)),
    ('deployment', re.compile(r'部署图|服务器节点|B/S|C/S架构|系统部署', re.I)),
    ('component', re.compile(r'构件图|组件图|软件体系结构', re.I)),
    ('package', re.compile(r'包图|package\s*diagram', re.I)),
    ('flowchart', re.compile(r'流程图|程序流程', re.I)),
    ('dfd', _DFD_PATTERN),
]


def detect_diagram_needs(full_text: str, metadata: dict | None = None) -> dict:
    """
    分析报告是否需要设计图。

    Returns:
        needs_uml: PlantUML 类图/时序图等
        needs_dfd: 标准数据流图（供 Planner 提示；Phase C 渲染）
        kinds: 推断的图类型列表（中文标签，供 Planner reason）
        evidence: 命中的原文短片段
    """
    text = full_text or ''
    needs_dfd = bool(_DFD_PATTERN.search(text))
    needs_uml = bool(_UML_PATTERN.search(text)) or needs_dfd

    kinds: list[str] = []
    for kind, pattern in _KIND_HINTS:
        if pattern.search(text):
            label = {
                'class': '类图', 'sequence': '时序图', 'usecase': '用例图',
                'activity': '活动图', 'state': '状态图', 'er': 'ER图',
                'deployment': '部署图', 'component': '构件图', 'package': '包图',
                'flowchart': '流程图', 'dfd': '数据流图',
            }.get(kind, kind)
            if label not in kinds:
                kinds.append(label)

    meta = metadata or {}
    major = (meta.get('major') or '') + (meta.get('course') or '')
    if not needs_uml and any(k in major for k in ('软件', '计算机', '信息')):
        if re.search(r'设计|建模|面向对象|OO|设计模式', text):
            needs_uml = True
            if '类图' not in kinds:
                kinds.append('类图')

    evidence = ''
    for pattern in (_UML_PATTERN, _DFD_PATTERN):
        m = pattern.search(text)
        if m:
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 12)
            evidence = text[start:end].strip()
            break

    return {
        'needs_uml': needs_uml,
        'needs_dfd': needs_dfd,
        'kinds': kinds,
        'evidence': evidence,
    }


def detect_needs_uml(full_text: str, metadata: dict | None = None) -> dict:
    """兼容入口：返回 detect_diagram_needs 结果（含 needs_uml / needs_dfd）。"""
    return detect_diagram_needs(full_text, metadata)


def normalize_plantuml(source: str) -> str:
    s = (source or '').strip().replace('\r\n', '\n')
    if not s:
        return '@startuml\nnote "empty"\n@enduml'
    low = s.lower()
    if '@startuml' not in low:
        s = '@startuml\n' + s
    if '@enduml' not in low:
        s = s + '\n@enduml'
    return s


def _encode_plantuml_hex(text: str) -> str:
    """PlantUML HEX 编码（~h 前缀，无压缩，兼容性最好）。"""
    return "~h" + text.encode("utf-8").hex()


def is_plantuml_error_png(data: bytes) -> bool:
    """PlantUML 服务端错误会以 PNG 形式返回，内含可读错误文本。"""
    if not data or len(data) < 200:
        return True
    markers = (
        b"bad URL",
        b"HUFFMAN",
        b"DEFLATE",
        b"Syntax Error",
        b"Error line",
        b"The plugin you are using",
    )
    return any(m in data for m in markers)


def _encode_plantuml_url(text: str) -> str:
    """PlantUML 官方 URL 编码（zlib + 自定义 base64）"""
    data = text.encode('utf-8')
    compressed = zlib.compress(data, 9)[2:-4]

    def encode6bit(b: int) -> str:
        if b < 10:
            return chr(48 + b)
        b -= 10
        if b < 26:
            return chr(65 + b)
        b -= 26
        if b < 26:
            return chr(97 + b)
        b -= 26
        if b == 0:
            return '0'
        if b == 1:
            return '1'
        return '?'

    def encode3bytes(b1: int, b2: int, b3: int) -> str:
        c1 = b1 >> 2
        c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
        c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
        c4 = b3 & 0x3F
        return encode6bit(c1) + encode6bit(c2) + encode6bit(c3) + encode6bit(c4)

    res = ''
    i = 0
    while i < len(compressed):
        if i + 2 < len(compressed):
            res += encode3bytes(compressed[i], compressed[i + 1], compressed[i + 2])
        elif i + 1 < len(compressed):
            res += encode3bytes(compressed[i], compressed[i + 1], 0)
        else:
            res += encode3bytes(compressed[i], 0, 0)
        i += 3
    return res


def _find_java() -> str | None:
    for p in JRE_DIR.glob('*/bin/java.exe'):
        return str(p)
    for name in ('java', 'java.exe'):
        try:
            r = subprocess.run([name, '-version'], capture_output=True, timeout=8)
            if r.returncode == 0 or r.stderr or r.stdout:
                return name
        except Exception:
            continue
    return None


def render_plantuml_png(source: str, out_path: str | Path, allow_online: bool = True) -> str:
    """渲染单张 PlantUML 图为 PNG，返回输出路径"""
    text = normalize_plantuml(source)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    err_local = _render_local_jar(text, out)
    if out.is_file() and out.stat().st_size > 100:
        if not is_plantuml_error_png(out.read_bytes()):
            return str(out)
        out.unlink(missing_ok=True)

    if allow_online and urllib:
        err_online = _render_online_png(text, out)
        if out.is_file() and out.stat().st_size > 100:
            if not is_plantuml_error_png(out.read_bytes()):
                return str(out)
            out.unlink(missing_ok=True)
        raise RuntimeError(err_online or err_local or 'UML 渲染失败')

    raise RuntimeError(err_local or '本地未找到 Java/PlantUML，且未启用在线渲染')


def _render_local_jar(text: str, out: Path) -> str | None:
    if not PLANTUML_JAR.is_file():
        return '未找到 plantuml.jar（可放到 src/python/assets/plantuml.jar）'
    java = _find_java()
    if not java:
        return '未找到 Java 运行环境'
    tmpdir = Path(tempfile.mkdtemp(prefix='uml_'))
    src = tmpdir / 'diagram.puml'
    src.write_text(text, encoding='utf-8')
    try:
        subprocess.run(
            [java, '-jar', str(PLANTUML_JAR), '-tpng', '-o', str(tmpdir), str(src)],
            capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace',
        )
        pngs = list(tmpdir.glob('*.png'))
        if not pngs:
            return 'PlantUML 本地渲染无输出'
        import shutil
        shutil.copy2(pngs[0], out)
        return None
    except Exception as e:
        return str(e)
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def _fetch_plantuml_png(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'lab-solver/1.0'})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read()


def _render_online_png(text: str, out: Path) -> str | None:
    attempts = [
        ("deflate", f'https://www.plantuml.com/plantuml/png/{_encode_plantuml_url(text)}'),
        ("hex", f'https://www.plantuml.com/plantuml/png/{_encode_plantuml_hex(text)}'),
    ]
    last_err = None
    for kind, url in attempts:
        try:
            data = _fetch_plantuml_png(url)
            if len(data) < 200:
                last_err = f'在线渲染({kind})返回数据过小'
                continue
            if is_plantuml_error_png(data):
                last_err = f'在线渲染({kind})返回错误图（编码不兼容）'
                continue
            out.write_bytes(data)
            return None
        except Exception as e:
            last_err = f'在线 PlantUML({kind})失败: {e}'
    return last_err or '在线 PlantUML 渲染失败'


def _is_dfd_diagram(d: dict) -> bool:
    kind = (d.get('kind') or '').lower()
    if kind == 'dfd' or d.get('source_engine') == 'graphviz':
        return True
    try:
        from dfd_layout import extract_dfd_json
        return extract_dfd_json(d) is not None
    except ImportError:
        return False


def render_diagrams(diagrams: list, temp_dir: Path, allow_online: bool = True) -> list[dict]:
    """
    diagrams: [{kind, title, plantuml|dfd_json}, ...]
    返回 [{title, kind, path}, ...]
    """
    results = []
    if not diagrams:
        return results
    temp_dir.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(diagrams[:MAX_DIAGRAMS]):
        if not isinstance(d, dict):
            continue
        kind = (d.get('kind') or 'uml').lower()
        title = d.get('title') or f'{kind}_{i + 1}'

        if _is_dfd_diagram(d):
            out = temp_dir / f'dfd_{i}.png'
            try:
                from dfd_render import render_dfd_png
                render_dfd_png(d, out, title=title)
                results.append({'title': title, 'kind': 'dfd', 'path': str(out)})
            except Exception as e:
                results.append({'title': title, 'kind': 'dfd', 'error': str(e)})
            continue

        src = d.get('plantuml') or d.get('source') or ''
        if not str(src).strip():
            continue
        out = temp_dir / f'uml_{i}_{kind}.png'
        try:
            render_plantuml_png(src, out, allow_online=allow_online)
            results.append({'title': title, 'kind': kind, 'path': str(out)})
        except Exception as e:
            results.append({'title': title, 'kind': kind, 'error': str(e)})
    return results
