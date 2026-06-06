"""Convert legacy .doc (binary Word) to .docx.

Tries Word COM automation first (most reliable on Windows),
falls back to LibreOffice headless, caches result by SHA-256 hash.
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from config import TEMP_DIR


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_libreoffice() -> str | None:
    """Locate LibreOffice soffice.exe."""
    candidates = [
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return shutil.which("soffice")


def _convert_via_com(doc_path: Path, out_path: Path) -> Path | None:
    """Convert using Microsoft Word COM automation (wdFormatXMLDocument=16)."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None

    word = None
    try:
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        doc = word.Documents.Open(str(doc_path))
        if out_path.exists():
            out_path.unlink()
        doc.SaveAs2(str(out_path), FileFormat=16)
        doc.Close()
        return out_path
    except Exception:
        return None
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _convert_via_libreoffice(doc_path: Path, out_path: Path) -> Path | None:
    """Convert using LibreOffice headless CLI."""
    soffice = _find_libreoffice()
    if not soffice:
        return None

    # LibreOffice names output after input stem → use a temp work dir
    work_dir = TEMP_DIR / f"_lo_{os.getpid()}_{doc_path.stem}"
    work_dir.mkdir(exist_ok=True)
    try:
        work_input = work_dir / doc_path.name
        shutil.copy2(doc_path, work_input)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", str(work_dir), str(work_input)],
            capture_output=True,
            timeout=120,
            text=True,
        )
        converted = work_dir / f"{doc_path.stem}.docx"
        if converted.exists() and converted.stat().st_size > 0:
            if out_path.exists():
                out_path.unlink()
            shutil.copy2(converted, out_path)
            return out_path
        return None
    except Exception:
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def convert_doc_to_docx(doc_path: Path) -> tuple[Path | None, str | None]:
    """Convert a legacy .doc file to .docx.

    Returns (converted_docx_path, error_message).
    On success error_message is None; on failure path is None.
    Caches result by file content hash in TEMP_DIR.
    """
    try:
        fhash = _file_hash(doc_path)
    except Exception:
        return None, "无法读取 .doc 文件"

    cached = TEMP_DIR / f"_conv_{fhash[:16]}.docx"
    if cached.exists() and cached.stat().st_size > 0:
        return cached, None

    # 1) Word COM
    result = _convert_via_com(doc_path, cached)
    if result and result.exists() and result.stat().st_size > 0:
        return result, None

    # 2) LibreOffice
    result = _convert_via_libreoffice(doc_path, cached)
    if result and result.exists() and result.stat().st_size > 0:
        return result, None

    return None, (
        "旧版 .doc 无法解析。\n"
        "请安装免费的 LibreOffice（https://www.libreoffice.org）\n"
        "或在 Microsoft Word 中「另存为」.docx 后重新上传。"
    )
