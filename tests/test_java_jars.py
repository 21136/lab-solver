"""V5-3 curated Java JAR sandbox tests."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "python"))

from modules.java_jars import (  # noqa: E402
    CURATED_JAR_CATALOG,
    build_java_classpath,
    detect_required_jar_ids,
    find_non_whitelist_imports,
    is_jar_installed,
    list_curated_jars_status,
    prepare_validation_jars,
)
from modules.user_constraints import normalize_user_constraints  # noqa: E402


def test_detect_h2_and_sqlite_imports():
    h2_code = "import org.h2.Driver;\npublic class Main {}"
    sqlite_code = "import org.sqlite.JDBC;\npublic class Main {}"
    assert detect_required_jar_ids(h2_code) == ["h2"]
    assert detect_required_jar_ids(sqlite_code) == ["sqlite-jdbc"]
    assert detect_required_jar_ids("import java.util.List;\n") == []


def test_find_non_whitelist_imports():
    code = "import org.mybatis.Session;\npublic class Main {}"
    assert find_non_whitelist_imports(code) == ["org.mybatis.Session"]


def test_normalize_conflicting_jar_constraints():
    assert normalize_user_constraints(["no_external_jar", "allow_curated_jars"]) == [
        "no_external_jar"
    ]


def test_prepare_validation_jars_no_external_jar_skips_detection():
    code = "import org.h2.Driver;\npublic class Main {}"
    paths, skip = prepare_validation_jars(code, "java", ["no_external_jar"])
    assert paths == []
    assert skip is None


def test_prepare_validation_jars_missing_without_consent_pauses():
    code = "import org.h2.Driver;\npublic class Main {}"
    with patch("modules.java_jars.is_jar_installed", return_value=False):
        paths, skip = prepare_validation_jars(code, "java", ["allow_curated_jars"])
    assert paths == []
    assert skip is not None
    assert skip["reason"] == "missing_jar"
    assert skip["missing_jars"][0]["id"] == "h2"


def test_prepare_validation_jars_download_on_consent(tmp_path, monkeypatch):
    code = "import org.h2.Driver;\npublic class Main {}"
    jar_file = tmp_path / CURATED_JAR_CATALOG["h2"]["filename"]
    jar_file.write_bytes(b"fake-jar")

    monkeypatch.setattr("modules.java_jars.JARS_DIR", tmp_path)

    def _consent(missing):
        assert missing[0]["id"] == "h2"
        return True

    with patch("modules.java_jars.is_jar_installed", return_value=False):
        with patch("modules.java_jars.download_curated_jar", return_value=jar_file):
            paths, skip = prepare_validation_jars(
                code, "java", ["allow_curated_jars"], on_jar_consent=_consent
            )
    assert skip is None
    assert paths == [str(jar_file)]


def test_prepare_validation_jars_approved_ids_download(tmp_path, monkeypatch):
    code = "import org.h2.Driver;\npublic class Main {}"
    jar_file = tmp_path / CURATED_JAR_CATALOG["h2"]["filename"]
    jar_file.write_bytes(b"fake-jar")
    monkeypatch.setattr("modules.java_jars.JARS_DIR", tmp_path)

    with patch("modules.java_jars.is_jar_installed", return_value=False):
        with patch("modules.java_jars.download_curated_jar", return_value=jar_file) as dl:
            paths, skip = prepare_validation_jars(
                code,
                "java",
                ["allow_curated_jars"],
                approved_jar_ids=["h2"],
            )
    dl.assert_called_once_with("h2")
    assert skip is None
    assert paths == [str(jar_file)]


def test_build_java_classpath_windows_style():
    cp = build_java_classpath("/work", ["/jars/h2.jar"])
    assert cp == "/jars/h2.jar;/work"


def test_list_curated_jars_status_structure():
    rows = list_curated_jars_status()
    assert len(rows) == len(CURATED_JAR_CATALOG)
    assert all("installed" in r and "purpose" in r for r in rows)


def test_is_jar_installed_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("modules.java_jars.JARS_DIR", tmp_path)
    assert not is_jar_installed("h2")
