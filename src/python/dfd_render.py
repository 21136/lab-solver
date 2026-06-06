"""Portable Graphviz rendering for standard DFD diagrams."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dfd_layout import dfd_to_dot, extract_dfd_json, validate_dfd

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
GRAPHVIZ_BIN = ASSETS_DIR / "graphviz" / "bin"
DOT_MISSING_MSG = "未找到便携 Graphviz，请检查 assets/graphviz 是否完整"


def _portable_dot_path() -> Path | None:
    if sys.platform == "win32":
        candidate = GRAPHVIZ_BIN / "dot.exe"
    else:
        candidate = GRAPHVIZ_BIN / "dot"
    return candidate if candidate.is_file() else None


def _find_dot() -> str | None:
    """Portable assets/graphviz/bin first, then system PATH."""
    portable = _portable_dot_path()
    if portable:
        return str(portable)
    for name in ("dot.exe", "dot") if sys.platform == "win32" else ("dot",):
        found = shutil.which(name)
        if found:
            return found
    return None


def _dot_env(dot_path: str) -> dict[str, str]:
    """Ensure portable Graphviz finds its lib/ DLLs on Windows."""
    env = os.environ.copy()
    lib_dir = Path(dot_path).resolve().parent.parent / "lib"
    if lib_dir.is_dir():
        path_key = "PATH"
        existing = env.get(path_key, "")
        lib_str = str(lib_dir)
        if lib_str not in existing:
            env[path_key] = lib_str + os.pathsep + existing if existing else lib_str
    return env


def probe_graphviz(*, portable_only: bool = False) -> dict:
    """
    Check whether dot is executable.

    Returns:
        ok, dot_path, source (portable|system|missing), version, message
    """
    portable = _portable_dot_path()
    dot = str(portable) if portable else None
    source = "portable" if dot else "missing"
    if not dot and not portable_only:
        dot = _find_dot()
        if dot:
            source = "portable" if str(portable or "") == dot else "system"
    if not dot:
        return {
            "ok": False,
            "dot_path": "",
            "source": "missing",
            "version": "",
            "message": DOT_MISSING_MSG,
            "assets_dir": str(ASSETS_DIR / "graphviz"),
        }
    try:
        r = subprocess.run(
            [dot, "-V"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            env=_dot_env(dot),
        )
        version = (r.stderr or r.stdout or "").strip().split("\n")[0]
        ok = r.returncode == 0 or bool(version)
        return {
            "ok": ok,
            "dot_path": dot,
            "source": source,
            "version": version,
            "message": "" if ok else "dot -V 执行失败",
            "assets_dir": str(ASSETS_DIR / "graphviz"),
        }
    except Exception as e:
        return {
            "ok": False,
            "dot_path": dot,
            "source": source,
            "version": "",
            "message": str(e),
            "assets_dir": str(ASSETS_DIR / "graphviz"),
        }


def render_dfd_png(diagram: dict, out_path: str | Path, *, title: str = "") -> str:
    """Render one DFD diagram dict to PNG; return output path."""
    data = extract_dfd_json(diagram)
    if not data:
        raise ValueError("kind=dfd 需要 dfd_json 或 source 中的 JSON 字符串")
    errors = validate_dfd(data)
    if errors:
        raise ValueError("DFD 校验失败: " + "; ".join(errors))

    dot_text = dfd_to_dot(data, title=title or diagram.get("title") or "")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    dot = _find_dot()
    if not dot:
        raise RuntimeError(
            f"{DOT_MISSING_MSG}（期望目录: {ASSETS_DIR / 'graphviz'}）"
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="dfd_"))
    dot_file = tmpdir / "diagram.dot"
    dot_file.write_text(dot_text, encoding="utf-8")
    try:
        r = subprocess.run(
            [dot, "-Tpng", "-o", str(out), str(dot_file)],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
            env=_dot_env(dot),
        )
        if r.returncode != 0 or not out.is_file() or out.stat().st_size < 100:
            detail = (r.stderr or r.stdout or "无输出").strip()
            raise RuntimeError(f"Graphviz 渲染失败: {detail}")
        return str(out)
    finally:
        try:
            import shutil as _shutil

            _shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def render_dfd_diagrams(diagrams: list, temp_dir: Path) -> list[dict]:
    """Render DFD entries; returns [{title, kind, path}|{title, kind, error}]."""
    results: list[dict] = []
    temp_dir.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(diagrams):
        if not isinstance(d, dict):
            continue
        kind = (d.get("kind") or "").lower()
        if kind != "dfd" and d.get("source_engine") != "graphviz":
            continue
        title = d.get("title") or f"dfd_{i + 1}"
        out = temp_dir / f"dfd_{i}.png"
        try:
            render_dfd_png(d, out, title=title)
            results.append({"title": title, "kind": "dfd", "path": str(out)})
        except Exception as e:
            results.append({"title": title, "kind": "dfd", "error": str(e)})
    return results
