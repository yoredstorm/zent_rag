# =============================================================================
# SourceRouter — elegir/rankear FUENTES antes del chunk ranking
# =============================================================================
# Determinístico y sin LLM. Puntúa la relación query ↔ fuente con metadata ya
# disponible (nombre, título, tipo de documento) y referencias estructurales
# («record 2», «cat 10») derivadas de forma genérica:
#
#   - match de referencia en el nombre          +3.0
#   - documento de reglas/spec para pregunta de regla +1.2
#   - documento de ejemplos cuando no se piden     -0.8
#   - overlap de términos del nombre               +0..1
#   - qualifier declarado NO pedido                -1.0
#   - qualifier del MISMO tipo con OTRO valor      -2.0
#
# El resultado son `preferred_sources` (a buscar primero) y `candidates`
# (fallback global). No hay ninguna regla por nombre de archivo.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.response.references import (
    SourceReference,
    extract_source_references,
    normalize_source_name,
    parse_declared_references,
    reference_matches_source,
)

logger = get_logger(__name__)

MAX_PREFERRED_SOURCES = 3
#: Score mínimo para entrar como preferred (un match de referencia ya lo supera).
MIN_PREFERRED_SCORE = 2.0

_RULE_HINTS = (
    "rule",
    "rules",
    "regla",
    "reglas",
    "spec",
    "specification",
    "norma",
    "normativa",
    "manual",
    "handbook",
    "guide",
    "guia",
    "referencia",
    "reference",
)
_EXAMPLE_HINTS = ("example", "examples", "ejemplo", "ejemplos", "sample", "muestra")
_RULE_QUESTION_RE = re.compile(
    r"\b(regla|reglas|rule|rules|significa|quiere decir|c[oó]mo funciona|"
    r"aplica|acepta|cumple|v[aá]lid[oa]|interpreta)\b",
    re.IGNORECASE,
)
_TERM_STOPWORDS = frozenset(
    {
        "para", "como", "cuando", "donde", "sobre", "entre", "esto", "esta",
        "este", "with", "that", "this", "from", "what", "which",
        "record", "byte", "table", "category", "field",
    }
)


@dataclass(frozen=True, kw_only=True)
class SourceProfile:
    """Metadata mínima de una fuente para routing (sin LLM)."""

    source_id: str
    name: str
    title: str = ""
    document_type: str = ""
    declared_references: tuple[SourceReference, ...] = ()
    terms: tuple[str, ...] = ()
    summary: str = ""

    @property
    def display_name(self) -> str:
        return self.title or self.name


@dataclass(frozen=True, kw_only=True)
class SourceScore:
    source_id: str
    name: str
    score: float
    reasons: tuple[str, ...] = ()
    matched_references: tuple[str, ...] = ()
    extra_scopes: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_id": self.source_id,
            "name": self.name,
            "score": round(self.score, 3),
        }
        if self.reasons:
            payload["reasons"] = list(self.reasons[:6])
        if self.matched_references:
            payload["matched_references"] = list(self.matched_references)
        if self.extra_scopes:
            payload["extra_scopes"] = list(self.extra_scopes)
        return payload


@dataclass(frozen=True, kw_only=True)
class SourceRoute:
    references: tuple[SourceReference, ...] = ()
    preferred: tuple[SourceScore, ...] = ()
    candidates: tuple[SourceScore, ...] = ()

    @property
    def has_preferred(self) -> bool:
        return bool(self.preferred)

    def preferred_ids(self, limit: int = MAX_PREFERRED_SOURCES) -> list[UUID]:
        ids: list[UUID] = []
        for entry in self.preferred[: max(1, int(limit))]:
            try:
                ids.append(UUID(str(entry.source_id)))
            except (ValueError, TypeError, AttributeError):
                continue
        return ids

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "references": [ref.to_public_dict() for ref in self.references[:6]],
            "preferred": [entry.to_public_dict() for entry in self.preferred[:5]],
            "candidates": [entry.to_public_dict() for entry in self.candidates[:5]],
            "global_fallback": not self.has_preferred,
        }


def profile_from_source(
    source_id: str,
    name: str,
    *,
    title: str = "",
    document_type: str = "",
    section_terms: list[str] | tuple[str, ...] = (),
    summary: str = "",
) -> SourceProfile:
    """Perfil determinístico desde el nombre/título; sin LLM."""
    declared = tuple(parse_declared_references(name, title=title))
    normalized = normalize_source_name(f"{name} {title}")
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9]{3,}", normalized):
        if token not in _TERM_STOPWORDS and token not in terms:
            terms.append(token)
    for term in section_terms or ():
        value = normalize_source_name(str(term))
        for token in re.findall(r"[a-z0-9]{3,}", value):
            if token not in terms:
                terms.append(token)
    return SourceProfile(
        source_id=str(source_id),
        name=str(name or ""),
        title=str(title or ""),
        document_type=str(document_type or "").lower(),
        declared_references=declared,
        terms=tuple(terms[:24]),
        summary=str(summary or ""),
    )


def _query_terms(query: str) -> set[str]:
    normalized = normalize_source_name(query)
    return {
        token
        for token in re.findall(r"[a-z0-9]{4,}", normalized)
        if token not in _TERM_STOPWORDS
    }


def _query_wants_rule(query: str, views: Any | None) -> bool:
    if _RULE_QUESTION_RE.search(query or ""):
        return True
    if views is not None:
        try:
            from src.rag.longcontext.roles import AnchorRole

            return any(
                str(getattr(anchor, "role", "")) == AnchorRole.RULE_ANCHOR.value
                for anchor in getattr(views, "anchors", ()) or ()
            )
        except Exception:  # noqa: BLE001
            return False
    return False


def route_sources(
    query: str,
    sources: list[SourceProfile] | tuple[SourceProfile, ...],
    *,
    views: Any | None = None,
    max_preferred: int = MAX_PREFERRED_SOURCES,
    min_score: float = MIN_PREFERRED_SCORE,
) -> SourceRoute:
    """Puntúa fuentes contra la consulta. No busca chunks: sólo rankea fuentes."""
    references = extract_source_references(query)
    if not sources:
        return SourceRoute(references=tuple(references))
    requested_kinds = {reference.kind for reference in references}
    query_terms = _query_terms(query)
    wants_rule = _query_wants_rule(query, views)
    wants_example = any(word in (query or "").lower() for word in _EXAMPLE_HINTS)

    scored: list[SourceScore] = []
    for profile in sources:
        score = 0.0
        reasons: list[str] = []
        matched: list[str] = []
        extra: list[str] = []

        for reference in references:
            if reference_matches_source(
                reference, profile.name, title=profile.title
            ):
                score += 3.0
                matched.append(reference.label)
                reasons.append(f"{reference.label}: coincide con la fuente")

        for declared in profile.declared_references:
            if declared.label in matched:
                continue
            requested_same_kind = [
                ref for ref in references if ref.kind == declared.kind
            ]
            if requested_same_kind:
                if any(ref.value == declared.value for ref in requested_same_kind):
                    continue  # es una referencia pedida (ya sumó arriba)
                score -= 2.0
                extra.append(declared.label)
                reasons.append(f"scope {declared.label} no pedido (-2.0)")
            else:
                score -= 1.0
                extra.append(declared.label)
                reasons.append(f"qualifier {declared.label} extra (-1.0)")

        haystack = normalize_source_name(f"{profile.name} {profile.title}")
        if wants_rule and any(hint in haystack for hint in _RULE_HINTS):
            score += 1.2
            reasons.append("documento de reglas/spec para pregunta de regla")
        if not wants_example and any(hint in haystack for hint in _EXAMPLE_HINTS):
            score -= 0.8
            reasons.append("documento de ejemplos no pedido (-0.8)")
        if profile.document_type in ("rules", "spec", "specification") and wants_rule:
            score += 0.4
            reasons.append("tipo de documento: reglas")

        overlap = len(query_terms & set(profile.terms))
        if overlap:
            bonus = min(1.0, overlap / 4.0)
            score += bonus
            reasons.append(f"términos en común con la fuente: {overlap}")

        if score != 0.0 or matched:
            scored.append(
                SourceScore(
                    source_id=profile.source_id,
                    name=profile.display_name or profile.name,
                    score=round(score, 4),
                    reasons=tuple(reasons),
                    matched_references=tuple(matched),
                    extra_scopes=tuple(extra),
                )
            )

    scored.sort(key=lambda entry: entry.score, reverse=True)
    preferred = [entry for entry in scored if entry.score >= float(min_score)][
        : max(1, int(max_preferred))
    ]
    preferred_ids = {entry.source_id for entry in preferred}
    candidates = [entry for entry in scored if entry.source_id not in preferred_ids]
    return SourceRoute(
        references=tuple(references),
        preferred=tuple(preferred),
        candidates=tuple(candidates),
    )


async def load_source_profiles(
    organization_id: UUID,
    *,
    source_ids: list[UUID] | None = None,
    knowledge_base_id: UUID | None = None,
    limit: int = 200,
) -> list[SourceProfile]:
    """Perfiles desde `kb_sources` (fail-soft: sin DB devuelve [])."""
    try:
        from sqlalchemy import bindparam
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            query = (
                "SELECT id::text, name, COALESCE(type, '') "
                "FROM kb_sources WHERE organization_id = :oid "
            )
            params: dict[str, Any] = {"oid": str(organization_id)}
            if source_ids:
                query += "AND id::text IN :ids "
            if knowledge_base_id is not None:
                query += "AND knowledge_base_id = :kb "
                params["kb"] = str(knowledge_base_id)
            query += "ORDER BY created_at DESC LIMIT :limit"
            params["limit"] = max(1, int(limit))
            statement = sql_text(query)
            if source_ids:
                statement = statement.bindparams(bindparam("ids", expanding=True))
                params["ids"] = [str(source_id) for source_id in source_ids]
            rows = (await session.execute(statement, params)).fetchall()
            return [
                profile_from_source(
                    str(row[0]),
                    str(row[1] or ""),
                    document_type=str(row[2] or ""),
                )
                for row in rows
            ]
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001 — el routing nunca rompe el retrieval
        logger.warning("Source profiles lookup failed", error=str(exc)[:150])
        return []


__all__ = [
    "MAX_PREFERRED_SOURCES",
    "MIN_PREFERRED_SCORE",
    "SourceProfile",
    "SourceRoute",
    "SourceScore",
    "load_source_profiles",
    "profile_from_source",
    "route_sources",
]
