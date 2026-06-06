"""
Agent core types (Phase 1.3 — fields frozen for Phase 2a extension).

See docs/architecture/LAB_SOLVER_AGENT_PLAN.md appendix C.
"""

from typing import Any, NotRequired, TypedDict

AGENT_SCHEMA_VERSION = 1

# Module IDs the agent may reference — sourced from registry (V3-1).
from agent.registry import known_module_ids

KNOWN_MODULE_IDS = known_module_ids()

# V5-4: experimental fill must not block deliverable / answer workspace.
NON_BLOCKING_MODULES = frozenset({"fill_report"})


def is_non_blocking_module(module: str) -> bool:
    return module in NON_BLOCKING_MODULES


class ChatResult(TypedDict, total=False):
    content: str
    reasoning_content: str
    phase: str
    finish_reason: str
    usage: dict[str, Any]


class DecisionLogEntry(TypedDict, total=False):
    timestamp: str
    agent: str
    decision: str
    target: str
    reason: str
    evidence: str
    fingerprint: str
    overridden: bool


class ModuleResult(TypedDict, total=False):
    ok: bool
    data: dict[str, Any]
    logs: list[str]
    fingerprint: str
    sub_fingerprints: dict[str, str]
    cacheable: bool


class PlanStep(TypedDict, total=False):
    module: str
    params: dict[str, Any]
    reason: str
    evidence: str
    source: str
    confidence: str
    default_checked: bool


class PlanResult(TypedDict, total=False):
    steps: list[PlanStep]
    plan_fingerprint: str
    clarifications: list[dict[str, Any]]
    prompt_version: str
    decision_log: list[DecisionLogEntry]


class AgentContext(TypedDict, total=False):
    """Session state carried through plan → run (2a). Phase 1 defines core slots only."""

    schema_version: int
    run_id: NotRequired[str]

    # Single-document inputs (Phase 1.3)
    report_text: str
    metadata: dict[str, Any]
    question: dict[str, Any]

    settings: dict[str, Any]
    user_profile: dict[str, Any]
    format_spec: NotRequired[dict[str, Any]]
    prompt_versions: dict[str, str]

    # Plan / execution (2a+)
    plan: PlanResult
    confirmed_steps: list[PlanStep]
    module_results: dict[str, ModuleResult]
    dirty_modules: list[str]
    dirty_fields: dict[str, list[str]]
    fill_sections: list[str]

    decision_log: list[DecisionLogEntry]
    consecutive_failures: int
