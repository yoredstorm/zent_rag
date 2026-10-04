# =============================================================================
# Knowledge OS — Retrieval Acceptance Gate
# =============================================================================
# El conocimiento ingerido no está "listo" hasta probar que puede encontrarse.
#
#   semantic units -> probes -> retrieval real -> comparación con la evidencia
#   esperada -> métricas -> accept / warn / quarantine
#
# Los probes son objetos versionados y re-ejecutables sin re-ingerir la fuente.
# Multi-tenant: toda corrida va scoped por organization_id y ACL válida.
# =============================================================================
from __future__ import annotations

from .contracts import (
    AcceptanceMode,
    AcceptanceReport,
    ProbeOutcome,
    RetrievalProbe,
)
from .evaluate import evaluate_probes
from .probes import generate_probes
from .service import AcceptanceGateResult, run_acceptance_gate
from .store import PostgresAcceptanceStore, probe_from_row

__all__ = [
    "AcceptanceGateResult",
    "AcceptanceMode",
    "AcceptanceReport",
    "PostgresAcceptanceStore",
    "ProbeOutcome",
    "RetrievalProbe",
    "evaluate_probes",
    "generate_probes",
    "probe_from_row",
    "run_acceptance_gate",
]
