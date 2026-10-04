# =============================================================================
# Acceptance — servicio (gate post-index)
# =============================================================================
# Modos:
#   off        -> no corre
#   observe    -> corre, mide y loguea; no persiste evaluación ni bloquea
#   warn       -> corre, mide, persiste y emite señal si no acepta
#   quarantine -> igual que warn + marca el documento como no publicado
#
# Nunca lanza: la ingesta jamás se cae porque el acceptance falle.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.core.domain.knowledge_v2 import StructuredDocument
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.enrichment.contracts import SemanticEnrichmentResult

from .contracts import AcceptanceMode, AcceptanceReport
from .evaluate import evaluate_probes
from .probes import generate_probes
from .store import PostgresAcceptanceStore

logger = get_logger(__name__)


@dataclass(frozen=True)
class AcceptanceGateResult:
    report: AcceptanceReport | None = None
    probes_total: int = 0
    persisted: bool = False
    quarantined: bool = False
    skipped_reason: str | None = None
    embedding_tokens: int = 0

    @property
    def ran(self) -> bool:
        return self.report is not None


def _setting(name: str, default):
    try:
        from src.core.config import get_settings

        return getattr(get_settings(), name, default)
    except Exception:  # noqa: BLE001
        return default


async def run_acceptance_gate(
    *,
    document: StructuredDocument,
    enrichment: SemanticEnrichmentResult | None,
    embedder,
    vector_store,
    mode: str | None = None,
    store: PostgresAcceptanceStore | None = None,
    max_probes: int | None = None,
    min_recall_at_5: float | None = None,
    role: str = "admin",
    user_id=None,
    groups=None,
) -> AcceptanceGateResult:
    mode = str(mode or _setting("KNOWLEDGE_RETRIEVAL_ACCEPTANCE_MODE", "warn"))
    if mode == AcceptanceMode.OFF.value:
        return AcceptanceGateResult(skipped_reason="mode_off")
    if enrichment is None:
        return AcceptanceGateResult(skipped_reason="no_enrichment")

    probes = generate_probes(
        document,
        enrichment,
        max_probes=int(max_probes or _setting("KNOWLEDGE_RETRIEVAL_ACCEPTANCE_MAX_PROBES", 24)),
    )
    if not probes:
        return AcceptanceGateResult(skipped_reason="no_probes")

    # Estimación determinista de tokens de embedding de las queries (costo real).
    embedding_tokens = sum(max(1, len(probe.query) // 4) for probe in probes)
    _observe_probes(probes)

    store = store if store is not None else PostgresAcceptanceStore()
    persisted = False
    if mode != AcceptanceMode.OBSERVE.value:
        try:
            await store.save_probes(probes)
            persisted = True
        except Exception as exc:  # noqa: BLE001 — el store no frena la ingesta
            logger.warning(
                "Acceptance probe persistence failed",
                document_id=str(document.id),
                error=str(exc)[:250],
            )

    try:
        report = await evaluate_probes(
            probes,
            embedder=embedder,
            vector_store=vector_store,
            role=role,
            user_id=user_id,
            groups=groups,
            min_recall_at_5=float(
                min_recall_at_5
                if min_recall_at_5 is not None
                else _setting("KNOWLEDGE_RETRIEVAL_ACCEPTANCE_MIN_RECALL", 0.6)
            ),
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 — nunca tumba la ingesta
        logger.warning(
            "Retrieval acceptance failed",
            document_id=str(document.id),
            error=str(exc)[:300],
        )
        return AcceptanceGateResult(probes_total=len(probes), skipped_reason="evaluation_error")

    _observe_metrics(report)

    if mode != AcceptanceMode.OBSERVE.value:
        try:
            await store.save_evaluation(report)
            await store.update_probe_results(report)
            persisted = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Acceptance evaluation persistence failed",
                document_id=str(document.id),
                error=str(exc)[:250],
            )

    quarantined = bool(
        mode == AcceptanceMode.QUARANTINE.value and report.gate_state == "FAIL"
    )
    if report.gate_state != "PASS":
        logger.warning(
            "Knowledge document retrieval state",
            document_id=str(document.id),
            mode=mode,
            state=report.gate_state,
            recall_at_5=report.recall_at_5,
            probes_failed=report.probes_failed,
            failed_types=sorted({outcome.query_type for outcome in report.failed_probes}),
        )
    return AcceptanceGateResult(
        report=report,
        probes_total=len(probes),
        persisted=persisted,
        quarantined=quarantined,
        embedding_tokens=embedding_tokens,
    )


def _observe_probes(probes) -> None:
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_retrieval_probes_total,
        )

        for probe in probes:
            knowledge_retrieval_probes_total.labels(
                organization_id=str(probe.organization_id),
                query_type=probe.query_type,
                status="generated",
            ).inc()
    except Exception:  # noqa: BLE001
        return


def _observe_metrics(report: AcceptanceReport) -> None:
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_retrieval_acceptance_failures_total,
            knowledge_retrieval_acceptance_recall,
            knowledge_retrieval_acceptance_runs_total,
        )

        org = str(report.organization_id)
        outcome = report.gate_state.lower()
        knowledge_retrieval_acceptance_runs_total.labels(
            organization_id=org, outcome=outcome
        ).inc()
        for k, value in (
            ("1", report.recall_at_1),
            ("3", report.recall_at_3),
            ("5", report.recall_at_5),
        ):
            if value is not None:
                knowledge_retrieval_acceptance_recall.labels(
                    organization_id=org, k=k
                ).observe(float(value))
        for outcome in report.failed_probes:
            knowledge_retrieval_acceptance_failures_total.labels(
                organization_id=org, query_type=outcome.query_type
            ).inc()
    except Exception:  # noqa: BLE001
        return
