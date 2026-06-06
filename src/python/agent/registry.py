"""
Unified module registry (V3-1).

Single source for planner catalog, known module IDs, and ReAct tool schemas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    description: str
    planner_visible: bool
    react_alias: str | None
    react_description: str | None
    react_params: tuple[str, ...]
    runner: str  # "executor" = delegate to executor._MODULE_RUNNERS; "" = no runner


def _build_registry() -> dict[str, ModuleSpec]:
    specs: list[ModuleSpec] = [
        ModuleSpec(
            id="parse_report",
            description="解析上传的实验报告文档",
            planner_visible=False,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="",
        ),
        ModuleSpec(
            id="solve_lab",
            description="生成实验报告答案（含步骤分析、代码等）",
            planner_visible=True,
            react_alias="solve_lab",
            react_description=(
                "生成实验报告答案（含步骤分析、结果说明、总结、代码）。"
                "参数 language 指定编程语言（python/java/c/cpp/javascript），"
                "include_uml 为 true 时同时生成 UML 图。"
            ),
            react_params=("language", "include_uml"),
            runner="executor",
        ),
        ModuleSpec(
            id="solve_theory",
            description="解答理论/简答题",
            planner_visible=True,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="run_code",
            description="编译并运行 solve_lab 生成的代码",
            planner_visible=True,
            react_alias="run_code",
            react_description="编译并运行上次 solve_lab 生成的代码，返回终端输出或错误信息。无需参数。",
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="fix_code",
            description="根据 run_code 错误自动修复代码",
            planner_visible=False,
            react_alias="fix_code",
            react_description=(
                "LLM 根据上次 run_code 的编译/运行错误自动修复代码。"
                "可选参数 error 提供错误信息（不传则从 run_code 结果自动获取）。"
                "修复后需再次调用 run_code 验证。"
            ),
            react_params=("error",),
            runner="executor",
        ),
        ModuleSpec(
            id="screenshot_ide",
            description="生成 IDE 风格代码截图",
            planner_visible=True,
            react_alias="screenshot",
            react_description="生成 IDE 风格代码截图（含代码+终端输出），用于插入实验报告。无需参数。",
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="screenshot_terminal",
            description="生成终端风格截图",
            planner_visible=True,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="render_uml",
            description="渲染 UML 图",
            planner_visible=True,
            react_alias="render_uml",
            react_description=(
                "渲染 UML 图（类图/时序图/用例图等）。"
                "仅在 solve_lab 返回了 diagrams 数组时调用。无需参数。"
            ),
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="fix_diagrams",
            description="根据验错结果 LLM 修复 diagrams",
            planner_visible=False,
            react_alias="fix_diagrams",
            react_description=(
                "当 render_uml 失败或图表 schema/一致性校验未通过时，"
                "根据验错信息修正 diagrams（PlantUML / dfd_json）。"
                "修复后应再次 render_uml。"
            ),
            react_params=("feedback",),
            runner="executor",
        ),
        ModuleSpec(
            id="present_deliverable",
            description="汇编答案交付物（分节内容、代码、图表）",
            planner_visible=True,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="fill_report",
            description="【高级/实验性】尝试填入 Word 模版",
            planner_visible=False,
            react_alias="fill_report",
            react_description="【实验性】将答案填入 Word；不保证版式，建议以复制粘贴为主。无需参数。",
            react_params=(),
            runner="executor",
        ),
        ModuleSpec(
            id="parse_answer_template",
            description="解析答题卡/答案模板",
            planner_visible=False,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="",
        ),
        ModuleSpec(
            id="verify_answer",
            description="规则校验答案完整性",
            planner_visible=False,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="",
        ),
        ModuleSpec(
            id="preflight",
            description="代码执行前环境预检",
            planner_visible=False,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="",
        ),
        ModuleSpec(
            id="revise_answer",
            description="根据反馈修订答案",
            planner_visible=False,
            react_alias=None,
            react_description=None,
            react_params=(),
            runner="",
        ),
        ModuleSpec(
            id="finalize_report",
            description="一键完成 UML → 截图 → 填表",
            planner_visible=False,
            react_alias="finalize_report",
            react_description=(
                "一键完成：渲染 UML（若有）→ 截图 → 填入 Word。"
                "当 run_code 反复失败或接近轮次上限时优先调用，不要继续 fix_code。"
            ),
            react_params=(),
            runner="",
        ),
    ]
    return {s.id: s for s in specs}


MODULE_REGISTRY: dict[str, ModuleSpec] = _build_registry()

_REACT_ALIAS_INDEX: dict[str, str] = {
    s.react_alias: s.id for s in MODULE_REGISTRY.values() if s.react_alias
}


def planner_module_catalog() -> frozenset[str]:
    """Module IDs visible to planner / understand_plan prompts."""
    return frozenset(s.id for s in MODULE_REGISTRY.values() if s.planner_visible)


def known_module_ids() -> frozenset[str]:
    """All registered module IDs (types.KNOWN_MODULE_IDS replacement)."""
    return frozenset(MODULE_REGISTRY.keys())


def react_tool_schemas() -> dict[str, dict[str, Any]]:
    """ReAct tool schemas keyed by action alias (react_tools.REACT_TOOL_SCHEMAS)."""
    out: dict[str, dict[str, Any]] = {}
    for spec in MODULE_REGISTRY.values():
        if not spec.react_alias:
            continue
        out[spec.react_alias] = {
            "description": spec.react_description or spec.description,
            "params": list(spec.react_params),
            "module": spec.id,
        }
    return out


def react_action_to_module(action: str) -> str:
    """Map a ReAct action name to an executor module id."""
    return _REACT_ALIAS_INDEX.get((action or "").strip().lower(), "")


def get_runner(module_id: str) -> Callable[..., Any] | None:
    """Return the executor runner for a module, or None."""
    spec = MODULE_REGISTRY.get(module_id)
    if not spec or spec.runner != "executor":
        return None
    from agent.executor import _MODULE_RUNNERS

    return _MODULE_RUNNERS.get(module_id)
