"""
IR-22: Declarative post-LLM plan rule chain.

Each PlanRule has an id, optional applies(ctx), and transform(steps, ctx).
Rules run in registration order; ``replaces_all`` stops the chain after apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agent.types import PlanStep

TransformFn = Callable[[list[PlanStep], "PlanRuleContext"], list[PlanStep]]
AppliesFn = Callable[["PlanRuleContext"], bool]


@dataclass
class PlanRuleContext:
    settings: dict | None = None
    report_text: str = ""
    metadata: dict | None = None
    constraints: list[str] | None = None
    profile: dict | None = None
    question_type: str = ""


@dataclass(frozen=True)
class PlanRule:
    id: str
    description: str
    transform: TransformFn
    applies: AppliesFn | None = None
    replaces_all: bool = False


@dataclass
class PlanRuleResult:
    steps: list[PlanStep]
    rules_applied: list[str] = field(default_factory=list)


def _always(_ctx: PlanRuleContext) -> bool:
    return True


def _apply_rule(
    steps: list[PlanStep],
    ctx: PlanRuleContext,
    rule: PlanRule,
) -> tuple[list[PlanStep], bool]:
    if rule.applies is not None and not rule.applies(ctx):
        return steps, False
    return rule.transform(list(steps), ctx), True


def apply_plan_rules(
    steps: list[PlanStep],
    ctx: PlanRuleContext,
    rules: list[PlanRule],
    *,
    stop_on_replaces_all: bool = True,
) -> PlanRuleResult:
    """Run rules in order; return transformed steps and applied rule ids."""
    current = list(steps)
    applied: list[str] = []
    for rule in rules:
        current, did = _apply_rule(current, ctx, rule)
        if did:
            applied.append(rule.id)
            if stop_on_replaces_all and rule.replaces_all:
                break
    return PlanRuleResult(steps=current, rules_applied=applied)


def _transform_v4_pipeline(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_for_v4_pipeline

    return adjust_plan_for_v4_pipeline(steps, ctx.settings)


def _transform_skip_validation(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_for_skip_validation

    return adjust_plan_for_skip_validation(steps, ctx.constraints)


def _transform_theory_only(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_theory_only

    return adjust_plan_theory_only(steps, ctx.report_text)


def _transform_enrich_low_confidence(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import enrich_low_confidence_steps

    return enrich_low_confidence_steps(steps)


def _transform_mixed_assignment(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_for_mixed_assignment

    return adjust_plan_for_mixed_assignment(steps, metadata=ctx.metadata)


def _transform_code_cloze(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_for_code_cloze

    return adjust_plan_for_code_cloze(steps, metadata=ctx.metadata)


def _transform_short_answer(steps: list[PlanStep], ctx: PlanRuleContext) -> list[PlanStep]:
    from agent.planner import adjust_plan_for_short_answer

    return adjust_plan_for_short_answer(steps, metadata=ctx.metadata)


def _applies_mixed(ctx: PlanRuleContext) -> bool:
    meta = ctx.metadata or {}
    return bool(meta.get("mixed_assignment")) and len(meta.get("assignment_questions") or []) >= 2


def _applies_code_cloze(ctx: PlanRuleContext) -> bool:
    meta = ctx.metadata or {}
    if meta.get("mixed_assignment"):
        return False
    q_type = (ctx.question_type or meta.get("question_type") or "").strip().lower()
    cloze = meta.get("code_cloze") or {}
    return q_type == "code_cloze" or bool(cloze.get("is_code_cloze"))


def _applies_short_answer(ctx: PlanRuleContext) -> bool:
    meta = ctx.metadata or {}
    if meta.get("mixed_assignment"):
        return False
    q_type = (ctx.question_type or meta.get("question_type") or "").strip().lower()
    return q_type == "short_answer"


# Post-LLM chain in plan_from_report (after behavior, before fingerprint).
POST_LLM_PLAN_RULES: list[PlanRule] = [
    PlanRule("v4_pipeline_demote_run_code", "V4 solve_lab 内化验证后降级 run_code", _transform_v4_pipeline),
    PlanRule("skip_validation", "用户 skip_validation 约束移除 run_code", _transform_skip_validation),
    PlanRule("theory_only", "纯理论题移除 run_code/render_uml", _transform_theory_only),
    PlanRule("enrich_low_confidence", "低置信步骤默认不勾选", _transform_enrich_low_confidence),
    PlanRule(
        "mixed_assignment",
        "混排卷按题序生成 solve 步骤",
        _transform_mixed_assignment,
        applies=_applies_mixed,
        replaces_all=True,
    ),
    PlanRule(
        "code_cloze",
        "代码完形填空仅保留 cloze + deliverable",
        _transform_code_cloze,
        applies=_applies_code_cloze,
    ),
]

# Server-side question_type overrides (mutually exclusive branches).
QUESTION_TYPE_OVERRIDE_RULES: list[PlanRule] = [
    PlanRule(
        "mixed_assignment",
        "混排卷覆盖计划",
        _transform_mixed_assignment,
        applies=_applies_mixed,
        replaces_all=True,
    ),
    PlanRule(
        "code_cloze",
        "代码完形填空覆盖计划",
        _transform_code_cloze,
        applies=_applies_code_cloze,
        replaces_all=True,
    ),
    PlanRule(
        "short_answer",
        "纯简答题覆盖计划",
        _transform_short_answer,
        applies=_applies_short_answer,
        replaces_all=True,
    ),
]


def apply_post_llm_plan_rules(
    steps: list[PlanStep],
    *,
    settings: dict | None,
    report_text: str,
    metadata: dict | None = None,
    constraints: list[str] | None = None,
) -> PlanRuleResult:
    ctx = PlanRuleContext(
        settings=settings,
        report_text=report_text,
        metadata=metadata,
        constraints=constraints,
    )
    return apply_plan_rules(steps, ctx, POST_LLM_PLAN_RULES, stop_on_replaces_all=False)


def apply_question_type_plan_rules(
    steps: list[PlanStep],
    *,
    metadata: dict | None,
    question_type: str = "",
) -> PlanRuleResult:
    ctx = PlanRuleContext(metadata=metadata, question_type=question_type)
    return apply_plan_rules(steps, ctx, QUESTION_TYPE_OVERRIDE_RULES)
