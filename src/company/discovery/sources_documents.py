# =============================================================================
# Company Discovery — fuentes documentales y temporales (§3/§14)
# =============================================================================
# Extracción DETERMINISTA de documentos: patrones explícitos de definición,
# identificadores técnicos y fechas de vigencia. Nada de LLM: si el documento
# no lo dice de forma localizable, no se propone.
#
# Estas fuentes son interpretativas (un documento puede estar desactualizado),
# así que producen candidatos con soporte bajo que requieren validación.
# =============================================================================
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from src.company.discovery.source_base import DiscoverySource
from src.company.discovery.source_loaders import (
    load_document_blocks,
    load_document_versions,
    load_structured_documents,
)
from src.company.discovery.sources_structured import _support
from src.core.domain.company_discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    EntityCandidatePayload,
    EntityRef,
    GapKind,
    KnowledgeGapPayload,
    MappingCandidatePayload,
    TemporalCandidatePayload,
)

# "X means Y" / "X se define como Y" — definición explícita.
_DEFINITION_PATTERNS = (
    re.compile(
        r"(?P<term>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\s\-/]{2,60}?)\s+"
        r"(?:means|refers to|is defined as|stands for)\s+"
        r"(?P<definition>[^.\n]{5,220}\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<term>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\s\-/]{2,60}?)\s+"
        r"(?:se define como|significa|se refiere a|corresponde a)\s+"
        r"(?P<definition>[^.\n]{5,220}\.)",
        re.IGNORECASE,
    ),
)

# Identificadores técnicos: SCHEMA.TABLE.FIELD, TABLE.FIELD, A1672STO0.
_TECHNICAL_RE = re.compile(
    r"\b(?P<identifier>[A-Z][A-Z0-9_]{2,}(?:\.[A-Z][A-Z0-9_]{1,}){0,2})\b"
)

# Fechas de vigencia explícitas.
_EFFECTIVE_RE = re.compile(
    r"(?P<subject>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\s\-]{2,60}?)\s+"
    r"(?:effective(?:\s+from)?|vigente\s+desde|entra\s+en\s+vigencia(?:\s+el)?|"
    r"valid\s+from)\s*:?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4})",
    re.IGNORECASE,
)

_POLICY_HINTS = (
    "policy",
    "política",
    "politica",
    "póliza",
    "poliza",
    "procedure",
    "procedimiento",
    "norma",
    "standard",
    "regla",
    "rule",
)


def parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def extract_definitions(text: str) -> list[tuple[str, str]]:
    """Definiciones explícitas (término, definición) en un bloque."""
    found: list[tuple[str, str]] = []
    for pattern in _DEFINITION_PATTERNS:
        for match in pattern.finditer(text or ""):
            term = " ".join(match.group("term").split()).strip()
            definition = " ".join(match.group("definition").split()).strip()
            if len(term) < 3 or not definition:
                continue
            if (term, definition) not in found:
                found.append((term, definition))
    return found[:10]


def extract_technical_identifiers(text: str) -> list[str]:
    """Identificadores técnicos visibles en el documento."""
    found: list[str] = []
    for match in _TECHNICAL_RE.finditer(text or ""):
        identifier = match.group("identifier")
        if len(identifier) < 4 or identifier.isdigit():
            continue
        if identifier not in found:
            found.append(identifier)
    return found[:20]


def extract_effective_dates(text: str) -> list[tuple[str, datetime | None]]:
    found: list[tuple[str, datetime | None]] = []
    for match in _EFFECTIVE_RE.finditer(text or ""):
        subject = " ".join(match.group("subject").split()).strip()
        if len(subject) < 3:
            continue
        entry = (subject, parse_date(match.group("date")))
        if entry not in found:
            found.append(entry)
    return found[:10]


def entity_type_for_title(title: str) -> str:
    lowered = (title or "").lower()
    return "policy" if any(hint in lowered for hint in _POLICY_HINTS) else "document"


def entity_type_for_identifier(identifier: str) -> str:
    return "field" if identifier.count(".") >= 2 or _looks_like_column(identifier) else "table"


def _looks_like_column(identifier: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", identifier or ""))


class DocumentConceptSource(DiscoverySource):
    """Conceptos, identificadores técnicos y vigencias desde documentos."""

    source_kind = DiscoverySourceKind.DOCUMENT
    name = "document_concepts"

    def __init__(
        self,
        *,
        loader_documents=load_structured_documents,
        loader_blocks=load_document_blocks,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_documents = loader_documents
        self._load_blocks = loader_blocks

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        documents = await self._load_documents(organization_id, self.max_items)
        if not documents:
            return []
        titles = {str(doc.get("id")): str(doc.get("title") or "") for doc in documents}
        blocks = await self._load_blocks(
            organization_id, [doc.get("id") for doc in documents], self.max_items * 8
        )

        candidates: list[DiscoveryCandidate] = []
        definitions: dict[str, list[tuple[str, str, str]]] = {}
        identifiers: dict[str, list[str]] = {}
        for block in blocks:
            text = str(block.get("text") or "")
            document_id = str(block.get("document_id") or "")
            title = titles.get(document_id, "")
            block_ref = str(block.get("id"))
            for term, definition in extract_definitions(text):
                definitions.setdefault(term.lower(), []).append(
                    (term, definition, block_ref)
                )
            for identifier in extract_technical_identifiers(text):
                identifiers.setdefault(identifier, [])
                if block_ref not in identifiers[identifier]:
                    identifiers[identifier].append(block_ref)

        for key, entries in definitions.items():
            term = entries[0][0]
            definition = entries[0][1]
            refs = tuple(ref for _t, _d, ref in entries[:5])
            distinct_docs = len({ref for ref in refs})
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=EntityCandidatePayload(
                        entity_type="concept",
                        canonical_name=term,
                        display_name=term,
                        description=definition,
                        domain="business",
                        aliases=(term,),
                        keyword=key,
                    ).to_dict(),
                    title=term,
                    summary=definition[:200],
                    support=_support(
                        structural=False,
                        observations=len(entries),
                        distinct_sources=max(1, distinct_docs),
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=refs[0],
                        detail={"document": titles.get("", ""), "definition": definition},
                        excerpt=definition[:400],
                    ),
                    workspace_id=workspace_id,
                )
            )
            # Definiciones divergentes del mismo término -> conflicto (§12).
            distinct_definitions = {definition for _t, definition, _r in entries}
            if len(distinct_definitions) > 1:
                gap = KnowledgeGapPayload(
                    gap_kind=GapKind.CONTRADICTORY_DEFINITION,
                    subject=term,
                    detail=f"{len(distinct_definitions)} different definitions found",
                    evidence_summary=refs,
                )
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.KNOWLEDGE_GAP,
                        payload=gap.to_dict(),
                        title=f"Gap: {term} has contradictory definitions",
                        summary=gap.detail,
                        support=_support(
                            structural=False,
                            observations=len(entries),
                            distinct_sources=max(1, distinct_docs),
                        ),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=refs[0],
                            detail={"definitions": sorted(distinct_definitions)[:3]},
                        ),
                        workspace_id=workspace_id,
                    )
                )

        for identifier, refs in identifiers.items():
            entity_type = entity_type_for_identifier(identifier)
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=EntityCandidatePayload(
                        entity_type=entity_type,
                        canonical_name=identifier,
                        display_name=identifier,
                        domain="data",
                        technical_identifiers=(identifier,),
                        keyword=identifier.lower(),
                    ).to_dict(),
                    title=identifier,
                    summary=f"technical identifier referenced in {len(refs)} block(s)",
                    support=_support(
                        structural=False,
                        observations=len(refs),
                        distinct_sources=1,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind, ref=refs[0]
                    ),
                    workspace_id=workspace_id,
                )
            )

        # Término definido en el mismo bloque que un identificador técnico.
        for block in blocks:
            text = str(block.get("text") or "")
            block_ref = str(block.get("id"))
            terms = [term for term, _definition in extract_definitions(text)]
            found_ids = extract_technical_identifiers(text)
            for term in terms:
                for identifier in found_ids:
                    payload = MappingCandidatePayload(
                        concept_ref=EntityRef("concept", term),
                        target_ref=EntityRef(
                            entity_type_for_identifier(identifier), identifier
                        ),
                    )
                    candidates.append(
                        self.build_candidate(
                            organization_id=organization_id,
                            kind=CandidateKind.MAPPING,
                            payload=payload.to_dict(),
                            title=f"{term} MAPS_TO {identifier}",
                            summary="document states the term and the identifier together",
                            support=_support(
                                structural=False, observations=1, distinct_sources=1
                            ),
                            evidence=DiscoveryEvidence(
                                source_kind=self.source_kind,
                                ref=block_ref,
                                excerpt=text[:200],
                            ),
                            workspace_id=workspace_id,
                        )
                    )

        for block in blocks:
            text = str(block.get("text") or "")
            block_ref = str(block.get("id"))
            for subject, effective_from in extract_effective_dates(text):
                payload = TemporalCandidatePayload(
                    subject_ref=EntityRef(
                        entity_type_for_title(subject), subject
                    ),
                    effective_from=effective_from,
                    note="explicit effective date in document",
                )
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.TEMPORAL,
                        payload=payload.to_dict(),
                        title=f"Effective date: {subject}",
                        summary=f"{subject} effective from {effective_from}",
                        support=_support(
                            structural=False, observations=1, distinct_sources=1
                        ),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=block_ref,
                            excerpt=text[:200],
                        ),
                        workspace_id=workspace_id,
                    )
                )
        return candidates


class TemporalVersionSource(DiscoverySource):
    """Versiones de documento: Policy V1 SUPERSEDED_BY Policy V2 (§14)."""

    source_kind = DiscoverySourceKind.DOCUMENT
    name = "temporal_versions"

    def __init__(self, *, loader=load_document_versions, max_items: int | None = None) -> None:
        super().__init__(max_items=max_items)
        self._load = loader

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        rows = await self._load(organization_id, self.max_items)
        by_document: dict[str, list[dict]] = {}
        for row in rows:
            by_document.setdefault(str(row.get("document_id")), []).append(row)

        candidates: list[DiscoveryCandidate] = []
        for document_id, versions in by_document.items():
            ordered = sorted(versions, key=lambda item: int(item.get("version") or 1))
            if len(ordered) < 2:
                continue
            title = str(ordered[-1].get("title") or "").strip()
            if not title:
                continue
            entity_type = entity_type_for_title(title)
            for previous, current in zip(ordered, ordered[1:]):
                previous_version = int(previous.get("version") or 1)
                current_version = int(current.get("version") or 1)
                payload = TemporalCandidatePayload(
                    subject_ref=EntityRef(entity_type, f"{title} v{previous_version}"),
                    superseded_by_ref=EntityRef(
                        entity_type, f"{title} v{current_version}"
                    ),
                    version_label=f"v{previous_version}->v{current_version}",
                    note="later document version exists",
                )
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.TEMPORAL,
                        payload=payload.to_dict(),
                        title=(
                            f"{title} v{previous_version} SUPERSEDED_BY "
                            f"v{current_version}"
                        ),
                        summary="document version chain observed",
                        support=_support(
                            structural=False,
                            observations=2,
                            distinct_sources=1,
                        ),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=str(previous.get("id") or document_id),
                            detail={
                                "document_id": document_id,
                                "change_kind": current.get("change_kind"),
                            },
                        ),
                        workspace_id=workspace_id,
                    )
                )
        return candidates
