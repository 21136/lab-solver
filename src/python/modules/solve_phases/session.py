"""V4 solve pipeline session state (IR-20)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

PhaseCallback = Callable[[dict[str, Any]], None]


@dataclass
class SolveSession:
    session_id: str = ""
    pipeline_version: str = "v4"
    brief: dict = field(default_factory=dict)
    code_files: list = field(default_factory=list)
    main_file: str = ""
    language: str = "python"
    run_result: dict | None = None
    code_attempts: int = 0
    code_status: str = "pending"  # pending | verified | degraded | skipped
    steps_analysis: str = ""
    result_description: str = ""
    expected_output: str = ""
    summary: str = ""
    notes: str = ""
    diagrams: list = field(default_factory=list)
    constraints_applied: list = field(default_factory=list)
    quality_tier: str = "standard"
    phases: list = field(default_factory=list)
    total_llm_calls: int = 0
    prompt_versions: dict = field(default_factory=dict)

    def to_solve_lab_data(self, *, answer: str = "") -> dict[str, Any]:
        code_single = ""
        if self.code_files:
            for f in self.code_files:
                if f.get("name") == self.main_file or not code_single:
                    code_single = f.get("code") or f.get("content") or ""
        parsed = {
            "language": self.language,
            "steps_analysis": self.steps_analysis,
            "result_description": self.result_description,
            "expected_output": self.expected_output,
            "summary": self.summary,
            "notes": self.notes,
            "code": code_single,
            "code_files": self.code_files,
            "main_file": self.main_file,
            "diagrams": self.diagrams,
        }
        return {
            "answer": answer,
            "code": code_single,
            "code_files": self.code_files,
            "main_file": self.main_file,
            "language": self.language,
            "type": "lab_report",
            "parsed": parsed,
            "pipeline_meta": {
                "version": self.pipeline_version,
                "tier": self.quality_tier,
                "phases": self.phases,
                "code_status": self.code_status,
                "total_llm_calls": self.total_llm_calls,
                "constraints_applied": self.constraints_applied,
                "prompt_versions": dict(self.prompt_versions),
            },
            "solve_session": asdict(self),
        }


def session_from_dict(data: dict) -> SolveSession:
    """Rebuild SolveSession from solve_session dict (retry-validation)."""
    fields = SolveSession.__dataclass_fields__
    kwargs = {k: data[k] for k in fields if k in data}
    return SolveSession(**kwargs)
