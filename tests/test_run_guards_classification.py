# =============================================================================
# Clasificación de RunGuards (P1-G) — el flag no abre un hueco de seguridad.
# =============================================================================
# Contrato:
#   * cada reason_code emitible por la tabla declara su clase (SECURITY /
#     CORRECTNESS / RESOURCE / QUALITY / EXPERIMENTAL);
#   * SECURITY/CORRECTNESS duplican una autoridad canónica que corre SIEMPRE
#     (registro de tools, política del cierre): `RUNTIME_RUN_GUARDS_ENFORCE=off`
#     deja el veredicto advisory sin debilitar la autoridad;
#   * RESOURCE respeta la autoridad canónica de `RunBudgetLedger`;
#   * QUALITY/EXPERIMENTAL pueden quedar advisory por diseño.
#
# La reclasificación de P1-5 (`RUNTIME_RUN_GUARDS_ENFORCE=off`) se sostiene con
# evidencia behavioral de abajo, no con la etiqueta.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.reason_codes import is_known_reason_code
from src.runtime.run_guards import (
    ADVISORY_CLASSES,
    GUARD_CANONICAL_ENFORCER,
    GUARD_CLASS,
    GuardClass,
    RunEvent,
    evaluate_transition,
    guard_class,
    requires_guard_enforcement,
)
from src.runtime.run_state import RunPhase

#: Barrido de señales que cubre TODAS las ramas de `evaluate_transition`.
_VARIANTS: tuple[dict, ...] = (
    {},
    {"tool_authorized": True},
    {"tool_authorized": True, "duplicate_tool_call": True},
    {"tool_authorized": True, "budget_exhausted": True},
    {"budget_exhausted": True},
    {"requires_deterministic": True, "authority_present": False},
    {"requires_deterministic": True, "authority_present": True},
    {"analysis_incomplete": True},
    {"evidence_available": True, "budget_exhausted": True},
    {"tool_failure": "transient"},
    {"tool_failure": "permanent"},
)


def _emitted_codes() -> set[str]:
    codes: set[str] = set()
    phases = [RunPhase.CREATED, RunPhase.REASONING, RunPhase.READY_TO_FINALIZE]
    for phase in phases:
        for event in RunEvent:
            for variant in _VARIANTS:
                verdict = evaluate_transition(phase, event, **variant)
                codes.add(str(verdict.reason_code))
    # Terminal: único veredicto.
    codes.add(str(evaluate_transition(RunPhase.FINALIZED, RunEvent.REQUEST_TOOL).reason_code))
    return codes


def test_todo_veredicto_emitible_tiene_clase() -> None:
    codes = _emitted_codes()
    assert codes, "el barrido no emitió veredictos"
    missing = sorted(code for code in codes if guard_class(code) is None)
    assert not missing, f"reason codes sin clase de guard (P1-G): {missing}"
    unknown = sorted(code for code in GUARD_CLASS if not is_known_reason_code(code))
    assert not unknown, f"la tabla de clases usa códigos fuera del catálogo: {unknown}"


def test_security_y_correctness_declaran_autoridad_canonica() -> None:
    for code, klass in GUARD_CLASS.items():
        if klass in ADVISORY_CLASSES:
            assert GUARD_CANONICAL_ENFORCER[klass] == ""
            continue
        assert GUARD_CANONICAL_ENFORCER[klass], (
            f"{code}: clase {klass} sin autoridad canónica declarada"
        )
        assert requires_guard_enforcement(code) is False, code


def test_autoridades_canonicas_declaradas_existen() -> None:
    """La autoridad que reemplaza al guard debe existir como símbolo real."""
    import importlib

    expected = {
        GuardClass.SECURITY: [
            ("src.agents.tools.registry", "tool_allowed"),
            ("src.runtime.finalization_policy", "resolve_closure_phase"),
        ],
        GuardClass.CORRECTNESS: [
            ("src.runtime.finalization_policy", "resolve_closure_phase"),
        ],
        GuardClass.RESOURCE: [("src.runtime.run_budget", "RunBudgetLedger")],
    }
    for klass, symbols in expected.items():
        for module_name, symbol in symbols:
            module = importlib.import_module(module_name)
            assert hasattr(module, symbol), f"{module_name}.{symbol} no existe"
            assert symbol in GUARD_CANONICAL_ENFORCER[klass]


def test_guards_off_no_desarma_la_autoridad_del_cierre() -> None:
    """Behavioral: sin guards, el cierre sigue fail-closed por autoridad.

    `REQUEST_FINALIZE` con autoridad determinista requerida y ausente resuelve
    UNDETERMINED en la tabla; con el flag off, quien aplica el bloqueo es la
    política del cierre (`resolve_closure_phase`), que corre siempre.
    """
    from src.runtime.run_state import AgentRunState, RunIdentity, finalize_state

    state = AgentRunState(identity=RunIdentity(run_id="guards-off"))
    state.decisions.requires_deterministic = True
    violations = finalize_state(
        state, status="completed", answer="MATCH", answer_state=None
    )
    assert state.phase is RunPhase.UNDETERMINED
    assert any(v.startswith("closure_authority_mismatch") for v in violations)
    # El guard solo habría sido un duplicado de esta misma decisión.
    verdict = evaluate_transition(
        RunPhase.REASONING,
        RunEvent.REQUEST_FINALIZE,
        requires_deterministic=True,
        authority_present=False,
    )
    assert verdict.to_phase is RunPhase.UNDETERMINED
    assert guard_class(verdict.reason_code) is GuardClass.SECURITY


def test_guards_off_no_desarma_el_ledger_de_presupuesto() -> None:
    """RESOURCE: la autoridad es `RunBudgetLedger`, no el flag de guards."""
    from src.runtime.run_state import AgentRunState, RunIdentity

    state = AgentRunState(identity=RunIdentity(run_id="budget-guard"))
    state.budget.ledger = SimpleNamespace(remaining_tokens=0, remaining_cost_usd=None)
    assert state.budget.note_expensive_call("llm") is False
    verdict = evaluate_transition(
        RunPhase.REASONING,
        RunEvent.REQUEST_TOOL,
        tool_authorized=True,
        budget_exhausted=True,
    )
    assert verdict.allowed is False
    assert guard_class(verdict.reason_code) is GuardClass.RESOURCE


def test_quality_puede_quedar_advisory() -> None:
    verdict = evaluate_transition(
        RunPhase.REASONING,
        RunEvent.OBSERVE_TOOL_RESULT,
        tool_failure="permanent",
    )
    assert verdict.allowed is False
    klass = guard_class(verdict.reason_code)
    assert klass in ADVISORY_CLASSES
    assert GUARD_CANONICAL_ENFORCER[klass] == ""
