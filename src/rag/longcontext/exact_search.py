# =============================================================================
# ExactRetriever — tercera pata, ahora POR ANCHOR y con source routing
# =============================================================================
# El error que corrige: un único barrido OR con `limit` global. Con scroll
# order, 4 chunks que contienen FCLAS llenaban el cupo y «&&&F» jamás se
# buscaba; el sistema creía haber hecho "exact retrieval". Acá:
#
#   - cada anchor DOCUMENTABLE tiene su propia búsqueda y su propio cupo;
#   - los anchors se procesan por rol: RULE → FIELD → REFERENCE/ENTITY →
#     EXAMPLE_VALUE (el ejemplo no es requirement documental, va último);
#   - cada anchor busca primero en las PREFERRED SOURCES y sólo si no hay
#     aciertos barre el resto de las fuentes permitidas;
#   - un acierto de regla no se mezcla con un acierto común: `mark_exact_hit`
#     deja el nivel (rule/field/reference/supporting) para el packager.
# =============================================================================
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.response.anchors import Anchor, extract_anchors
from src.rag.longcontext.exact_tokens import ExactToken
from src.rag.longcontext.must_keep import mark_exact_hit, must_keep_level
from src.rag.longcontext.roles import (
    AnchorRole,
    normalize_role,
    role_for_kind,
)

if TYPE_CHECKING:  # evita el ciclo retrieval.__init__ → hybrid → exact_search
    from src.rag.retrieval.models import RetrievalQuery

logger = get_logger(__name__)

_DEFAULT_MAX_NEEDLES = 8
_DEFAULT_CHUNKS = 4
_DEFAULT_MAX_POINTS = 4000
_DEFAULT_MAX_MS = 1500.0

#: Orden de procesamiento por rol (menor = antes).
_ROLE_PRIORITY = {
    AnchorRole.RULE_ANCHOR.value: 0,
    AnchorRole.FIELD_ANCHOR.value: 1,
    AnchorRole.ENTITY.value: 2,
    AnchorRole.REFERENCE.value: 3,
    AnchorRole.EXAMPLE_VALUE.value: 9,
    "": 4,
}

#: Calidad de un chunk para quedarse con la mejor marca si aparece en varios.
_LEVEL_ORDER = {"rule": 0, "field": 1, "reference": 2, "supporting": 3, "": 4}


@dataclass(frozen=True, kw_only=True)
class ExactAnchorSpec:
    """Un anchor exacto con su rol y sus needles."""

    value: str
    role: str = ""
    needles: tuple[str, ...] = ()

    @property
    def priority(self) -> int:
        return _ROLE_PRIORITY.get(self.role, 4)

    @property
    def documentable(self) -> bool:
        return self.role != AnchorRole.EXAMPLE_VALUE.value

    def effective_needles(self) -> list[str]:
        values = [str(needle).strip() for needle in self.needles if str(needle or "").strip()]
        if self.value and self.value not in values:
            values.insert(0, self.value)
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.lower()
            if len(value) >= 2 and key not in seen:
                seen.add(key)
                deduped.append(value)
        return deduped[:3]


def spec_from_anchor(anchor: Anchor) -> ExactAnchorSpec:
    role = normalize_role(getattr(anchor, "role", "") or "") or role_for_kind(anchor)
    return ExactAnchorSpec(
        value=str(getattr(anchor, "value", "") or ""),
        role=role,
        needles=tuple(
            str(needle) for needle in getattr(anchor, "needles", ()) if needle
        )
        or (str(getattr(anchor, "value", "") or ""),),
    )


def spec_from_needle(needle: str) -> ExactAnchorSpec:
    """Clasifica un needle suelto por forma (tests/rewrites): máscara=regla."""
    value = str(needle or "").strip()
    role = ""
    try:
        found = extract_anchors(value, max_items=1)
        if found:
            role = role_for_kind(found[0])
    except Exception:  # noqa: BLE001 — clasificación best-effort
        role = ""
    return ExactAnchorSpec(value=value, role=role, needles=(value,))


def _coerce_specs(items: Any) -> list[ExactAnchorSpec]:
    specs: list[ExactAnchorSpec] = []
    for item in items or ():
        try:
            if isinstance(item, ExactAnchorSpec):
                specs.append(item)
            elif isinstance(item, Anchor):
                specs.append(spec_from_anchor(item))
            elif isinstance(item, ExactToken):
                specs.append(
                    ExactAnchorSpec(
                        value=str(item.value or ""),
                        role=normalize_role(item.kind) or _role_from_token_kind(item.kind),
                        needles=tuple(str(needle) for needle in item.needles if needle),
                    )
                )
            elif isinstance(item, dict):
                specs.append(
                    ExactAnchorSpec(
                        value=str(item.get("value") or ""),
                        role=normalize_role(str(item.get("role") or "")),
                        needles=tuple(
                            str(needle) for needle in item.get("needles") or () if needle
                        ),
                    )
                )
            elif isinstance(item, str):
                specs.append(spec_from_needle(item))
        except Exception:  # noqa: BLE001, S112 — un token roto no rompe la pata
            continue
    return [spec for spec in specs if spec.effective_needles()]


def _role_from_token_kind(kind: str) -> str:
    value = str(kind or "").strip().lower()
    if value in ("mascara", "rango"):
        return AnchorRole.RULE_ANCHOR.value
    if value in ("sigla", "campo"):
        return AnchorRole.FIELD_ANCHOR.value
    if value in ("codigo", "identificador"):
        return AnchorRole.REFERENCE.value
    return ""


class ExactRetriever:
    """Pata exacta per-anchor sobre el store, preferred sources primero."""

    def __init__(self, store: object) -> None:
        self._store = store

    def _settings(self) -> tuple[bool, int, int, int, float]:
        """(activo, cupo por anchor, puntos, anchors máx, ms)."""
        try:
            from src.core.config import get_settings

            settings = get_settings()

            def _leer(nombre: str, default):
                return getattr(settings, nombre, default)

            activo = str(_leer("RAG_EXACT_SEARCH", "on")).lower() not in {
                "off",
                "0",
                "false",
            }
            return (
                activo,
                max(int(_leer("RAG_EXACT_SEARCH_CHUNKS", _DEFAULT_CHUNKS) or 0), 1),
                max(int(_leer("RAG_EXACT_SEARCH_MAX_POINTS", _DEFAULT_MAX_POINTS) or 0), 0),
                max(int(_leer("RAG_EXACT_SEARCH_MAX_NEEDLES", _DEFAULT_MAX_NEEDLES) or 0), 1),
                max(float(_leer("RAG_EXACT_SEARCH_MAX_MS", _DEFAULT_MAX_MS) or 0.0), 0.0),
            )
        except Exception:  # noqa: BLE001 — la pata exacta nunca rompe el retrieval
            return True, _DEFAULT_CHUNKS, _DEFAULT_MAX_POINTS, _DEFAULT_MAX_NEEDLES, _DEFAULT_MAX_MS

    async def retrieve(
        self,
        query: RetrievalQuery,
        items: Any,
    ) -> RetrievalContext:
        """Busca cada anchor por separado; no comparte cupo entre anchors."""
        activo, per_anchor, max_points, max_anchors, max_ms = self._settings()
        if not activo or not getattr(query, "exact_search", True):
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)
        specs = _coerce_specs(items)
        if not specs:
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

        scan_literal = getattr(self._store, "scan_text_literal", None)
        scan = scan_literal if callable(scan_literal) else getattr(self._store, "scan_text", None)
        if not callable(scan):
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

        preferred = [
            source_id
            for source_id in (getattr(query, "preferred_source_ids", None) or [])
            if source_id
        ]
        allowed = list(query.source_ids or [])
        remaining = [source_id for source_id in allowed if source_id not in preferred]

        ordered = sorted(
            specs, key=lambda spec: (spec.priority, -len(spec.value))
        )[: max(1, int(max_anchors))]
        # El valor de ejemplo del usuario no es requirement documental: sólo se
        # busca si no hay NINGÚN anchor documentable (pregunta puramente de valor).
        documentables = [spec for spec in ordered if spec.documentable]
        if documentables:
            ordered = documentables
        collected: dict[Any, RetrievalChunk] = {}
        latency = 0.0
        scans = 0
        per_anchor_found: dict[str, int] = {}

        for spec in ordered:
            needles = spec.effective_needles()
            if not needles:
                continue
            found_for_anchor = 0
            # Preferred PRIMERO, en orden de score: una fuente a la vez. Si la
            # mejor fuente tiene el anchor, no se barre el resto para ESTE
            # anchor. Cada anchor tiene su propio cupo: 10 hits de FCLAS no
            # consumen el presupuesto de &&&F.
            groups: list[list[Any] | None] = []
            if preferred:
                groups.extend([[source_id] for source_id in preferred])
                if remaining:
                    groups.append(remaining)
            elif remaining:
                groups.append(remaining)
            else:
                groups.append(allowed or None)
            for sources in groups:
                if found_for_anchor >= per_anchor:
                    break
                context = await self._scan(
                    scan,
                    query,
                    needles,
                    sources=sources,
                    limit=per_anchor,
                    max_points=max_points,
                    max_ms=max_ms,
                )
                scans += 1
                latency += float(context.retrieval_latency_ms or 0.0)
                for chunk in self._literal_hits(context.chunks, needles):
                    needle = self._matched_needle(chunk, needles)
                    marked = mark_exact_hit(
                        chunk,
                        needle=needle,
                        role=spec.role,
                        retrieval=_retrieval_for_role(spec.role),
                    )
                    current = collected.get(marked.document_id)
                    if current is None or _is_better_level(marked, current):
                        collected[marked.document_id] = marked
                    found_for_anchor += 1
                    if found_for_anchor >= per_anchor:
                        break
                if found_for_anchor:
                    break
            per_anchor_found[spec.value] = found_for_anchor

        chunks = list(collected.values())
        if chunks:
            logger.info(
                "Exact leg matched per anchor",
                anchors={key: value for key, value in per_anchor_found.items() if value},
                scans=scans,
                chunks=len(chunks),
                organization_id=str(query.organization_id),
            )
        return RetrievalContext(
            chunks=chunks,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=latency,
        )

    async def _scan(
        self,
        scan,
        query: RetrievalQuery,
        needles: list[str],
        *,
        sources: list[Any] | None,
        limit: int,
        max_points: int,
        max_ms: float,
    ) -> RetrievalContext:
        try:
            return await scan(
                organization_id=query.organization_id,
                needles=list(needles),
                source_ids=sources,
                knowledge_base_id=query.knowledge_base_id,
                workspace_id=query.workspace_id,
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
                limit=limit,
                max_points=max_points,
                max_ms=max_ms,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort, jamás tumba el retrieval
            logger.warning("Exact scan failed", error=str(exc)[:200])
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

    @staticmethod
    def _literal_hits(
        chunks: list[RetrievalChunk],
        needles: list[str],
    ) -> list[RetrievalChunk]:
        hits: list[RetrievalChunk] = []
        for chunk in chunks:
            content = html.unescape(chunk.content or "").lower()
            if any(needle.lower() in content for needle in needles):
                hits.append(chunk)
        return hits

    @staticmethod
    def _matched_needle(chunk: RetrievalChunk, needles: list[str]) -> str:
        content = html.unescape(chunk.content or "").lower()
        for needle in needles:
            if needle.lower() in content:
                return needle
        return needles[0]


def _retrieval_for_role(role: str) -> str:
    if role == AnchorRole.RULE_ANCHOR.value:
        return "exact_rule"
    if role == AnchorRole.FIELD_ANCHOR.value:
        return "exact_field"
    if role == AnchorRole.EXAMPLE_VALUE.value:
        return "exact_example"
    return "exact"


def _is_better_level(candidate: RetrievalChunk, current: RetrievalChunk) -> bool:
    return _LEVEL_ORDER.get(
        must_keep_level(candidate), 4
    ) < _LEVEL_ORDER.get(must_keep_level(current), 4)


__all__ = ["ExactAnchorSpec", "ExactRetriever", "spec_from_anchor", "spec_from_needle"]
