# =============================================================================
# Acceptance — evaluación real contra el índice
# =============================================================================
# Corre cada probe con el MISMO contrato ACL del retrieval productivo
# (organization_id + workspace + role/user/groups). El rank se calcula sobre
# evidencia real: documento correcto, sección correcta, unidad esperada.
# =============================================================================
from __future__ import annotations

import time

from src.core.ports import EmbeddingProvider, VectorStore
from src.infrastructure.observability.logging_config import get_logger

from .contracts import (
    AcceptanceMode,
    AcceptanceReport,
    ProbeOutcome,
    RetrievalProbe,
)

logger = get_logger(__name__)

V2_DOC_FILTER = {"metadata.v2_doc": "true"}

#: Batching de embeddings de probes + presupuesto de retries individuales.
#: Evita fan-out descontrolado si el provider está caído (500 probes != 500 calls).
PROBE_EMBED_BATCH_SIZE = 32
PROBE_INDIVIDUAL_RETRY_BUDGET = 64


def _chunks_of(context) -> list:
    if context is None:
        return []
    chunks = getattr(context, "chunks", None)
    if chunks is not None:
        return list(chunks)
    if isinstance(context, (list, tuple)):
        return list(context)
    return []


def _metadata(chunk) -> dict:
    return dict(getattr(chunk, "metadata", None) or {})


def _document_id(chunk) -> str:
    metadata = _metadata(chunk)
    value = metadata.get("document_id")
    if value:
        return str(value)
    raw = getattr(chunk, "document_id", None)
    return str(raw) if raw else ""


def _matches(chunk, probe: RetrievalProbe) -> tuple[bool, bool, bool]:
    """(documento, sección, unidad) del chunk contra la evidencia esperada."""
    metadata = _metadata(chunk)
    hit_document = _document_id(chunk) == probe.expected_document_id
    if not hit_document:
        return False, False, False

    section_ids = {
        str(metadata.get("section_id") or ""),
        str(metadata.get("parent_id") or ""),
        str(metadata.get("prev_section_id") or ""),
        str(metadata.get("next_section_id") or ""),
    }
    hit_section = bool(probe.expected_section_id) and (
        probe.expected_section_id in section_ids
    )
    if not probe.expected_section_id:
        hit_section = True

    block_ids = {str(value) for value in (metadata.get("block_ids") or ())}
    unit_keys = {
        str(metadata.get("chunk_id") or ""),
        str(metadata.get("unit_id") or ""),
        str(metadata.get("primary_block_id") or ""),
        str(metadata.get("section_id") or ""),
    }
    hit_unit = False
    if probe.expected_unit_id:
        hit_unit = (
            probe.expected_unit_id in block_ids
            or probe.expected_unit_id in unit_keys
            or probe.expected_unit_id == str(metadata.get("table_id") or "")
        )
    else:
        hit_unit = True
    return True, hit_section, hit_unit


async def _search(store, probe: RetrievalProbe, embedding, **kwargs):
    try:
        return await store.search(
            organization_id=probe.organization_id,
            query_embedding=embedding,
            top_k=kwargs["top_k"],
            filters=V2_DOC_FILTER,
            role=kwargs["role"],
            user_id=kwargs["user_id"],
            groups=kwargs["groups"],
            workspace_id=probe.workspace_id,
        )
    except TypeError:
        # Adaptadores legacy sin kwargs opcionales.
        return await store.search(
            organization_id=probe.organization_id,
            query_embedding=embedding,
            top_k=kwargs["top_k"],
            filters=V2_DOC_FILTER,
        )


async def evaluate_probes(
    probes: tuple[RetrievalProbe, ...],
    *,
    embedder: EmbeddingProvider,
    vector_store: VectorStore,
    role: str = "admin",
    user_id=None,
    groups=None,
    top_k: int = 5,
    min_recall_at_5: float = 0.6,
    mode: str = AcceptanceMode.WARN.value,
    measure_lexical: bool = True,
) -> AcceptanceReport:
    started = time.perf_counter()
    organization_id = probes[0].organization_id if probes else None
    document_id = probes[0].document_id if probes else None
    source_id = probes[0].source_id if probes else None
    workspace_id = probes[0].workspace_id if probes else None

    if not probes or organization_id is None or document_id is None:
        return AcceptanceReport(
            organization_id=organization_id or document_id or _nil_uuid(),
            document_id=document_id or _nil_uuid(),
            source_id=source_id,
            workspace_id=workspace_id,
            mode=mode,
            probes_total=0,
            min_recall_at_5=min_recall_at_5,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            details={"reason": "no_probes"},
        )

    # Embeddings de queries: batches acotados; si un batch falla, retry
    # individual con presupuesto global (nunca N queries -> N calls sin tope).
    queries = [probe.query for probe in probes]
    embeddings: list[list[float] | None] = [None] * len(probes)
    individual_budget = PROBE_INDIVIDUAL_RETRY_BUDGET

    def _normalize(embedded) -> list[list[float]]:
        if embedded and not isinstance(embedded[0], list):
            return [embedded]  # proveedor que devuelve un solo vector
        return list(embedded or [])

    for start in range(0, len(queries), PROBE_EMBED_BATCH_SIZE):
        chunk = queries[start : start + PROBE_EMBED_BATCH_SIZE]
        try:
            embedded = _normalize(await embedder.embed(chunk))
        except Exception as exc:  # noqa: BLE001 — batch roto: retry acotado
            logger.warning(
                "Acceptance batch embedding failed",
                probes=len(chunk),
                error=str(exc)[:200],
            )
            for offset, query in enumerate(chunk):
                if individual_budget <= 0:
                    break
                individual_budget -= 1
                try:
                    single = _normalize(await embedder.embed([query]))
                    embeddings[start + offset] = single[0] if single else None
                except Exception as inner:  # noqa: BLE001
                    logger.warning(
                        "Acceptance probe embedding failed", error=str(inner)[:200]
                    )
            continue
        for offset in range(len(chunk)):
            if offset < len(embedded):
                embeddings[start + offset] = embedded[offset]

    outcomes: list[ProbeOutcome] = []
    for probe, embedding in zip(probes, embeddings):
        if embedding is None:
            outcomes.append(
                ProbeOutcome(
                    probe_id=probe.probe_id,
                    query=probe.query,
                    query_type=probe.query_type,
                    passed=False,
                    error="embedding_failed",
                )
            )
            continue
        try:
            context = await _search(
                vector_store,
                probe,
                list(embedding),
                top_k=top_k,
                role=role,
                user_id=user_id,
                groups=groups,
            )
        except Exception as exc:  # noqa: BLE001 — un probe no tumba la corrida
            outcomes.append(
                ProbeOutcome(
                    probe_id=probe.probe_id,
                    query=probe.query,
                    query_type=probe.query_type,
                    passed=False,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
            )
            continue

        chunks = _chunks_of(context)[:top_k]
        rank: int | None = None
        document_rank: int | None = None
        hit_document = hit_section = hit_unit = False
        retrieved_ids: list[str] = []
        top_score: float | None = None
        for position, chunk in enumerate(chunks, start=1):
            doc_id = _document_id(chunk)
            if doc_id and doc_id not in retrieved_ids:
                retrieved_ids.append(doc_id)
            if position == 1:
                score = getattr(chunk, "score", None)
                top_score = float(score) if score is not None else None
            matched, section_match, unit_match = _matches(chunk, probe)
            if not matched:
                continue
            hit_document = True
            hit_section = hit_section or section_match
            hit_unit = hit_unit or unit_match
            if document_rank is None:
                document_rank = position
            if rank is None and section_match and unit_match:
                rank = position

        lexical_hit: bool | None = None
        if measure_lexical:
            lexical_hit = await _lexical_hit(vector_store, probe, top_k=top_k)

        passed = bool(rank is not None and hit_document)
        outcomes.append(
            ProbeOutcome(
                probe_id=probe.probe_id,
                query=probe.query,
                query_type=probe.query_type,
                passed=passed,
                rank=rank,
                document_rank=document_rank,
                hit_document=hit_document,
                hit_section=bool(hit_section),
                hit_unit=bool(hit_unit),
                semantic_hit=bool(rank is not None),
                lexical_hit=lexical_hit,
                top_score=top_score,
                retrieved_document_ids=tuple(retrieved_ids),
            )
        )

    report = _aggregate(
        outcomes,
        organization_id=organization_id,
        document_id=document_id,
        source_id=source_id,
        workspace_id=workspace_id,
        mode=mode,
        top_k=top_k,
        min_recall_at_5=min_recall_at_5,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        measured_lexical=measure_lexical,
    )
    return report


async def _lexical_hit(store, probe: RetrievalProbe, *, top_k: int) -> bool | None:
    search_sparse = getattr(store, "search_sparse", None)
    if not callable(search_sparse):
        return None
    try:
        context = await search_sparse(
            organization_id=probe.organization_id,
            query_text=probe.query,
            top_k=top_k,
            filters=V2_DOC_FILTER,
        )
    except Exception:  # noqa: BLE001 — lexical es opcional
        return None
    for chunk in _chunks_of(context)[:top_k]:
        matched, _section, _unit = _matches(chunk, probe)
        if matched:
            return True
    return False


def _aggregate(
    outcomes: list[ProbeOutcome],
    *,
    organization_id,
    document_id,
    source_id,
    workspace_id,
    mode: str,
    top_k: int,
    min_recall_at_5: float,
    duration_ms: float,
    measured_lexical: bool,
) -> AcceptanceReport:
    total = len(outcomes)
    passed = sum(1 for outcome in outcomes if outcome.passed)
    ranks = [outcome.rank for outcome in outcomes]

    def recall(k: int) -> float:
        if not total:
            return 0.0
        return round(sum(1 for rank in ranks if rank is not None and rank <= k) / total, 4)

    mrr = (
        round(sum(1.0 / rank for rank in ranks if rank) / total, 4) if total else 0.0
    )
    with_unit = [outcome for outcome in outcomes if outcome.semantic_hit]
    lexical_measured = [outcome for outcome in outcomes if outcome.lexical_hit is not None]
    accepted = bool(total) and recall(5) >= min_recall_at_5
    failed = tuple(outcome for outcome in outcomes if not outcome.passed)

    return AcceptanceReport(
        organization_id=organization_id,
        document_id=document_id,
        source_id=source_id,
        workspace_id=workspace_id,
        mode=mode,
        accepted=accepted,
        retrievable=accepted,
        probes_total=total,
        probes_passed=passed,
        probes_failed=total - passed,
        recall_at_1=recall(1),
        recall_at_3=recall(3),
        recall_at_5=recall(5),
        mrr=mrr,
        correct_document_rate=round(
            sum(1 for outcome in outcomes if outcome.hit_document) / total, 4
        ) if total else None,
        correct_section_rate=round(
            sum(1 for outcome in outcomes if outcome.hit_section) / total, 4
        ) if total else None,
        evidence_hit_rate=round(
            len(with_unit) / total, 4
        ) if total else None,
        semantic_hit_rate=round(
            sum(1 for outcome in outcomes if outcome.semantic_hit) / total, 4
        ) if total else None,
        lexical_hit_rate=(
            round(sum(1 for outcome in lexical_measured if outcome.lexical_hit) / len(lexical_measured), 4)
            if lexical_measured
            else None
        ),
        top_score=next(
            (outcome.top_score for outcome in outcomes if outcome.top_score is not None),
            None,
        ),
        min_recall_at_5=min_recall_at_5,
        failed_probes=failed[:50],
        outcomes=tuple(outcomes),
        duration_ms=duration_ms,
        details={
            "top_k": top_k,
            "measured_lexical": bool(measured_lexical),
            "lexical_measured_probes": len(lexical_measured),
        },
    )


def _nil_uuid():
    from uuid import UUID

    return UUID(int=0)
