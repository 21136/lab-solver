"""Curated Java JAR catalog for internal validation sandbox only (V5-3)."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

from config import JARS_DIR
from log_util import loge, logi

# Validation sandbox only — not a general dependency resolver.
CURATED_JAR_CATALOG: dict[str, dict[str, Any]] = {
    "h2": {
        "id": "h2",
        "label": "H2 Database",
        "purpose": "内存数据库 JDBC，仅用于内化验证沙箱试编译/试跑",
        "filename": "h2-2.2.224.jar",
        "size_bytes": 2_610_000,
        "url": (
            "https://repo1.maven.org/maven2/com/h2database/h2/2.2.224/h2-2.2.224.jar"
        ),
        "import_prefixes": ("org.h2.",),
    },
    "sqlite-jdbc": {
        "id": "sqlite-jdbc",
        "label": "SQLite JDBC",
        "purpose": "SQLite JDBC 驱动，仅用于内化验证沙箱试编译/试跑",
        "filename": "sqlite-jdbc-3.45.3.0.jar",
        "size_bytes": 13_200_000,
        "url": (
            "https://repo1.maven.org/maven2/org/xerial/sqlite-jdbc/"
            "3.45.3.0/sqlite-jdbc-3.45.3.0.jar"
        ),
        "import_prefixes": ("org.sqlite.",),
    },
}

_JDK_JAVA_PREFIXES = ("java.", "javax.")
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)

JarConsentCallback = Callable[[list[dict[str, Any]]], bool]

JARS_DIR.mkdir(parents=True, exist_ok=True)


def _jar_path(jar_id: str) -> Path:
    meta = CURATED_JAR_CATALOG[jar_id]
    return JARS_DIR / meta["filename"]


def is_jar_installed(jar_id: str) -> bool:
    if jar_id not in CURATED_JAR_CATALOG:
        return False
    return _jar_path(jar_id).is_file()


def list_installed_jars() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for jar_id, meta in CURATED_JAR_CATALOG.items():
        path = _jar_path(jar_id)
        if path.is_file():
            out.append(
                {
                    "id": jar_id,
                    "label": meta["label"],
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return out


def list_curated_jars_status() -> list[dict[str, Any]]:
    """Catalog entries with installed flag (for GET /api/java-jars)."""
    installed = {j["id"] for j in list_installed_jars()}
    rows: list[dict[str, Any]] = []
    for jar_id, meta in CURATED_JAR_CATALOG.items():
        rows.append(
            {
                "id": jar_id,
                "label": meta["label"],
                "purpose": meta["purpose"],
                "size_bytes": meta["size_bytes"],
                "installed": jar_id in installed,
                "path": str(_jar_path(jar_id)) if jar_id in installed else None,
            }
        )
    return rows


def _normalize_pkg(import_target: str) -> str:
    pkg = (import_target or "").strip()
    if pkg.endswith(".*"):
        pkg = pkg[:-2]
    return pkg


def iter_java_imports(code: str) -> list[str]:
    return [_normalize_pkg(m.group(1)) for m in _IMPORT_RE.finditer(code or "")]


def _is_jdk_import(pkg: str) -> bool:
    return any(pkg == p.rstrip(".") or pkg.startswith(p) for p in _JDK_JAVA_PREFIXES)


def jar_ids_for_import(pkg: str) -> list[str]:
    matches: list[str] = []
    for jar_id, meta in CURATED_JAR_CATALOG.items():
        if any(pkg.startswith(prefix) for prefix in meta["import_prefixes"]):
            matches.append(jar_id)
    return matches


def detect_required_jar_ids(code: str) -> list[str]:
    required: list[str] = []
    for pkg in iter_java_imports(code):
        if _is_jdk_import(pkg):
            continue
        for jar_id in jar_ids_for_import(pkg):
            if jar_id not in required:
                required.append(jar_id)
    return required


def find_non_whitelist_imports(code: str) -> list[str]:
    """Third-party imports not covered by curated jar prefixes."""
    unknown: list[str] = []
    for pkg in iter_java_imports(code):
        if _is_jdk_import(pkg):
            continue
        if jar_ids_for_import(pkg):
            continue
        if pkg not in unknown:
            unknown.append(pkg)
    return unknown


def jar_info_for_consent(jar_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for jar_id in jar_ids:
        meta = CURATED_JAR_CATALOG.get(jar_id)
        if not meta:
            continue
        rows.append(
            {
                "id": jar_id,
                "label": meta["label"],
                "purpose": meta["purpose"],
                "size_bytes": meta["size_bytes"],
            }
        )
    return rows


def download_curated_jar(jar_id: str) -> Path:
    if jar_id not in CURATED_JAR_CATALOG:
        raise ValueError(f"未知 jar id: {jar_id}")
    meta = CURATED_JAR_CATALOG[jar_id]
    dest = _jar_path(jar_id)
    if dest.is_file():
        return dest
    JARS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JARS_DIR / f".{meta['filename']}.download"
    logi("java_jars", f"下载 {jar_id} → {dest.name}")
    try:
        urllib.request.urlretrieve(meta["url"], str(tmp))
        tmp.replace(dest)
        logi("java_jars", f"已安装 {jar_id} ({dest.stat().st_size} bytes)")
        return dest
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def resolve_jar_paths(jar_ids: list[str]) -> list[str]:
    return [str(_jar_path(jid)) for jid in jar_ids if _jar_path(jid).is_file()]


def build_java_classpath(work_dir: Path | str, jar_paths: list[str] | None = None) -> str:
    parts = list(jar_paths or [])
    parts.append(str(work_dir))
    return ";".join(parts)


def prepare_validation_jars(
    code: str,
    language: str,
    constraints: list[str],
    *,
    on_jar_consent: JarConsentCallback | None = None,
    approved_jar_ids: list[str] | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    """Resolve classpath jars for sandbox validation.

    Returns (jar_paths, skip_run_result). When skip_run_result is set, do not run code.
    """
    if (language or "").lower() != "java":
        return [], None
    if "no_external_jar" in constraints:
        return [], None
    if "allow_curated_jars" not in constraints:
        return [], None

    required_ids = detect_required_jar_ids(code)
    if not required_ids:
        return [], None

    unknown = find_non_whitelist_imports(code)
    if unknown:
        return [], {
            "stdout": "",
            "stderr": f"代码 import 了未白名单的第三方包：{', '.join(unknown)}",
            "exit_code": 1,
            "is_error": True,
            "pattern": "external_jar",
            "reason": "non_whitelist_import",
        }

    missing = [jid for jid in required_ids if not is_jar_installed(jid)]
    if not missing:
        return resolve_jar_paths(required_ids), None

    missing_info = jar_info_for_consent(missing)

    def _download_all(ids: list[str]) -> list[str]:
        for jid in ids:
            download_curated_jar(jid)
        return [str(_jar_path(jid)) for jid in required_ids if _jar_path(jid).is_file()]

    if approved_jar_ids:
        approved = [jid for jid in missing if jid in approved_jar_ids]
        if len(approved) < len(missing):
            return [], {
                "stdout": "",
                "stderr": "用户未同意下载验证所需 jar",
                "exit_code": 0,
                "is_error": False,
                "skipped": True,
                "reason": "jar_download_declined",
                "missing_jars": missing_info,
            }
        return _download_all(approved), None

    if on_jar_consent:
        if on_jar_consent(missing_info):
            return _download_all(missing), None
        return [], {
            "stdout": "",
            "stderr": "用户未同意下载验证所需 jar",
            "exit_code": 0,
            "is_error": False,
            "skipped": True,
            "reason": "jar_download_declined",
            "missing_jars": missing_info,
        }

    return [], {
        "stdout": "",
        "stderr": "验证需要白名单 jar，等待用户确认下载",
        "exit_code": 0,
        "is_error": False,
        "skipped": True,
        "reason": "missing_jar",
        "missing_jars": missing_info,
    }


def invalidate_java_env_cache() -> None:
    """Clear cached Java probe after jar install (config.get_java_env)."""
    import config

    config._JAVA_ENV = None  # noqa: SLF001
