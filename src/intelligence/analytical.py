# =============================================================================
# Analytical Reasoning Engine (Phase 29)
# =============================================================================
# Research plans para why/causal; decompose; driver_analysis; causality
# always not_established unless evidence marks causal. Budget via LoopGuard.
# =============================================================================
from __future__ import annotations

import re
from typing import Any

from src.core.domain.intelligence import ToolFingerprint
from src.core.domain.research import ResearchBudgets, ResearchPlan, ResearchStep
from src.intelligence.loop_guard import LoopGuard

_WHY_RE = re.compile(
    r"\b(por\s+qu[eé]|porque|why|causa|raz[oó]n|driver|ca[ií]d|bajaron|"
    r"subieron|variaci[oó]n|variance)\b",
    re.IGNORECASE,
)

_DEFAULT_WHY_STEPS: list[tuple[str, str]] = [
    ("Calculate total metric variation", "period_comparison"),
    ("Break down by region", "dimension_decomposition"),
    ("Break down by channel", "dimension_decomposition"),
    ("Break down by product", "dimension_decomposition"),
    ("Separate price vs volume effects", "variance"),
    ("Inspect refunds / returns", "top_contributors"),
    ("Search relevant incidents/documents", "inspect"),
    ("Rank largest drivers", "top_contributors"),
    ("Validate evidence", "validate"),
    ("Produce explanation", "explain"),
]


class AnalyticalReasoningEngine:
    """Motor de razonamiento analítico con Research Plan acotado."""

    def __init__(
        self,
        *,
        budgets: ResearchBudgets | None = None,
        loop_guard: LoopGuard | None = None,
    ) -> None:
        self.budgets = budgets or ResearchBudgets()
        self.loop_guard = loop_guard or LoopGuard()

    def is_analytical_question(self, question: str) -> bool:
        return bool(_WHY_RE.search(question or ""))

    def build_research_plan(self, question: str) -> ResearchPlan:
        """Plan para preguntas causales / why; respeta max_steps."""
        steps: list[ResearchStep] = []
        for name, op in _DEFAULT_WHY_STEPS:
            if len(steps) >= self.budgets.max_steps:
                break
            steps.append(ResearchStep(name=name, operation=op))
        plan = ResearchPlan(question=question, steps=steps, budgets=self.budgets)
        # LoopGuard-style budget check fingerprint
        fp = ToolFingerprint.compute(
            tool="analytical_research_plan",
            source=None,
            arguments={"q": question.strip().lower()[:200]},
            query=question,
            agent_id=None,
            organization_id="system",
        )
        allowed = self.loop_guard.check(fp, observation_context=f"steps={len(steps)}")
        if not allowed:
            plan.steps = plan.steps[:1]
            if plan.steps:
                plan.steps[0].result = {"blocked": "loop_guard"}
        return plan

    def decompose(self, question: str) -> list[dict[str, Any]]:
        """Operaciones de descomposición analítica inicial."""
        ops = [
            "period_comparison",
            "variance",
            "dimension_decomposition",
            "top_contributors",
        ]
        if re.search(r"\bprecio|price|volumen|volume\b", question or "", re.I):
            ops.append("price_volume")
        if re.search(r"\bsegmento|cohort|cohorte\b", question or "", re.I):
            ops.append("segment_comparison")
        return [{"operation": op, "status": "PENDING"} for op in ops]

    def driver_analysis(
        self,
        total_delta: float,
        contributions: list[dict[str, Any]],
        *,
        causal_evidence: bool = False,
    ) -> dict[str, Any]:
        """Contribution shares; causality not_established unless evidence says so."""
        total_abs = sum(abs(float(c.get("delta", 0.0))) for c in contributions) or 1.0
        ranked: list[dict[str, Any]] = []
        for c in contributions:
            delta = float(c.get("delta", 0.0))
            share = delta / total_abs if total_delta == 0 else delta / abs(total_delta or 1.0)
            # Prefer share of absolute contribution mass
            share_of_abs = abs(delta) / total_abs
            ranked.append(
                {
                    "name": c.get("name") or c.get("dimension") or "other",
                    "delta": delta,
                    "contribution_share": round(share_of_abs * (1 if delta >= 0 else -1), 4),
                    "share_abs": round(share_of_abs, 4),
                }
            )
        ranked.sort(key=lambda r: abs(r["delta"]), reverse=True)
        return {
            "total_delta": total_delta,
            "primary_drivers": ranked[:3],
            "secondary_drivers": ranked[3:],
            "causality": "established" if causal_evidence else "not_established",
            "limitations": []
            if causal_evidence
            else [
                "Correlación temporal no implica causalidad sin evidencia causal explícita."
            ],
        }

    def can_execute_step(self, plan: ResearchPlan, step_name: str) -> bool:
        """True si el presupuesto y LoopGuard permiten el paso."""
        if plan.budget_exceeded():
            return False
        if plan.steps_executed >= plan.budgets.max_steps:
            return False
        fp = ToolFingerprint.compute(
            tool="analytical_step",
            source=None,
            arguments={"plan": str(plan.id), "step": step_name},
            query=plan.question,
            agent_id=None,
            organization_id="system",
        )
        return self.loop_guard.check(
            fp, observation_context=f"executed={plan.steps_executed}"
        )
