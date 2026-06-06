"""
Verify Python backend imports (packaging smoke test).

Usage:
  python tests/verify_imports.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SRC = ROOT / "src" / "python"


def main():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(PYTHON_SRC)!r}); "
            "from modules import parse_report, solve_lab, run_code; "
            "from llm_client import call_ai, get_llm_call_count, reset_llm_call_count; "
            "from agent import prompts; "
            "from agent.planner import plan_from_report; "
            "from agent.executor import start_run_async; "
            "from agent.prompt_budget import fit_budget; "
            "from agent.types import AgentContext, ModuleResult; "
            "from settings_schema import SETTINGS_SCHEMA_VERSION; "
            "assert SETTINGS_SCHEMA_VERSION >= 1; "
            "print('imports_ok schema_version=' + str(SETTINGS_SCHEMA_VERSION))",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    print(proc.stdout.strip())
    print("verify_imports: OK")


if __name__ == "__main__":
    main()
