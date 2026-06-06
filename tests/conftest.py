"""Shared pytest setup: add src/python to sys.path for all tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SRC = ROOT / "src" / "python"
src = str(PYTHON_SRC)
if src not in sys.path:
    sys.path.insert(0, src)
