"""Shared paths, optional dependency flags, and runtime environment probes."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMP_DIR = Path(tempfile.gettempdir()) / "lab_solver"
APP_DATA = Path(os.environ.get("APPDATA", TEMP_DIR)) / "lab-solver"
JRE_DIR = APP_DATA / "jre"
JARS_DIR = APP_DATA / "jars"
TEMP_DIR.mkdir(exist_ok=True)
APP_DATA.mkdir(exist_ok=True)

LOG_FILE = APP_DATA / "app.log"

try:
    from docx import Document  # noqa: F401
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    import fitz  # noqa: F401  # PyMuPDF

    PDF_OK = True
except ImportError:
    PDF_OK = False

try:
    from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    PIL_OK = True
except ImportError:
    PIL_OK = False

OCR_OK = False
if shutil.which("tesseract"):
    try:
        import pytesseract  # noqa: F401

        OCR_OK = True
    except ImportError:
        OCR_OK = False

try:
    from uml_render import detect_needs_uml, render_diagrams  # noqa: F401
    UML_RENDER_OK = True
except ImportError:
    UML_RENDER_OK = False

    def detect_needs_uml(*_args, **_kwargs):
        return {"needs_uml": False, "needs_dfd": False, "kinds": [], "evidence": ""}

    def render_diagrams(*_args, **_kwargs):
        return []


# ══════════════════════════════════════════════════════
# Runtime environment probes (L4 — injected into LLM prompts)
# ══════════════════════════════════════════════════════

# PEP 594 — modules removed in Python 3.13+
_PEP594_REMOVED = (
    "aifc", "audioop", "cgi", "cgitb", "chunk", "crypt", "imghdr",
    "mailcap", "msilib", "nis", "nntplib", "ossaudiodev", "pipes",
    "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib",
)

# Common pip packages used in university lab assignments
_COMMON_PIP_PACKAGES = (
    "numpy", "matplotlib", "pandas", "scipy", "sklearn",
    "requests", "flask", "django", "pillow",
    "turtle", "tkinter", "pygame", "openpyxl", "jieba",
    "pymysql", "sqlite3",
)


def _probe_python_env():
    """Detect Python version, removed stdlib modules, and available pip packages.

    Runs once at import time (module-level cache). Falls back gracefully
    to empty results on any error.
    """
    result = {"version": "", "removed_modules": [], "available_packages": [], "probe_ok": False}
    try:
        result["version"] = sys.version.split()[0]  # "3.14.0"
        result["probe_ok"] = True
    except Exception:
        return result

    for mod in _PEP594_REMOVED:
        try:
            __import__(mod)
        except (ImportError, ModuleNotFoundError):
            result["removed_modules"].append(mod)
        except Exception:
            pass

    for mod in _COMMON_PIP_PACKAGES:
        try:
            __import__(mod)
            result["available_packages"].append(mod)
        except (ImportError, ModuleNotFoundError):
            pass
        except Exception:
            pass

    return result


def _probe_java_env():
    result = {
        "available": False,
        "javac_path": "",
        "java_path": "",
        "version_info": "",
        "installed_jars": [],
    }
    try:
        javac = None
        for p in JRE_DIR.glob("*/bin/javac.exe"):
            javac = str(p)
            break
        if not javac:
            javac = shutil.which("javac")
        java = None
        for p in JRE_DIR.glob("*/bin/java.exe"):
            java = str(p)
            break
        if not java:
            java = shutil.which("java")
        if javac and java:
            result["available"] = True
            result["javac_path"] = javac
            result["java_path"] = java
            try:
                r = subprocess.run(
                    [java, "-version"], capture_output=True, timeout=10
                )
                version_line = (r.stderr or r.stdout).decode("utf-8", errors="replace")
                result["version_info"] = version_line.strip().split("\n")[0] if version_line else ""
            except Exception:
                pass
        try:
            from modules.java_jars import list_installed_jars

            result["installed_jars"] = list_installed_jars()
        except Exception:
            pass
    except Exception:
        pass
    return result


def _probe_c_env():
    result = {"gcc_available": False, "gpp_available": False}
    try:
        result["gcc_available"] = shutil.which("gcc") is not None
        result["gpp_available"] = shutil.which("g++") is not None
    except Exception:
        pass
    return result


def _probe_node_env():
    result = {"available": False}
    try:
        result["available"] = shutil.which("node") is not None
    except Exception:
        pass
    return result


# Module-level cache — probed once on first import
_PYTHON_ENV = None
_JAVA_ENV = None
_C_ENV = None
_NODE_ENV = None


def get_python_env():
    global _PYTHON_ENV
    if _PYTHON_ENV is None:
        _PYTHON_ENV = _probe_python_env()
    return _PYTHON_ENV


def get_java_env():
    global _JAVA_ENV
    if _JAVA_ENV is None:
        _JAVA_ENV = _probe_java_env()
    return _JAVA_ENV


def get_c_env():
    global _C_ENV
    if _C_ENV is None:
        _C_ENV = _probe_c_env()
    return _C_ENV


def get_node_env():
    global _NODE_ENV
    if _NODE_ENV is None:
        _NODE_ENV = _probe_node_env()
    return _NODE_ENV


def build_python_env_section():
    """Prompt injection string describing the Python runtime environment."""
    env = get_python_env()
    if not env.get("probe_ok"):
        return ""

    lines = [f"当前 Python 环境：{env['version']}"]
    if env.get("removed_modules"):
        removed = ", ".join(env["removed_modules"])
        lines.append(f"以下模块已在 Python 3.13+ 移除，禁止 import：{removed}")
    if env.get("available_packages"):
        pkgs = ", ".join(env["available_packages"])
        lines.append(f"已安装的第三方库（可直接 import）：{pkgs}")
    return "\n".join(lines)


def build_java_env_section():
    env = get_java_env()
    if not env.get("available"):
        return "当前环境：Java 运行时不可用（未安装 JDK）"
    lines = ["当前 Java 环境可用"]
    if env.get("version_info"):
        lines.append(f"Java 版本：{env['version_info']}")
    installed = env.get("installed_jars") or []
    if installed:
        names = ", ".join(j.get("label") or j.get("id", "") for j in installed)
        lines.append(f"验证沙箱已安装扩展库（仅内化验证）：{names}")
    return "\n".join(lines)


def build_c_env_section():
    env = get_c_env()
    parts = []
    if env.get("gcc_available"):
        parts.append("gcc 可用")
    else:
        parts.append("gcc 不可用（需 MinGW-w64）")
    if env.get("gpp_available"):
        parts.append("g++ 可用")
    else:
        parts.append("g++ 不可用（需 MinGW-w64）")
    return "当前 C/C++ 环境：" + "，".join(parts)


def build_js_env_section():
    env = get_node_env()
    if env.get("available"):
        return "当前环境：Node.js 可用"
    return "当前环境：Node.js 不可用（未安装）"


# ══════════════════════════════════════════════════════
# Aggregated runtime status + download guides
# ══════════════════════════════════════════════════════

# Download URLs use domestic Chinese mirrors for speed.
# Key: runtime key in get_all_runtime_status().
RUNTIME_DOWNLOAD_GUIDES = {
    "python": {
        "label": "Python",
        "download_url": "https://npmmirror.com/mirrors/python/3.12.9/python-3.12.9-amd64.exe",
        "install_guide": "下载后双击安装，务必勾选「Add Python to PATH」",
        "language_key": "python",
    },
    "java": {
        "label": "Java (JDK)",
        "download_url": "https://mirrors.huaweicloud.com/openjdk/17.0.2/openjdk-17.0.2_windows-x64_bin.zip",
        "install_guide": "下载 zip 解压到任意目录，将 bin 目录添加到系统 PATH 环境变量；或使用应用内一键下载 JRE",
        "language_key": "java",
        "can_auto_download": True,
        "auto_download_label": "⚡ 一键安装 JRE（应用内置，约 50MB）",
    },
    "c": {
        "label": "MinGW-w64 (C/C++)",
        "download_url": "https://github.com/niXman/mingw-builds-binaries/releases",
        "install_guide": "下载 mingw-install.exe，安装时选择 x86_64-posix-seh 版本",
        "language_key": "c",
    },
    "node": {
        "label": "Node.js",
        "download_url": "https://npmmirror.com/mirrors/node/v20.18.0/node-v20.18.0-x64.msi",
        "install_guide": "下载 msi 双击安装，自动加入 PATH",
        "language_key": "javascript",
    },
}


def get_diagram_tools_status() -> dict:
    """Probe bundled PlantUML / Java / portable Graphviz for /api/runtime-status."""
    from pathlib import Path as _Path

    py_dir = _Path(__file__).resolve().parent
    plantuml_jar = py_dir / "assets" / "plantuml.jar"
    plantuml_jar_ok = plantuml_jar.is_file()

    java_ok = False
    java_version = ""
    try:
        for p in JRE_DIR.glob("*/bin/java.exe"):
            java_ok = True
            break
        if not java_ok:
            java_path = shutil.which("java")
            if java_path:
                java_ok = True
        if java_ok:
            java_bin = None
            for p in JRE_DIR.glob("*/bin/java.exe"):
                java_bin = str(p)
                break
            if not java_bin:
                java_bin = shutil.which("java") or "java"
            r = subprocess.run(
                [java_bin, "-version"], capture_output=True, timeout=10
            )
            java_version = (r.stderr or r.stdout).decode("utf-8", errors="replace").strip().split("\n")[0]
    except Exception:
        pass

    graphviz_ok = False
    graphviz_version = ""
    graphviz_source = "missing"
    graphviz_message = ""
    graphviz_assets = str(py_dir / "assets" / "graphviz")
    try:
        from dfd_render import probe_graphviz

        gv = probe_graphviz(portable_only=True)
        graphviz_ok = bool(gv.get("ok"))
        graphviz_version = gv.get("version") or ""
        graphviz_source = gv.get("source") or "missing"
        graphviz_message = gv.get("message") or ""
        graphviz_assets = gv.get("assets_dir") or graphviz_assets
    except Exception as e:
        graphviz_message = str(e)

    return {
        "plantuml_jar_ok": plantuml_jar_ok,
        "java_ok": java_ok,
        "java_version": java_version,
        "graphviz_ok": graphviz_ok,
        "graphviz_version": graphviz_version,
        "graphviz_source": graphviz_source,
        "graphviz_message": graphviz_message,
        "graphviz_assets_dir": graphviz_assets,
    }


def get_ocr_install_guide() -> dict:
    """Platform-specific Tesseract download URL and install steps for settings UI."""
    tesseract_on_path = bool(shutil.which("tesseract"))
    pytesseract_ok = False
    if tesseract_on_path:
        try:
            import pytesseract  # noqa: F401

            pytesseract_ok = True
        except ImportError:
            pass

    if OCR_OK:
        issue = "ok"
    elif tesseract_on_path and not pytesseract_ok:
        issue = "missing_pytesseract"
    else:
        issue = "missing_tesseract"

    base = {
        "label": "Tesseract OCR",
        "available": OCR_OK,
        "tesseract_on_path": tesseract_on_path,
        "pytesseract_ok": pytesseract_ok,
        "issue": issue,
    }

    if issue == "missing_pytesseract":
        return {
            **base,
            "install_guide": "Tesseract 已安装，但 Python OCR 桥接包 pytesseract 未安装",
            "install_steps": [
                "Tesseract 引擎本身没问题（系统已能找到 tesseract 命令）",
                "缺少的是 Python 包 pytesseract，请在运行本应用的 Python 环境中执行：pip install pytesseract",
                "安装后点「重新检测」；开发模式下重启 Python 后端即可",
            ],
            "alt_hint": "也可在解析页手动粘贴题目文字，无需安装 OCR",
        }

    if sys.platform == "win32":
        return {
            **base,
            "download_url": "https://github.com/UB-Mannheim/tesseract/wiki",
            "download_label": "打开 Tesseract 下载页",
            "lang_pack_url": "https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata",
            "lang_pack_label": "下载中文语言包 (chi_sim)",
            "install_guide": (
                "下载 Windows 安装包并运行；安装时勾选 Additional language data，"
                "选中 Chinese - Simplified (chi_sim)"
            ),
            "install_steps": [
                "点击下方「打开 Tesseract 下载页」，下载 tesseract-ocr-w64-setup 安装包",
                "运行安装程序，在语言包步骤勾选 Chinese - Simplified (chi_sim)",
                "若已安装但缺中文包，可点「下载中文语言包」保存到 Tesseract 的 tessdata 文件夹",
                "安装完成后点「重新检测」；仍失败请完全退出并重启本应用",
            ],
            "alt_hint": "也可在解析页手动粘贴题目文字，无需安装 OCR",
        }
    if sys.platform == "darwin":
        return {
            **base,
            "download_url": "https://formulae.brew.sh/formula/tesseract-lang",
            "download_label": "查看 Homebrew 说明",
            "install_guide": "终端执行：brew install tesseract tesseract-lang",
            "install_steps": [
                "打开「终端」，运行：brew install tesseract tesseract-lang",
                "安装完成后点「重新检测」；仍失败请完全退出并重启本应用",
            ],
            "alt_hint": "也可在解析页手动粘贴题目文字，无需安装 OCR",
        }
    return {
        **base,
        "download_url": "https://github.com/tesseract-ocr/tesseract",
        "download_label": "查看 Tesseract 官方说明",
        "install_guide": "Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-chi-sim",
        "install_steps": [
            "Ubuntu/Debian：sudo apt install tesseract-ocr tesseract-ocr-chi-sim",
            "Fedora：sudo dnf install tesseract tesseract-langpack-chi_sim",
            "Arch：sudo pacman -S tesseract tesseract-data-chi_sim",
            "安装完成后点「重新检测」；仍失败请完全退出并重启本应用",
        ],
        "alt_hint": "也可在解析页手动粘贴题目文字，无需安装 OCR",
    }


def get_all_runtime_status():
    """Aggregate all four language probes into a single dict with download guides.

    Returns a dict keyed by runtime id (python/java/c/node), each with
    ``available``, version info, download URL, and install instructions.
    Also includes ``any_available`` at the top level.
    """
    py = get_python_env()
    java = get_java_env()
    c_env = get_c_env()
    node = get_node_env()

    result = {
        "python": {
            "available": py.get("probe_ok", False) and py.get("version", "") != "",
            "version": py.get("version", ""),
            **RUNTIME_DOWNLOAD_GUIDES["python"],
        },
        "java": {
            "available": java.get("available", False),
            "version_info": java.get("version_info", ""),
            **RUNTIME_DOWNLOAD_GUIDES["java"],
        },
        "c": {
            "available": c_env.get("gcc_available", False) or c_env.get("gpp_available", False),
            "gcc_available": c_env.get("gcc_available", False),
            "gpp_available": c_env.get("gpp_available", False),
            **RUNTIME_DOWNLOAD_GUIDES["c"],
        },
        "node": {
            "available": node.get("available", False),
            **RUNTIME_DOWNLOAD_GUIDES["node"],
        },
    }
    result["any_available"] = any(
        result[k]["available"] for k in ["python", "java", "c", "node"]
    )
    return result


def _any_runtime_available() -> bool:
    return get_all_runtime_status()["any_available"]


def _runtime_available_for(language: str) -> bool:
    rt = get_all_runtime_status()
    lang_map = {
        "python": rt["python"]["available"],
        "java": rt["java"]["available"],
        "c": rt["c"]["available"],
        "cpp": rt["c"]["available"],
        "javascript": rt["node"]["available"],
    }
    return lang_map.get((language or "").lower(), False)
