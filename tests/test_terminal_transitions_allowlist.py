# =============================================================================
# Allowlist de transiciones terminales fuera de FinalizationPolicy.
# =============================================================================
# Regla: una fase terminal es consecuencia de una resolución de autoridad.
# Los sitios de abajo son la lista CERRADA de transiciones terminales que no
# pasan por `finalization_policy`: cada uno con su justificación. Cualquier
# transición nueva rompe este test: se rutea por la política, o se agrega acá
# con justificación escrita.
#
# No son transiciones (no entran): comparaciones (`== RunPhase.FINALIZED`),
# claves de mapping (`RunPhase.FINALIZED: ...`) y membership en TERMINAL_PHASES.
#
# Desde el hardening de autoridad:
#   * `try_advance()` RECHAZA fases terminales (progreso no terminal únicamente);
#   * el aplicador único es `AgentRunState._apply_terminal`, invocado por
#     `finish(phase_override=<resolución>)` y por `apply_closure_override()`
#     (fail-closed post cierre, solo fases no-concluyentes);
#   * el segundo test de este archivo prohíbe asignaciones `.phase =` nuevas
#     fuera del aplicador canónico.
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_TERMINALS = "FINALIZED|ABSTAINED|BLOCKED|FAILED|LIMIT_REACHED|UNDETERMINED"
_TRANSITION_PATTERN = re.compile(
    rf"phase\s*=\s*RunPhase\.(?:{_TERMINALS})"  # asignación / kwarg (phase=, to_phase=)
    rf"|return\s+RunPhase\.(?:{_TERMINALS})"  # mapper status → fase
    rf"|\(RunPhase\.(?:{_TERMINALS})\)"  # argumento posicional
)

#: archivo -> [(snippet exacto, cantidad, justificación)].
ALLOWLIST: dict[str, list[tuple[str, int, str]]] = {
    "src/agents/runtime/agent_runtime.py": [
        (
            "phase=RunPhase.BLOCKED",
            2,
            "early return operativo (budget excedido / circuito abierto) antes "
            "del loop: no hay run que finalizar",
        ),
    ],
    "src/runtime/run_guards.py": [
        (
            "phase=RunPhase.UNDETERMINED",
            1,
            "tabla de guards: fail-closed ejecutable sin autoridad; el cierre "
            "real sigue resolviéndolo la política",
        ),
        (
            "phase=RunPhase.FINALIZED",
            2,
            "tabla de guards: REQUEST_FINALIZE permitido (evidencia / READY)",
        ),
    ],
    "src/runtime/run_state.py": [
        ("return RunPhase.FAILED", 1, "mapper único status → fase (oráculo)"),
        ("return RunPhase.LIMIT_REACHED", 1, "mapper único status → fase (oráculo)"),
        ("return RunPhase.BLOCKED", 3, "mapper único status → fase (oráculo)"),
        ("return RunPhase.ABSTAINED", 1, "mapper único status → fase (oráculo)"),
        ("return RunPhase.UNDETERMINED", 1, "mapper único status → fase (oráculo)"),
        ("return RunPhase.FINALIZED", 1, "mapper único status → fase (oráculo)"),
    ],
    "src/runtime/finalization_policy.py": [
        (
            "phase=RunPhase.FAILED",
            1,
            "resolución de fallo de la autoridad del cierre "
            "(`closure_authority_failure`): declara FAILED, no transiciona; el "
            "aplicador único sigue siendo finish(phase_override=...). Fail-closed: "
            "un fallo del reducer no reabre la heurística legacy.",
        ),
        (
            "return RunPhase.ABSTAINED",
            1,
            "reducer del cierre: la resolución DECLARA la fase del veto por "
            "conflicto de fuentes. No muta el run: el aplicador único sigue "
            "siendo finish(phase_override=...).",
        ),
        (
            "return RunPhase.UNDETERMINED",
            1,
            "reducer del cierre: veto por conflicto de reglas (misma razón: "
            "declara la resolución, no transiciona el run).",
        ),
        (
            "phase=RunPhase.BLOCKED",
            2,
            "reducer del cierre: valor de la resolución en los branches de "
            "fallo operativo y de cierre no autorizado (autoridad, no "
            "transición).",
        ),
    ],
}


def _found_transitions() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        matches = [m.group(0) for m in _TRANSITION_PATTERN.finditer(text)]
        if matches:
            found[str(path.relative_to(ROOT)).replace("\\", "/")] = matches
    return found


def test_solo_los_sitios_allowlisted() -> None:
    found = _found_transitions()
    expected = {
        rel: [snippet for snippet, count, _ in entries for _ in range(count)]
        for rel, entries in ALLOWLIST.items()
    }
    assert sorted(found.keys()) == sorted(expected.keys())
    for rel, matches in found.items():
        assert sorted(matches) == sorted(expected[rel]), (
            f"{rel}: transiciones terminales fuera de la allowlist.\n"
            f"encontradas: {sorted(matches)}\n"
            f"esperadas:   {sorted(expected[rel])}\n"
            "Rutear por FinalizationPolicy o agregar a la allowlist con justificación."
        )


def test_apply_terminal_es_el_unico_mutador_de_phase_en_src() -> None:
    """Ratchet de asignación: solo `run_state._apply_terminal` muta `.phase`.

    Los usuarios del estado tienen `try_advance` (no terminal) y el override de
    seguridad post cierre; una asignación nueva fuera del aplicador canónico
    exige justificación explícita acá y en el ownership map.
    """
    assignment = re.compile(r"\.phase\s*=\s*(?!=)")
    allowed = {
        "src/runtime/run_state.py": 2,
        # ^ `try_advance` (fase NO terminal) + `_apply_terminal` (canónico).
    }
    found = {
        str(path.relative_to(ROOT)).replace("\\", "/"): len(
            assignment.findall(path.read_text(encoding="utf-8"))
        )
        for path in (ROOT / "src").rglob("*.py")
        if assignment.search(path.read_text(encoding="utf-8"))
    }
    assert found == allowed, (
        "Asignaciones directas de `.phase` fuera del aplicador canónico:\n"
        f"  encontradas: {found}\n"
        f"  esperadas:   {allowed}"
    )


def test_allowlist_declara_justificacion() -> None:
    for entries in ALLOWLIST.values():
        for snippet, count, justification in entries:
            assert snippet.strip()
            assert count >= 1
            assert len(justification.strip()) >= 20
