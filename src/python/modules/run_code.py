"""Compile and run user code."""

import os
import re
import subprocess
from pathlib import Path

from config import JRE_DIR, TEMP_DIR
from modules.java_jars import build_java_classpath
from log_util import loge, logi

ERR_PREFIX = "[ERR]"
TIMEOUT_MARKER = "[TIMEOUT]"


def get_java_exe():
    for p in JRE_DIR.glob("*/bin/java.exe"):
        return str(p)
    import shutil

    return shutil.which("java")


def get_javac_exe():
    java = get_java_exe()
    if java:
        javac = Path(java).parent / "javac.exe"
        if javac.exists():
            return str(javac)
    import shutil

    return shutil.which("javac")


def java_status_info():
    java = get_java_exe()
    return {
        "available": java is not None,
        "jre_downloaded": any(JRE_DIR.glob("*/bin/java.exe")),
        "java_path": java,
    }


def execute_multi_file(files, language, main_file, work_dir=None, java_classpath_jars=None):
    """Execute a multi-file code project.

    Args:
        files: list of {name, code} dicts
        language: python | java | c | cpp | javascript
        main_file: entry-point filename (e.g. "main.py")
        work_dir: working directory (default: TEMP_DIR)

    Returns: (output: str, is_error: bool)
    """
    import shutil

    wd = Path(work_dir) if work_dir else TEMP_DIR

    # Clean compiled artifacts from previous runs
    for stale in list(wd.glob("*.class")) + list(wd.glob("*.pyc")) + list(wd.glob("*.exe")) + list(wd.glob("*.out")):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

    # Write all files to work_dir
    kept_names = set()
    for f in files:
        fname = f.get("name") or f.get("filename") or "main.txt"
        fpath = wd / fname
        fpath.write_text(f.get("code") or f.get("content") or "", encoding="utf-8")
        kept_names.add(fname)
        logi("run_multi", f"写入 {fname} ({len(f.get('code', ''))} bytes)")

    # Clean stale source files from previous runs (not in current files list)
    source_ext = {"java": ".java", "python": ".py", "c": ".c", "cpp": ".cpp",
                  "javascript": ".js"}.get((language or "").lower(), "")
    if source_ext:
        for stale in wd.glob(f"*{source_ext}"):
            if stale.name not in kept_names:
                try:
                    stale.unlink(missing_ok=True)
                    logi("run_multi", f"清理残留文件: {stale.name}")
                except OSError:
                    pass

    main_path = wd / main_file

    if language == "java":
        return _run_java_multi(wd, main_file, java_classpath_jars=java_classpath_jars)
    if language == "c":
        return _compile_run_multi("gcc", wd, "*.c", "out_c.exe")
    if language == "cpp":
        return _compile_run_multi("g++", wd, "*.cpp", "out_cpp.exe")
    if language == "javascript":
        node = shutil.which("node")
        if not node:
            return f"{ERR_PREFIX} Node.js 未安装", True
        cmd = [node, str(main_path)]
    else:
        cmd = ["python", "-X", "utf8", str(main_path)]

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, env=env, cwd=str(wd))
        stdout = r.stdout.decode("utf-8", errors="replace")
        stderr = r.stderr.decode("utf-8", errors="replace")
        return (stdout or stderr or "(无输出)"), r.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时（15秒）", True
    except FileNotFoundError as e:
        return f"{ERR_PREFIX} 找不到运行环境: {e}", True


def _run_java_multi(work_dir, main_file, java_classpath_jars=None):
    """Compile all .java files then run the main class."""
    javac = get_javac_exe()
    java = get_java_exe()
    if not javac:
        return f"{ERR_PREFIX} 未找到javac", True

    main_stem = Path(main_file).stem
    cp = build_java_classpath(work_dir, java_classpath_jars)
    try:
        java_files = list(Path(work_dir).glob("*.java"))
        javac_cmd = [javac, "-encoding", "UTF-8", "-cp", cp] + [str(f) for f in java_files]
        logi("java_multi", f"编译 {len(java_files)} 个文件: {[f.name for f in java_files]}")
        rc = subprocess.run(
            javac_cmd, capture_output=True, timeout=30, cwd=str(work_dir)
        )

        def dec(b):
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    return b.decode(enc)
                except Exception:
                    pass
            return b.decode("utf-8", errors="replace")

        if rc.returncode != 0:
            err = dec(rc.stderr or rc.stdout)
            loge("java_multi", err[:300])
            return f"{ERR_PREFIX} 编译错误:\n" + err, True
        logi("java_multi", f"运行 {main_stem}")
        rr = subprocess.run(
            [java, "-Dfile.encoding=UTF-8", "-cp", cp, main_stem],
            capture_output=True, timeout=15,
        )
        out = dec(rr.stdout)
        err = dec(rr.stderr)
        logi("java_multi", f"exit={rr.returncode} out={out[:80]}")
        return (out or err or "(无输出)"), rr.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时", True
    except Exception as e:
        loge("java_multi", str(e))
        return f"{ERR_PREFIX} {e}", True


def _compile_run_multi(compiler, work_dir, glob_pattern, out_name):
    """Compile all source files matching glob_pattern then run."""
    import shutil

    if not shutil.which(compiler):
        return f"{ERR_PREFIX} {compiler} 未安装（mingw-w64.org）", True
    out = Path(work_dir) / out_name
    try:
        import glob as _glob
        sources = list(Path(work_dir).glob(glob_pattern))
        if not sources:
            return f"{ERR_PREFIX} 没有找到源文件", True
        compile_cmd = [compiler] + [str(s) for s in sources] + ["-o", str(out)]
        logi("compile_multi", f"{compiler} {' '.join(s.name for s in sources)}")
        rc = subprocess.run(
            compile_cmd, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if rc.returncode != 0:
            return f"{ERR_PREFIX} 编译错误:\n" + (rc.stderr or rc.stdout), True
        rr = subprocess.run(
            [str(out)], capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return (rr.stdout or rr.stderr or "(无输出)"), rr.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时", True
    except Exception as e:
        return f"{ERR_PREFIX} {e}", True


def execute_code(code, language, java_classpath_jars=None):
    ext = {
        "python": ".py",
        "javascript": ".js",
        "c": ".c",
        "cpp": ".cpp",
        "java": ".java",
    }.get(language, ".py")
    tmp = TEMP_DIR / f"exec{ext}"
    tmp.write_text(code, encoding="utf-8")

    if language == "java":
        return _run_java(code, java_classpath_jars=java_classpath_jars)
    if language == "c":
        return _compile_run("gcc", tmp, "out_c.exe")
    if language == "cpp":
        return _compile_run("g++", tmp, "out_cpp.exe")
    if language == "javascript":
        import shutil

        node = shutil.which("node")
        if not node:
            return f"{ERR_PREFIX} Node.js 未安装", True
        cmd = [node, str(tmp)]
    else:
        cmd = ["python", "-X", "utf8", str(tmp)]

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, env=env)
        stdout = r.stdout.decode("utf-8", errors="replace")
        stderr = r.stderr.decode("utf-8", errors="replace")
        return (stdout or stderr or "(无输出)"), r.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时（15秒）", True
    except FileNotFoundError as e:
        return f"{ERR_PREFIX} 找不到运行环境: {e}", True


def _run_java(code, java_classpath_jars=None):
    javac = get_javac_exe()
    java = get_java_exe()
    if not javac:
        return f"{ERR_PREFIX} 未找到javac", True

    m = re.search(r"public\s+class\s+(\w+)", code)
    cls = m.group(1) if m else "Main"
    jf = TEMP_DIR / f"{cls}.java"
    jf.write_text(code, encoding="utf-8")
    cp = build_java_classpath(TEMP_DIR, java_classpath_jars)

    try:
        logi("java", f"编译 {cls}.java")
        rc = subprocess.run(
            [javac, "-encoding", "UTF-8", "-cp", cp, str(jf)],
            capture_output=True,
            timeout=30,
            cwd=str(TEMP_DIR),
        )

        def dec(b):
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    return b.decode(enc)
                except Exception:
                    pass
            return b.decode("utf-8", errors="replace")

        if rc.returncode != 0:
            err = dec(rc.stderr or rc.stdout)
            loge("java", err[:300])
            return f"{ERR_PREFIX} 编译错误:\n" + err, True
        logi("java", f"运行 {cls}")
        rr = subprocess.run(
            [java, "-Dfile.encoding=UTF-8", "-cp", cp, cls],
            capture_output=True,
            timeout=15,
        )
        out = dec(rr.stdout)
        err = dec(rr.stderr)
        logi("java", f"exit={rr.returncode} out={out[:80]}")
        return (out or err or "(无输出)"), rr.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时", True
    except Exception as e:
        loge("java", str(e))
        return f"{ERR_PREFIX} {e}", True


def _compile_run(compiler, src, out_name):
    import shutil

    if not shutil.which(compiler):
        return f"{ERR_PREFIX} {compiler} 未安装（mingw-w64.org）", True
    out = TEMP_DIR / out_name
    try:
        rc = subprocess.run(
            [compiler, str(src), "-o", str(out)],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if rc.returncode != 0:
            return f"{ERR_PREFIX} 编译错误:\n" + (rc.stderr or rc.stdout), True
        rr = subprocess.run(
            [str(out)],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return (rr.stdout or rr.stderr or "(无输出)"), rr.returncode != 0
    except subprocess.TimeoutExpired:
        return f"{TIMEOUT_MARKER} 运行超时", True
    except Exception as e:
        return f"{ERR_PREFIX} {e}", True


def launch_async_gui(code, language):
    """异步启动 GUI 程序。"""
    ext = {"java": ".java", "python": ".py", "c": ".c", "cpp": ".cpp"}.get(language, ".py")
    tmp = TEMP_DIR / f"gui_prog{ext}"
    tmp.write_text(code, encoding="utf-8")

    if language == "java":
        m = re.search(r"public\s+class\s+(\w+)", code)
        cls = m.group(1) if m else "Main"
        jf = TEMP_DIR / f"{cls}.java"
        jf.write_text(code, encoding="utf-8")
        javac = get_javac_exe()
        java = get_java_exe()
        if not javac:
            return
        subprocess.run([javac, "-encoding", "UTF-8", str(jf)], cwd=str(TEMP_DIR))
        subprocess.Popen([java, "-cp", str(TEMP_DIR), cls])
    elif language == "python":
        subprocess.Popen(["python", str(tmp)])


_ERROR_CATEGORIES = {
    "compile_error": {
        "keywords": [
            "SyntaxError", "编译错误", "error: ", "javac:", "gcc:",
            "class, interface", "需要 class",
        ],
        "message": "编译/语法错误",
    },
    "missing_module": {
        "keywords": [
            "ModuleNotFoundError", "ImportError", "No module named",
            "找不到模块", "cannot import",
        ],
        "message": "缺少 Python 模块或 import 错误",
    },
    "timeout_blocking": {
        "keywords": [f"{TIMEOUT_MARKER} 运行超时"],
        "message": "运行超时 — 代码可能启动了阻塞进程",
    },
    "timeout_slow": {
        "keywords": [f"{TIMEOUT_MARKER} 运行超时"],
        "message": "运行超时 — 算法可能过慢",
    },
}


def classify_run_error(output: str, pattern: str = "") -> dict:
    """Classify a run error into a category for targeted fix strategy.

    Args:
        output: The error output from execute_code.
        pattern: Preflight exec_pattern (web_server/interactive/etc.) or "".

    Returns:
        {category, message, suggestion}
    """
    if not output or output == "(无输出)":
        return {"category": "unknown", "message": "无输出",
                "suggestion": "检查代码是否有 print 语句或返回值"}

    # Timeout: distinguish blocking vs slow using preflight pattern
    if f"{TIMEOUT_MARKER} 运行超时" in output:
        if pattern in ("web_server", "interactive", "possible_infinite"):
            return {
                "category": "timeout_blocking",
                "message": "运行超时 — 代码启动了阻塞进程（Web 服务/交互输入/死循环）",
                "suggestion": "去掉服务器启动代码或交互输入，改为直接执行核心逻辑并 print 结果",
            }
        return {
            "category": "timeout_slow",
            "message": "运行超时 — 算法可能过慢或数据量太大",
            "suggestion": "优化算法复杂度，或减小测试数据规模用 print 验证正确性",
        }

    # Compile error
    compile_markers = [
        "SyntaxError", "编译错误", "javac:", "gcc:", "g++:",
        "error:", "错误:", "class, interface", "需要 class",
        "找不到符号", "illegal", "unexpected",
    ]
    if any(m in output for m in compile_markers):
        return {
            "category": "compile_error",
            "message": "编译/语法错误",
            "suggestion": "修复代码语法错误，确保语言版本兼容",
        }

    # Missing module — extract module name if possible
    missing_markers = [
        "ModuleNotFoundError", "ImportError", "No module named",
        "找不到模块", "cannot import",
    ]
    if any(m in output for m in missing_markers):
        import re
        mod_match = re.search(r"No module named ['\"](\w+)['\"]", output)
        mod_name = mod_match.group(1) if mod_match else "未知模块"
        return {
            "category": "missing_module",
            "message": f"缺少模块: {mod_name}",
            "suggestion": f"用 Python 标准库替代 {mod_name}，或去掉该 import 重写功能",
            "module_name": mod_name,
        }

    # Runtime exception
    return {
        "category": "runtime_exception",
        "message": "运行时异常",
        "suggestion": "检查代码逻辑、边界条件和输入处理",
    }

