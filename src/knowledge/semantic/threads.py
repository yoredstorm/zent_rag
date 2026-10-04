# =============================================================================
# SemanticThreads — continuidad bidireccional (§12-13)
# =============================================================================
# Una idea puede abrirse en una ventana y resolverse muchas ventanas después
# (referencia temprana a un apéndice, símbolo usado antes de definirse,
# continuación abierta al final de una sección).
#
# Un thread es un objeto DURABLE con:
#   id determinista, type, source_units, target_hint, scope, status,
#   opened_at, resolved_by, confidence.
#
# Resolución bidireccional: la ventana N puede resolver un thread abierto en la
# ventana 1; y un thread ambiguo puede desambiguarse con información posterior.
# Sin LLM: matching determinista por label/tokens con candidatos auditables.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import UUID, uuid5

from src.knowledge.compiler.model import normalize_term

from .contracts import SemanticWindowResult

THREAD_VERSION = "semantic-thread-1"

#: Namespace de IDs deterministas de thread.
THREAD_NS = UUID("d3f7a1c2-9b4e-4e7a-8c1d-2f6b5a9e3c21")

#: Tope de historia por thread (status changes).
MAX_HISTORY = 20
#: Tope de candidatos guardados por thread.
MAX_CANDIDATES = 8


class ThreadType(StrEnum):
    REFERENCE = "REFERENCE"
    CONTINUATION = "CONTINUATION"
    DEFINITION = "DEFINITION"
    SYMBOL = "SYMBOL"
    RULE_DEPENDENCY = "RULE_DEPENDENCY"
    TABLE_REFERENCE = "TABLE_REFERENCE"
    EXCEPTION = "EXCEPTION"
    ALIAS = "ALIAS"
    TEMPORAL = "TEMPORAL"
    ENTITY = "ENTITY"


class ThreadStatus(StrEnum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTING = "CONFLICTING"
    UNRESOLVED = "UNRESOLVED"


#: Tipos que la Fase 4 abre con evidencia determinista (los demás quedan
#: soportados en el modelo para el stitcher de Fase 5).
OPENABLE_TYPES: tuple[str, ...] = (
    ThreadType.REFERENCE.value,
    ThreadType.TABLE_REFERENCE.value,
    ThreadType.CONTINUATION.value,
    ThreadType.SYMBOL.value,
    ThreadType.ALIAS.value,
    ThreadType.EXCEPTION.value,
)


@dataclass(frozen=True, kw_only=True)
class SemanticThread:
    """Hilo semántico durable. Id determinista por documento + clave."""

    id: UUID
    thread_key: str
    thread_type: str
    status: str
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    target_hint: str = ""
    target_kind: str | None = None
    scope: str | None = None
    source_units: tuple[str, ...] = ()
    source_windows: tuple[int, ...] = ()
    opened_at_window: int = 0
    last_seen_window: int = 0
    resolved_at_window: int | None = None
    resolved_by_unit: str | None = None
    confidence: float = 0.5
    candidates: tuple[dict, ...] = ()
    evidence: dict = field(default_factory=dict)
    history: tuple[dict, ...] = ()
    version: str = THREAD_VERSION

    @property
    def is_open(self) -> bool:
        return self.status in {
            ThreadStatus.OPEN.value,
            ThreadStatus.PARTIAL.value,
            ThreadStatus.AMBIGUOUS.value,
            ThreadStatus.CONFLICTING.value,
            ThreadStatus.UNRESOLVED.value,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "thread_key": self.thread_key,
            "thread_type": self.thread_type,
            "status": self.status,
            "target_hint": self.target_hint[:512],
            "target_kind": self.target_kind,
            "scope": self.scope,
            "source_units": list(self.source_units),
            "source_windows": list(self.source_windows),
            "opened_at_window": int(self.opened_at_window),
            "last_seen_window": int(self.last_seen_window),
            "resolved_at_window": self.resolved_at_window,
            "resolved_by_unit": self.resolved_by_unit,
            "confidence": round(float(self.confidence), 4),
            "candidates": list(self.candidates),
            "evidence": dict(self.evidence),
            "history": list(self.history),
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class ThreadStats:
    opened: int = 0
    resolved: int = 0
    partial: int = 0
    ambiguous: int = 0
    still_open: int = 0
    touched: int = 0

    def to_dict(self) -> dict:
        return {
            "opened": self.opened,
            "resolved": self.resolved,
            "partial": self.partial,
            "ambiguous": self.ambiguous,
            "still_open": self.still_open,
            "touched": self.touched,
        }


# ---------------------------------------------------------------------------
# Apertura
# ---------------------------------------------------------------------------


def open_threads_from_result(
    result: SemanticWindowResult,
) -> list[SemanticThread]:
    """Threads nuevos que abre una ventana (con evidencia determinista)."""
    threads: list[SemanticThread] = []

    for item in result.unresolved_references:
        target_kind = str(item.attributes.get("target_kind") or "").lower()
        is_table = target_kind in {"table", "tabla"}
        threads.append(
            _new_thread(
                result,
                thread_type=(
                    ThreadType.TABLE_REFERENCE.value
                    if is_table
                    else ThreadType.REFERENCE.value
                ),
                thread_key=(
                    f"table_reference:{normalize_term(item.label)}"
                    if is_table
                    else f"reference:{target_kind}:{normalize_term(item.label)}"
                ),
                target_hint=item.label,
                target_kind=target_kind or None,
                scope=str(item.attributes.get("section_id") or "") or None,
                confidence=float(item.confidence),
                source_units=item.block_ids,
                evidence={
                    "reference_text": item.text,
                    "block_ids": list(item.block_ids),
                },
            )
        )

    for item in result.continuation_candidates:
        scope = str(item.attributes.get("section_id") or "") or None
        threads.append(
            _new_thread(
                result,
                thread_type=ThreadType.CONTINUATION.value,
                thread_key=f"continuation:{scope or 'document'}:{normalize_term(item.label)[:80]}",
                target_hint=item.label,
                scope=scope,
                confidence=float(item.confidence),
                source_units=item.block_ids,
                evidence={
                    "target_hint": item.attributes.get("target_hint"),
                    "block_ids": list(item.block_ids),
                },
            )
        )

    defined_labels = {
        normalize_term(str(item.label))
        for kind in ("definition", "entity")
        for item in result.by_kind(kind)
    }
    for item in result.symbols:
        # Un símbolo con dueño DEFINIDO EN ESTA VENTANA ya está asociado; si la
        # definición vive en otra ventana, el símbolo abre thread (se usó antes
        # de definirse y la ventana posterior lo resuelve).
        owner = str(
            item.attributes.get("parent_definition")
            or item.attributes.get("field_name")
            or item.attributes.get("relation_target")
            or ""
        )
        if owner and normalize_term(owner) in defined_labels:
            continue
        threads.append(
            _new_thread(
                result,
                thread_type=ThreadType.SYMBOL.value,
                thread_key=f"symbol:{item.label}",
                target_hint=item.label,
                confidence=float(item.confidence),
                source_units=item.block_ids,
                evidence={
                    "identifier_type": item.attributes.get("identifier_type"),
                    "owner_hint": owner or None,
                    "block_ids": list(item.block_ids),
                },
            )
        )

    for item in result.aliases:
        if item.attributes.get("canonical"):
            continue
        threads.append(
            _new_thread(
                result,
                thread_type=ThreadType.ALIAS.value,
                thread_key=f"alias:{normalize_term(item.label)}",
                target_hint=item.label,
                confidence=float(item.confidence),
                source_units=item.block_ids,
                evidence={"alias_kind": item.attributes.get("alias_kind")},
            )
        )

    for item in result.exceptions:
        # Una excepción se ancla a un símbolo/regla si lo menciona.
        symbol = _first_symbol(item.text)
        if not symbol:
            continue
        threads.append(
            _new_thread(
                result,
                thread_type=ThreadType.EXCEPTION.value,
                thread_key=f"exception:{symbol}",
                target_hint=symbol,
                confidence=float(item.confidence),
                source_units=item.block_ids,
                evidence={"exception_text": item.text[:400]},
            )
        )
    return threads


def _new_thread(
    result: SemanticWindowResult,
    *,
    thread_type: str,
    thread_key: str,
    target_hint: str,
    confidence: float,
    source_units: tuple[str, ...],
    target_kind: str | None = None,
    scope: str | None = None,
    evidence: dict | None = None,
) -> SemanticThread:
    document_id = result.document_id
    return SemanticThread(
        id=uuid5(THREAD_NS, f"{document_id}|{thread_key}"),
        thread_key=thread_key,
        thread_type=thread_type,
        status=ThreadStatus.OPEN.value,
        organization_id=result.organization_id,
        source_id=result.source_id,
        workspace_id=result.workspace_id,
        document_id=document_id,
        target_hint=target_hint,
        target_kind=target_kind,
        scope=scope,
        source_units=source_units,
        source_windows=(int(result.window_index),),
        opened_at_window=int(result.window_index),
        last_seen_window=int(result.window_index),
        confidence=max(0.0, min(1.0, float(confidence))),
        evidence=dict(evidence or {}),
        history=(
            {
                "window": int(result.window_index),
                "status": ThreadStatus.OPEN.value,
                "reason": "opened",
            },
        ),
    )


# ---------------------------------------------------------------------------
# Avance / resolución
# ---------------------------------------------------------------------------


def advance_threads(
    existing: dict[str, SemanticThread],
    result: SemanticWindowResult,
    *,
    window_section_id: str | None = None,
) -> tuple[dict[str, SemanticThread], list[SemanticThread], ThreadStats]:
    """Resuelve threads previos con la ventana actual y abre los nuevos.

    Devuelve (mapa actualizado, threads tocados, stats). Determinista.
    """
    updated: dict[str, SemanticThread] = dict(existing)
    touched: dict[str, SemanticThread] = {}
    opened = resolved = partial = ambiguous = 0

    for key, thread in list(updated.items()):
        if not thread.is_open:
            continue
        candidates = _resolution_candidates(
            thread, result, window_section_id=window_section_id
        )
        if not candidates:
            if thread.last_seen_window < result.window_index:
                updated[key] = replace(
                    thread, last_seen_window=int(result.window_index)
                )
                touched[key] = updated[key]
            continue
        status, reason, resolved_by_unit = _status_for_candidates(candidates)
        new_history = _append_history(
            thread.history,
            window=int(result.window_index),
            status=status,
            reason=reason,
        )
        updated[key] = replace(
            thread,
            status=status,
            last_seen_window=int(result.window_index),
            resolved_at_window=int(result.window_index),
            resolved_by_unit=resolved_by_unit,
            confidence=round(float(candidates[0].get("confidence") or 0.5), 4),
            candidates=tuple(candidates[:MAX_CANDIDATES]),
            history=new_history,
        )
        touched[key] = updated[key]
        if status == ThreadStatus.RESOLVED.value:
            resolved += 1
        elif status == ThreadStatus.PARTIAL.value:
            partial += 1
        else:
            ambiguous += 1

    for thread in open_threads_from_result(result):
        if thread.thread_key in updated:
            # Ya existe (reproceso de ventana): conservar el más informativo.
            continue
        updated[thread.thread_key] = thread
        touched[thread.thread_key] = thread
        opened += 1

    stats = ThreadStats(
        opened=opened,
        resolved=resolved,
        partial=partial,
        ambiguous=ambiguous,
        still_open=sum(1 for item in updated.values() if item.is_open),
        touched=len(touched),
    )
    return updated, list(touched.values()), stats


def _resolution_candidates(
    thread: SemanticThread,
    result: SemanticWindowResult,
    *,
    window_section_id: str | None,
) -> list[dict]:
    if thread.thread_type == ThreadType.CONTINUATION.value:
        if (
            thread.scope
            and window_section_id
            and str(thread.scope) == str(window_section_id)
            and result.window_index > thread.opened_at_window
        ):
            block_id = result.block_ids[0] if result.block_ids else None
            return [
                {
                    "kind": "continuation",
                    "label": thread.target_hint[:120],
                    "block_id": block_id,
                    "confidence": 0.8,
                }
            ]
        return []

    label = normalize_term(thread.target_hint)
    if not label:
        return []
    tokens = set(label.split())
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def consider(item, kind: str) -> None:
        item_label = normalize_term(str(item.label))
        if not item_label:
            return
        matched = item_label == label or (
            len(label) >= 2 and label in item_label.split()
        )
        if not matched:
            return
        candidate_key = (kind, item.key or item_label)
        if candidate_key in seen:
            return
        seen.add(candidate_key)
        candidates.append(
            {
                "kind": kind,
                "label": item.label[:200],
                "block_id": item.block_ids[0] if item.block_ids else None,
                "confidence": round(float(item.confidence), 4),
                "key": item.key,
            }
        )

    if thread.thread_type in {
        ThreadType.REFERENCE.value,
        ThreadType.TABLE_REFERENCE.value,
    }:
        for kind in ("definition", "entity", "concept", "symbol", "rule", "topic", "table"):
            for item in result.by_kind(kind):
                consider(item, kind)
    elif thread.thread_type == ThreadType.SYMBOL.value:
        symbol = thread.target_hint
        for definition in result.definitions:
            if symbol and (symbol in definition.text or symbol in definition.label):
                consider(definition, "definition")
        for entity in result.entities:
            if str(entity.attributes.get("literal_pattern") or "") == symbol:
                consider(entity, "entity")
        for item in result.symbols:
            if item.label == symbol and (
                item.attributes.get("field_name")
                or item.attributes.get("relation_target")
                or item.text
            ):
                consider(item, "symbol")
    elif thread.thread_type == ThreadType.ALIAS.value:
        for kind in ("concept", "entity", "definition"):
            for item in result.by_kind(kind):
                consider(item, kind)
    elif thread.thread_type == ThreadType.EXCEPTION.value:
        symbol = thread.target_hint
        for rule in result.rules:
            if symbol and symbol in f"{rule.label} {rule.text}":
                consider(rule, "rule")
    return candidates


def _status_for_candidates(candidates: list[dict]) -> tuple[str, str, str | None]:
    best = max(candidates, key=lambda item: float(item.get("confidence") or 0.0))
    confidence = float(best.get("confidence") or 0.0)
    resolved_by = str(best.get("block_id") or "") or None
    if len(candidates) > 1 and confidence < 0.85:
        return (
            ThreadStatus.AMBIGUOUS.value,
            "multiple_candidates",
            None,
        )
    if confidence < 0.6:
        return (ThreadStatus.PARTIAL.value, "low_confidence_candidate", resolved_by)
    return (ThreadStatus.RESOLVED.value, "candidate_found", resolved_by)


def _append_history(
    history: tuple[dict, ...], *, window: int, status: str, reason: str
) -> tuple[dict, ...]:
    if history and history[-1].get("status") == status:
        return history
    return (
        *history,
        {"window": int(window), "status": status, "reason": reason},
    )[-MAX_HISTORY:]


def _first_symbol(text: str) -> str | None:
    import re

    match = re.search(r"\S*[&%#?*\[\]]\S*", text or "")
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# Rollback (reproceso de una ventana)
# ---------------------------------------------------------------------------


def rollback_threads(
    existing: dict[str, SemanticThread], *, from_window: int
) -> dict[str, SemanticThread]:
    """Deshace los efectos de ventanas >= from_window antes de reprocesarlas.

    - threads abiertos en esas ventanas se eliminan (se re-derivan);
    - threads resueltos en esas ventanas vuelven a OPEN;
    - se recortan source_windows/last_seen_window.
    """
    rolled: dict[str, SemanticThread] = {}
    for key, thread in existing.items():
        if thread.opened_at_window >= from_window:
            # Se re-derivará al reprocesar la ventana; no conservar.
            continue
        windows = tuple(
            value for value in thread.source_windows if value < from_window
        )
        last_seen = max(windows) if windows else thread.opened_at_window
        if thread.resolved_at_window is not None and thread.resolved_at_window >= from_window:
            thread = replace(
                thread,
                status=ThreadStatus.OPEN.value,
                resolved_at_window=None,
                resolved_by_unit=None,
                candidates=(),
                source_windows=windows,
                last_seen_window=last_seen,
                history=_append_history(
                    thread.history,
                    window=from_window,
                    status=ThreadStatus.OPEN.value,
                    reason="rollback_reprocess",
                ),
            )
        else:
            thread = replace(
                thread,
                source_windows=windows,
                last_seen_window=last_seen,
            )
        rolled[key] = thread
    return rolled


def cap_open_threads(
    existing: dict[str, SemanticThread], *, max_open: int
) -> tuple[dict[str, SemanticThread], list[SemanticThread]]:
    """Tope de threads abiertos por documento: los más viejos pasan a UNRESOLVED.

    Evita crecimiento infinito en fuentes enormes; el estado queda auditable
    (history + reason) y el stitcher de Fase 5 puede reabrirlos con evidencia.
    """
    if max_open <= 0:
        return existing, []
    open_threads = sorted(
        (thread for thread in existing.values() if thread.is_open),
        key=lambda thread: (thread.opened_at_window, thread.thread_key),
    )
    overflow = len(open_threads) - max_open
    if overflow <= 0:
        return existing, []
    touched: list[SemanticThread] = []
    for thread in open_threads[:overflow]:
        updated = replace(
            thread,
            status=ThreadStatus.UNRESOLVED.value,
            history=_append_history(
                thread.history,
                window=thread.last_seen_window,
                status=ThreadStatus.UNRESOLVED.value,
                reason="open_thread_cap",
            ),
        )
        existing[thread.thread_key] = updated
        touched.append(updated)
    return existing, touched


__all__ = [
    "MAX_CANDIDATES",
    "OPENABLE_TYPES",
    "THREAD_NS",
    "THREAD_VERSION",
    "SemanticThread",
    "ThreadStats",
    "ThreadStatus",
    "ThreadType",
    "advance_threads",
    "cap_open_threads",
    "open_threads_from_result",
    "rollback_threads",
]
