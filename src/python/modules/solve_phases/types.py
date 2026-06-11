"""IR-19: Solve pipeline phase contracts (context + result types)."""



from __future__ import annotations



from dataclasses import dataclass, field

from typing import Any, Protocol



from modules.java_jars import JarConsentCallback

from modules.solve_phases.session import PhaseCallback, SolveSession





@dataclass

class SolvePhaseContext:

    """Inputs shared across V4 solve phases."""



    settings: dict

    question: dict

    session: SolveSession

    constraints: list[str] = field(default_factory=list)

    limits: dict[str, Any] | None = None

    on_phase: PhaseCallback | None = None

    on_jar_consent: JarConsentCallback | None = None

    approved_jar_ids: list[str] | None = None

    skip_run: bool = False





@dataclass

class SolvePhaseResult:

    """Outcome of a single phase invocation (for contract tests / IR-20 orchestration)."""



    phase_id: str

    status: str

    llm_calls: int = 0





class SolvePhase(Protocol):

    def run(self, ctx: SolvePhaseContext) -> SolvePhaseResult: ...





def last_phase_record(session: SolveSession, phase_id: str) -> dict[str, Any] | None:

    for rec in reversed(session.phases):

        if rec.get("id") == phase_id:

            return rec

    return None

