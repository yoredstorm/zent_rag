# =============================================================================
# Finite Execution State Machine — elimina loops indefinidos
# =============================================================================
# Estados: UNDERSTAND -> PLAN -> RESOLVE_CONTEXT -> RETRIEVE -> EXECUTE ->
# VALIDATE -> ANSWER | ABSTAIN -> DONE. Transiciones válidas verificadas en
# cada paso; presupuesto (Budget) con límites duros por ejecución.
# =============================================================================
from __future__ import annotations

from enum import StrEnum

from src.core.domain.intelligence import Budget, BudgetLimits


class IntelligenceState(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    RESOLVE_CONTEXT = "RESOLVE_CONTEXT"
    RETRIEVE = "RETRIEVE"
    EXECUTE = "EXECUTE"
    VALIDATE = "VALIDATE"
    ANSWER = "ANSWER"
    ABSTAIN = "ABSTAIN"
    DONE = "DONE"


# Transiciones válidas del FSM (fallo de transición = bug, no loop).
_TRANSITIONS: dict[IntelligenceState, frozenset[IntelligenceState]] = {
    IntelligenceState.UNDERSTAND: frozenset(
        {IntelligenceState.PLAN, IntelligenceState.DONE}
    ),
    IntelligenceState.PLAN: frozenset(
        {
            IntelligenceState.RESOLVE_CONTEXT,
            IntelligenceState.RETRIEVE,
            IntelligenceState.EXECUTE,
            IntelligenceState.ANSWER,
            IntelligenceState.ABSTAIN,
            IntelligenceState.DONE,
        }
    ),
    IntelligenceState.RESOLVE_CONTEXT: frozenset(
        {IntelligenceState.RETRIEVE, IntelligenceState.EXECUTE, IntelligenceState.DONE}
    ),
    IntelligenceState.RETRIEVE: frozenset(
        {IntelligenceState.EXECUTE, IntelligenceState.VALIDATE, IntelligenceState.DONE}
    ),
    IntelligenceState.EXECUTE: frozenset(
        {IntelligenceState.VALIDATE, IntelligenceState.DONE}
    ),
    IntelligenceState.VALIDATE: frozenset(
        {IntelligenceState.ANSWER, IntelligenceState.ABSTAIN, IntelligenceState.DONE}
    ),
    IntelligenceState.ANSWER: frozenset({IntelligenceState.DONE}),
    IntelligenceState.ABSTAIN: frozenset({IntelligenceState.DONE}),
    IntelligenceState.DONE: frozenset(),
}


class FSMViolation(RuntimeError):
    """Transición inválida en la máquina de estados de ejecución."""


class IntelligenceStateMachine:
    """Máquina de estados finita + presupuesto duro por ejecución."""

    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self._state = IntelligenceState.UNDERSTAND
        self.budget = Budget(limits=limits or BudgetLimits())
        self._history: list[str] = [self._state.value]

    @property
    def state(self) -> IntelligenceState:
        return self._state

    @property
    def history(self) -> list[str]:
        return list(self._history)

    def transition(self, new_state: IntelligenceState) -> IntelligenceState:
        """Mueve el FSM validando la transición; lanza FSMViolation si es inválida."""
        if self._state == IntelligenceState.DONE:
            raise FSMViolation(f"Cannot transition from DONE to {new_state.value}")
        allowed = _TRANSITIONS[self._state]
        if new_state not in allowed:
            raise FSMViolation(
                f"Invalid transition {self._state.value} -> {new_state.value}"
            )
        self._state = new_state
        self._history.append(new_state.value)
        return new_state

    def check_budget(self) -> str | None:
        """Retorna el límite excedido (None = presupuesto válido)."""
        return self.budget.exceeded

    def record_llm_call(self, tokens: int = 0, cost: float = 0.0) -> None:
        self.budget.record_llm_call(tokens=tokens, cost=cost)

    def record_tool_call(self) -> None:
        self.budget.record_tool_call()

    def record_retrieval(self) -> None:
        self.budget.record_retrieval()

    def record_plan_attempt(self) -> None:
        self.budget.record_plan_attempt()

    def record_sql_repair(self) -> None:
        self.budget.record_sql_repair()

    def snapshot(self) -> dict:
        return {
            "state": self._state.value,
            "history": self._history,
            "budget": self.budget.to_dict(),
        }
