# =============================================================================
# Certificación de `except Exception` en caminos críticos (ratchet, F11).
# =============================================================================
# Regla: cada `except Exception` de un camino crítico declara su política
# (fail-soft | fail-closed | observability-only). El ratchet NO exige certificar
# todo hoy: exige que el número de excepciones SIN comentario no crezca y que no
# aparezcan `except:` desnudos. Bajar un número es el trabajo pendiente.
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Camino crítico → máximo de `except Exception` sin comentario permitido hoy.
#: 0 ya certificado; los >0 son deuda declarada en hardening/00-audit.md §3.
ALLOWED_UNCOMMENTED: dict[str, int] = {
    "src/agents/runtime/agent_runtime.py": 4,
    "src/agents/runtime/orchestrator.py": 11,
    "src/runtime/finalization_policy.py": 0,
    "src/runtime/enforcement.py": 0,
    "src/runtime/run_accounting.py": 0,
    "src/runtime/run_budget.py": 0,
    "src/runtime/prompt_assembly.py": 0,
    "src/runtime/failure_taxonomy.py": 0,
    "src/runtime/run_metrics.py": 0,
    "src/infrastructure/redis/cache.py": 0,
    "src/infrastructure/llm/router.py": 1,
    "src/infrastructure/llm/provider.py": 4,
}


def _scan(rel: str) -> tuple[int, list[int], list[int]]:
    """(sin_comentario, líneas sin comentario, líneas `except:` desnudas)."""
    path = ROOT / rel
    uncommented: list[int] = []
    bare: list[int] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("except Exception") and "#" not in line:
            uncommented.append(number)
        elif stripped == "except:" or stripped.startswith("except: "):
            bare.append(number)
    return len(uncommented), uncommented, bare


class TestRatchetDeExcepciones:
    def test_sin_except_desnudos_en_caminos_criticos(self) -> None:
        offenders = {
            rel: lines
            for rel in ALLOWED_UNCOMMENTED
            for _, lines, bare in [_scan(rel)]
            if bare
            for lines in [bare]
        }
        assert not offenders, f"`except:` desnudo prohibido: {offenders}"

    def test_el_numero_de_except_sin_comentario_no_crece(self) -> None:
        regressions: dict[str, str] = {}
        for rel, allowed in ALLOWED_UNCOMMENTED.items():
            count, lines, _ = _scan(rel)
            if count > allowed:
                regressions[rel] = f"{count} > {allowed} (líneas {lines})"
        assert not regressions, (
            "un `except Exception` nuevo en camino crítico debe declarar su "
            "política (fail-soft | fail-closed | observability-only): "
            f"{regressions}"
        )

    def test_el_ratchet_no_queda_por_encima_de_la_realidad(self) -> None:
        """Si se certificó de más, el número permitido baja en el mismo commit."""
        stale: dict[str, str] = {}
        for rel, allowed in ALLOWED_UNCOMMENTED.items():
            count, _, _ = _scan(rel)
            if count < allowed:
                stale[rel] = f"{count} < {allowed}"
        assert not stale, (
            "bajá ALLOWED_UNCOMMENTED (el ratchet solo se aprieta): "
            f"{stale}"
        )
