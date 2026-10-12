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
            "phase = RunPhase.UNDETERMINED",
            1,
            "strict fail-closed: ejecuta la resolución de la política "
            "(UNDETERMINED/BLOCK sobre FINALIZED); no decide por sí",
        ),
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
    "src/agents/runtime/orchestrator.py": [
        (
            "phase = RunPhase.UNDETERMINED",
            1,
            "camino RAG sin loop: fallo determinista de fase",
        ),
    ],
    "src/runtime/run_state.py": [
        ("return RunPhase.FAILED", 1, "mapper único status → fase (finish())"),
        ("return RunPhase.LIMIT_REACHED", 1, "mapper único status → fase (finish())"),
        ("return RunPhase.BLOCKED", 3, "mapper único status → fase (finish())"),
        ("return RunPhase.ABSTAINED", 1, "mapper único status → fase (finish())"),
        ("return RunPhase.UNDETERMINED", 1, "mapper único status → fase (finish())"),
        ("return RunPhase.FINALIZED", 1, "mapper único status → fase (finish())"),
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


def test_allowlist_declara_justificacion() -> None:
    for entries in ALLOWLIST.values():
        for snippet, count, justification in entries:
            assert snippet.strip()
            assert count >= 1
            assert len(justification.strip()) >= 20
