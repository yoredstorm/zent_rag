# =============================================================================
# P1-F — el estado canónico refleja la autoridad mientras el run evoluciona.
# =============================================================================
# Contrato:
#   * un hecho de autoridad (regla determinista resuelta, envelope, autoridad
#     externa) se publica en `AgentRunState.decisions` en el EVENT BOUNDARY en
#     que se resuelve, no en la finalización;
#   * `AgentRunState.decisions` no almacena objetos temporales ni duplica la
#     verdad: envuelve la autoridad canónica y expone `authoritative`,
#     `external_authority`, `state` y si hay autorización ejecutable;
#   * un run observado ANTES de `finalize_state` ya declara su autoridad.
# =============================================================================
from __future__ import annotations

import re
from pathlib import Path

from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "src" / "agents" / "runtime" / "orchestrator.py"


def _state() -> AgentRunState:
    return AgentRunState(identity=RunIdentity(run_id="p1f"))


def test_estado_observable_antes_de_finalization() -> None:
    """Un run en vuelo ya representa autoridad, estado y fuente."""
    from types import SimpleNamespace

    state = _state()
    # Antes de resolver nada: sin autoridad, estado vacío.
    public = state.decisions.to_public_dict()
    assert public["authoritative"] is False
    assert public["state"] == ""
    assert public["external_authority"] is None

    envelope = SimpleNamespace(
        authoritative=True,
        state="MATCH",
        operation="COMPARISON",
        normalized_result="MATCH",
        to_public_dict=lambda: {
            "authoritative": True,
            "state": "MATCH",
            "operation": "COMPARISON",
            "result": "MATCH",
        },
    )
    state.decisions.set_envelope(envelope)
    state.decisions.observe_public_envelope(envelope.to_public_dict())

    # En vuelo (sin finalize_state): la autoridad vigente ya es consultable.
    state.try_advance(RunPhase.CLASSIFIED)
    public = state.decisions.to_public_dict()
    assert public["authoritative"] is True
    assert public["state"] == "MATCH"
    assert public["operation"] == "COMPARISON"
    assert state.terminal is False


def test_autoridad_externa_publicada_tambien_en_vuelo() -> None:
    state = _state()
    state.decisions.observe_external_authority("sql")
    public = state.decisions.to_public_dict()
    assert public["external_authority"] == "sql"
    assert public["authoritative"] is False


def test_orchestrator_publica_autoridad_en_el_boundary_de_resolucion() -> None:
    """Ratchet de orden: el envelope reconstruido se publica donde se resuelve.

    El patrón prohibido es el de P1-F: `authoritative_envelope = build(...)`
    seguido de uso (deterministic_mode) sin publicar en `run_state.decisions`.
    """
    text = ORCHESTRATOR.read_text(encoding="utf-8", errors="replace")
    assert "authoritative_envelope = build_decision_envelope(" in text
    anchor = text.index("authoritative_envelope = build_decision_envelope(")
    window = text[anchor : anchor + 1600]
    assert "run_state.decisions.set_envelope(authoritative_envelope)" in window, (
        "el envelope reconstruido no se publica en el boundary de resolución"
    )
    assert "observe_public_envelope" in window
    # La autoridad externa SQL se publica al resolverse el modo SQL-first.
    sql_anchor = text.index("sql_mode = sql_mode_from_result(")
    sql_window = text[sql_anchor : sql_anchor + 700]
    assert 'observe_external_authority("sql")' in sql_window, (
        "la autoridad SQL no se publica en el boundary en que se resuelve"
    )


def test_no_hay_escritura_directa_de_envelope_fuera_de_los_metodos() -> None:
    """Sin doble verdad: los campos de autoridad solo se escriben por métodos."""
    pattern = re.compile(
        r"\.decisions\.(envelope|envelope_public|finalized|external_authority)\s*=(?!=)"
    )
    offenders: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "escritura directa de campos de autoridad (usar observe_/set_): "
        f"{offenders}"
    )
