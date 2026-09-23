# =============================================================================
# Company Discovery — Entity Resolution Engine (§4/§5)
# =============================================================================
# Estrategia en capas, de determinista a interpretativa:
#   1. exact canonical match
#   2. alias match
#   3. technical identifier match
#   4. deterministic normalization (acentos, separadores, mayúsculas)
#   5. abbreviation / acronym match (ADM ~ Agency Debit Memo)
#   6. semantic similarity (opcional, requiere embedder inyectado)
#   7. JEV/LLM SOLO si la ambigüedad persiste — y su salida sigue siendo
#      sugerencia: nunca fusiona entidades por sí sola.
#
# Regla dura: si dos o más candidatos compiten, NO se fusiona. Se marca
# ambiguo y se emite una sugerencia para revisión humana.
#
# Cada resultado registra `reason` y `strategy`: se puede auditar por qué se
# resolvió (o no) un candidato.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable
from uuid import UUID

from src.core.domain.company_discovery import EntityCandidatePayload
from src.core.domain.company_graph import CompanyEntity

# Separación mínima entre el mejor y el segundo mejor para fusionar.
_AMBIGUITY_MARGIN = 0.08

_LEGAL_SUFFIXES = frozenset(
    {"sa", "sac", "srl", "ltda", "lt", "inc", "llc", "ltd", "corp", "gmbh", "spa"}
)

# Sufijos legales con puntuación ("S.A.", "S.A.C.", "S.R.L.") se eliminan antes
# de tokenizar: si no, quedan como tokens sueltos ("s", "a").
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:s\.?a\.?c?|s\.?r\.?l\.?|ltda|inc|llc|ltd|corp|gmbh|spa)\.?$"
)

# Palabras vacías que no distinguen identidad.
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "de", "del", "la", "el", "los", "las", "y", "para"}
)


class ResolutionStrategy(StrEnum):
    EXACT_CANONICAL = "exact_canonical"
    ALIAS = "alias"
    TECHNICAL_IDENTIFIER = "technical_identifier"
    NORMALIZED = "normalized"
    ABBREVIATION = "abbreviation"
    SEMANTIC = "semantic"
    JUDGE_ADJUDICATED = "judge_adjudicated"
    NONE = "none"


@dataclass(frozen=True, kw_only=True)
class ResolutionOutcome:
    strategy: ResolutionStrategy
    matched_id: UUID | None = None
    matched_name: str = ""
    score: float = 0.0
    reason: str = ""
    ambiguous: bool = False
    alternatives: tuple[UUID, ...] = ()
    candidates: tuple[dict, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.matched_id is not None and not self.ambiguous

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "matched_id": str(self.matched_id) if self.matched_id else None,
            "matched_name": self.matched_name,
            "score": self.score,
            "reason": self.reason,
            "ambiguous": self.ambiguous,
            "alternatives": [str(item) for item in self.alternatives],
        }


def normalize_business_name(value: str) -> str:
    """Normalización determinista: sin acentos, sin puntuación, sin artículos."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = " ".join(text.lower().split())
    text = _LEGAL_SUFFIX_RE.sub("", text).strip()
    cleaned = "".join(
        ch if (ch.isalnum() or ch.isspace()) else " " for ch in text
    )
    tokens = [tok for tok in cleaned.split() if tok and tok not in _STOPWORDS]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def acronym_of(name: str) -> str:
    """Siglas de un nombre: Agency Debit Memo -> adm."""
    tokens = [tok for tok in normalize_business_name(name).split() if tok]
    return "".join(tok[0] for tok in tokens)


def _keywords(value: str) -> set[str]:
    return {tok for tok in normalize_business_name(value).split() if len(tok) > 2}


@dataclass
class _Scored:
    entity: CompanyEntity
    score: float
    strategy: ResolutionStrategy
    reason: str


@dataclass
class EntityResolutionEngine:
    """Resuelve un candidato contra las entidades existentes del tenant.

    `embedder` y `judge` son opcionales y se inyectan: sin ellos el motor es
    100% determinista. El `judge` solo desambigua; nunca confirma.
    """

    abbreviation_lexicon: dict[str, str] = field(default_factory=dict)
    semantic_threshold: float = 0.86
    semantic_margin: float = 0.04

    def resolve(
        self,
        payload: EntityCandidatePayload,
        existing: list[CompanyEntity] | tuple[CompanyEntity, ...],
    ) -> ResolutionOutcome:
        pool = [
            entity
            for entity in existing
            if entity.entity_type == payload.entity_type
        ]
        if not pool:
            return ResolutionOutcome(
                strategy=ResolutionStrategy.NONE,
                reason="kind:new_entity",
                score=0.0,
            )

        # Se evalúan TODAS las capas deterministas y luego se decide: así una
        # entidad que gana por exact match y otra que gana por normalización
        # producen la ambigüedad correcta en lugar de resolverse por orden.
        scored: list[_Scored] = []
        for layer in (
            self._exact,
            self._alias,
            self._technical,
            self._normalized,
            self._abbreviation,
        ):
            scored.extend(item for item in layer(payload, pool) if item.score > 0)
        best_per_entity: dict[UUID, _Scored] = {}
        for item in scored:
            current = best_per_entity.get(item.entity.id)
            if current is None or item.score > current.score:
                best_per_entity[item.entity.id] = item
        if not best_per_entity:
            return ResolutionOutcome(
                strategy=ResolutionStrategy.NONE,
                reason="no_deterministic_match",
                score=0.0,
            )
        return self._decide(list(best_per_entity.values()), payload)

    # -- capas deterministas ------------------------------------------
    def _exact(
        self, payload: EntityCandidatePayload, pool: list[CompanyEntity]
    ) -> list[_Scored]:
        target = payload.canonical_name.strip().lower()
        return [
            _Scored(entity, 1.0, ResolutionStrategy.EXACT_CANONICAL, "canonical_name_exact")
            for entity in pool
            if entity.canonical_name.strip().lower() == target
        ]

    def _alias(
        self, payload: EntityCandidatePayload, pool: list[CompanyEntity]
    ) -> list[_Scored]:
        wanted = {payload.canonical_name.strip().lower()}
        wanted |= {alias.strip().lower() for alias in payload.aliases if alias.strip()}
        results: list[_Scored] = []
        for entity in pool:
            aliases = {alias.strip().lower() for alias in entity.aliases}
            if wanted & aliases:
                results.append(
                    _Scored(entity, 0.95, ResolutionStrategy.ALIAS, "alias_match")
                )
        return results

    def _technical(
        self, payload: EntityCandidatePayload, pool: list[CompanyEntity]
    ) -> list[_Scored]:
        if not payload.technical_identifiers:
            return []
        wanted = {item.strip().lower() for item in payload.technical_identifiers}
        results: list[_Scored] = []
        for entity in pool:
            identifiers = {
                str(item).strip().lower()
                for item in (entity.metadata or {}).get("technical_identifiers") or ()
            }
            # El propio nombre técnico cuenta como identificador.
            identifiers.add(entity.canonical_name.strip().lower())
            if wanted & identifiers:
                results.append(
                    _Scored(
                        entity,
                        0.93,
                        ResolutionStrategy.TECHNICAL_IDENTIFIER,
                        "technical_identifier_match",
                    )
                )
        return results

    def _normalized(
        self, payload: EntityCandidatePayload, pool: list[CompanyEntity]
    ) -> list[_Scored]:
        target = normalize_business_name(payload.canonical_name)
        if not target:
            return []
        results: list[_Scored] = []
        for entity in pool:
            if normalize_business_name(entity.canonical_name) == target:
                results.append(
                    _Scored(
                        entity, 0.9, ResolutionStrategy.NORMALIZED, "normalized_equal"
                    )
                )
                continue
            if normalize_business_name(entity.display_name) == target:
                results.append(
                    _Scored(
                        entity,
                        0.88,
                        ResolutionStrategy.NORMALIZED,
                        "normalized_display_name_equal",
                    )
                )
        return results

    def _abbreviation(
        self, payload: EntityCandidatePayload, pool: list[CompanyEntity]
    ) -> list[_Scored]:
        """Siglas deterministas en ambas direcciones: ADM <-> Agency Debit Memo.

        Cubre el caso del spec ("ADM", "Agency Debit Memo", "agency debit memo"
        apuntan al mismo Concept) sin fuzzy matching ni LLM.
        """
        results: list[_Scored] = []
        raw = payload.canonical_name.strip().lower()
        declared = (payload.abbreviation or "").strip().lower()
        candidate_acronym = acronym_of(payload.canonical_name)
        lexicon_meaning = self.abbreviation_lexicon.get(raw, "")
        for entity in pool:
            entity_acronym = acronym_of(entity.canonical_name)
            entity_norm = normalize_business_name(entity.canonical_name)
            entity_compact = entity_norm.replace(" ", "")
            if declared and entity_acronym and declared == entity_acronym:
                reason = "declared_abbreviation_expands_to_entity"
            elif raw and entity_acronym and raw == entity_acronym:
                reason = "candidate_is_entity_acronym"
            elif candidate_acronym and candidate_acronym == entity_compact:
                reason = "candidate_acronym_expands_to_entity"
            elif lexicon_meaning and normalize_business_name(lexicon_meaning) == entity_norm:
                reason = "lexicon_expansion_match"
            else:
                continue
            results.append(
                _Scored(entity, 0.85, ResolutionStrategy.ABBREVIATION, reason)
            )
        return results

    # -- semántico / judge (opcionales) --------------------------------
    def semantic_scores(
        self,
        payload: EntityCandidatePayload,
        pool: list[CompanyEntity],
        similarities: dict[UUID, float],
    ) -> list[_Scored]:
        """Similitud semántica precomputada (embedder externo).

        Se inyectan scores ya calculados para que el motor siga siendo
        determinista y testeable sin depender de un proveedor.
        """
        return [
            _Scored(
                entity,
                round(float(similarities[entity.id]), 4),
                ResolutionStrategy.SEMANTIC,
                "semantic_similarity",
            )
            for entity in pool
            if entity.id in similarities
            and float(similarities[entity.id]) >= self.semantic_threshold
        ]

    def adjudicate(
        self,
        options: list[CompanyEntity],
        judge: Callable[[str, list[CompanyEntity]], UUID | None],
        *,
        question: str,
    ) -> ResolutionOutcome:
        """Desambiguación por JEV/LLM. Nunca fusiona: la elección queda como
        sugerencia (VALIDATED requiere revisión humana)."""
        if len(options) < 2:
            return ResolutionOutcome(
                strategy=ResolutionStrategy.NONE, reason="nothing_to_adjudicate"
            )
        try:
            chosen = judge(question, options)
        except Exception:  # noqa: BLE001 - la desambiguación nunca bloquea
            chosen = None
        if chosen is None:
            return ResolutionOutcome(
                strategy=ResolutionStrategy.NONE,
                reason="judge_abstained",
                ambiguous=True,
                candidates=tuple(self._describe(options)),
            )
        match = next((item for item in options if item.id == chosen), None)
        if match is None:
            return ResolutionOutcome(
                strategy=ResolutionStrategy.NONE,
                reason="judge_choice_out_of_options",
                ambiguous=True,
                candidates=tuple(self._describe(options)),
            )
        return ResolutionOutcome(
            strategy=ResolutionStrategy.JUDGE_ADJUDICATED,
            matched_id=match.id,
            matched_name=match.canonical_name,
            score=0.5,
            reason="judge_adjudicated_requires_validation",
            ambiguous=False,
            alternatives=tuple(str(item.id) for item in options if item.id != chosen),
        )

    # -- decisión ------------------------------------------------------
    def _decide(
        self, scored: list[_Scored], payload: EntityCandidatePayload
    ) -> ResolutionOutcome | None:
        scored.sort(key=lambda item: (-item.score, item.entity.canonical_name))
        best = scored[0]
        if len(scored) == 1:
            return ResolutionOutcome(
                strategy=best.strategy,
                matched_id=best.entity.id,
                matched_name=best.entity.canonical_name,
                score=best.score,
                reason=best.reason,
            )
        second = scored[1]
        if best.score - second.score >= _AMBIGUITY_MARGIN:
            return ResolutionOutcome(
                strategy=best.strategy,
                matched_id=best.entity.id,
                matched_name=best.entity.canonical_name,
                score=best.score,
                reason=best.reason,
                alternatives=tuple(str(item.entity.id) for item in scored[1:]),
            )
        # Empate: nunca fusionar automáticamente (§4).
        return ResolutionOutcome(
            strategy=ResolutionStrategy.NONE,
            score=best.score,
            reason=f"ambiguous:{best.entity.canonical_name}|{second.entity.canonical_name}",
            ambiguous=True,
            alternatives=tuple(str(item.entity.id) for item in scored),
            candidates=tuple(self._describe([item.entity for item in scored])),
        )

    @staticmethod
    def _describe(entities: list[CompanyEntity]) -> list[dict]:
        return [
            {
                "id": str(entity.id),
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
                "status": entity.status.value,
                "aliases": list(entity.aliases),
                "keywords": sorted(_keywords(entity.canonical_name))[:6],
            }
            for entity in entities[:6]
        ]
