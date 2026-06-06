"""Agent orchestration (planner Phase 1.3; executor Phase 2a.1)."""

from agent.planner import (
    compute_plan_fingerprint,
    make_agent_context,
    normalize_plan,
    parse_plan_json,
    plan_from_report,
    replan_incremental,
    replan_with_answers,
    verify_plan_fingerprint,
)
from agent.sections_config import normalize as normalize_sections_config
from agent.types import (
    AGENT_SCHEMA_VERSION,
    AgentContext,
    ChatResult,
    DecisionLogEntry,
    ModuleResult,
    PlanResult,
    PlanStep,
)

__all__ = [
    "AGENT_SCHEMA_VERSION",
    "AgentContext",
    "ChatResult",
    "DecisionLogEntry",
    "ModuleResult",
    "PlanResult",
    "PlanStep",
    "compute_plan_fingerprint",
    "make_agent_context",
    "normalize_plan",
    "parse_plan_json",
    "plan_from_report",
    "replan_incremental",
    "replan_with_answers",
    "normalize_sections_config",
    "verify_plan_fingerprint",
]
