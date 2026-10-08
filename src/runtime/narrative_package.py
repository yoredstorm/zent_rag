# =============================================================================
# Paquete narrativo final — Doc:N es presentación, evidence_id es la identidad.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from src.runtime.evidence import EvidenceItem, EvidenceSelection, render_evidence

_DOC_RE = re.compile(r"\[(?:Doc|doc)\s*[: ]?\s*(\d{1,3})\b\]?")
_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñ]{4,}", re.IGNORECASE)

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
UNSUPPORTED = "UNSUPPORTED"
UNCITED = "UNCITED"


@dataclass(frozen=True)
class CitationPackage:
    """Mapa estable Doc:N → evidence_id de UNA generación."""

    package_id: str
    package_version: int
    evidence_ids: tuple[str, ...]
    doc_number_to_evidence_id: dict[int, str]
    evidence_id_to_doc_number: dict[str, int]
    created_after_registry_version: str

    def evidence_id_for_doc(self, number: int) -> str:
        return self.doc_number_to_evidence_id.get(int(number), "")


@dataclass(frozen=True)
class FinalNarrativeEvidencePackage:
    """Lo único que el modelo puede citar en la generación final."""

    citation: CitationPackage
    rendered_context: str
    items: tuple[EvidenceItem, ...] = ()

    @property
    def package_version(self) -> int:
        return self.citation.package_version


@dataclass
class NarrativeCitationBinding:
    answer: str
    cited_evidence_ids: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]
    invalid_doc_numbers: tuple[int, ...]
    supports: tuple[dict, ...] = ()
    verification: str = ""
    grounding: str = ""
    consistent: bool = True


def freeze_narrative_package(
    selection: EvidenceSelection,
    *,
    version: int,
    registry_version: str,
    package_id: str = "final",
) -> FinalNarrativeEvidencePackage:
    """Paquete nuevo. La numeración Doc empieza en 1 para ESTA selección."""
    ids: list[str] = []
    doc_to_id: dict[int, str] = {}
    id_to_doc: dict[str, int] = {}
    for index, item in enumerate(selection.items, start=1):
        evidence_id = str(item.evidence_id or "")
        if not evidence_id:
            continue
        ids.append(evidence_id)
        doc_to_id[index] = evidence_id
        id_to_doc[evidence_id] = index
    citation = CitationPackage(
        package_id=package_id,
        package_version=int(version),
        evidence_ids=tuple(ids),
        doc_number_to_evidence_id=doc_to_id,
        evidence_id_to_doc_number=id_to_doc,
        created_after_registry_version=str(registry_version or ""),
    )
    return FinalNarrativeEvidencePackage(
        citation=citation,
        rendered_context=render_evidence(selection, tag_style="citations"),
        items=tuple(selection.items),
    )


def parse_doc_numbers(answer: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for raw in _DOC_RE.findall(answer or ""):
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number not in numbers:
            numbers.append(number)
    return tuple(numbers)


def strip_invalid_doc_citations(answer: str, invalid: Iterable[int]) -> str:
    """Quita sólo las marcas inválidas. No inventa una cita de reemplazo."""
    banned = {int(number) for number in invalid}

    def _replace(match: re.Match[str]) -> str:
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            return match.group(0)
        if number in banned:
            return ""
        return match.group(0)

    cleaned = _DOC_RE.sub(_replace, answer or "")
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "")}


def _item_text(package: FinalNarrativeEvidencePackage, evidence_id: str) -> str:
    for item in package.items:
        if item.evidence_id == evidence_id:
            return f"{item.title or ''}\n{item.content or ''}"
    return ""


def _sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (answer or "").strip())
    return [part.strip() for part in parts if len(part.strip()) >= 24]


def narrative_claim_support(
    answer: str,
    package: FinalNarrativeEvidencePackage,
) -> tuple[dict, ...]:
    """Soporte léxico de cada afirmación contra el paquete que vio el modelo."""
    supports: list[dict] = []
    for sentence in _sentences(answer):
        numbers = parse_doc_numbers(sentence)
        claim_tokens = _tokens(sentence)
        if numbers:
            for number in numbers:
                evidence_id = package.citation.evidence_id_for_doc(number)
                if not evidence_id:
                    supports.append(
                        {
                            "claim": sentence[:240],
                            "status": UNSUPPORTED,
                            "doc_number": number,
                            "evidence_id": "",
                        }
                    )
                    continue
                overlap = claim_tokens & _tokens(_item_text(package, evidence_id))
                status = SUPPORTED if len(overlap) >= 2 else PARTIAL if overlap else UNSUPPORTED
                supports.append(
                    {
                        "claim": sentence[:240],
                        "status": status,
                        "doc_number": number,
                        "evidence_id": evidence_id,
                    }
                )
            continue
        best_id = ""
        best_overlap = 0
        for evidence_id in package.citation.evidence_ids:
            overlap = len(claim_tokens & _tokens(_item_text(package, evidence_id)))
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = evidence_id
        if best_id and best_overlap >= 2:
            supports.append(
                {
                    "claim": sentence[:240],
                    "status": UNCITED,
                    "doc_number": None,
                    "evidence_id": best_id,
                }
            )
    return tuple(supports)


def narrative_verification(
    supports: Sequence[dict],
    invalid_doc_numbers: Sequence[int],
) -> tuple[str, str]:
    """Verificación narrativa. No exige DecisionEnvelope."""
    if invalid_doc_numbers:
        return "CITATION_INVALID", "INCOMPLETE"
    if not supports:
        return "UNVERIFIED", "UNKNOWN"
    cited_claims = [
        item for item in supports if str(item.get("status") or "") != UNCITED
    ]
    if any(str(item.get("status") or "") == UNSUPPORTED for item in cited_claims):
        return "PARTIAL", "PARTIAL"
    if cited_claims and all(
        str(item.get("status") or "") == SUPPORTED for item in cited_claims
    ):
        return "VERIFIED_GROUNDED", "COMPLETE"
    return "PARTIAL", "PARTIAL"


def bind_narrative_answer(
    answer: str,
    package: FinalNarrativeEvidencePackage,
) -> NarrativeCitationBinding:
    """Resuelve Doc:N contra el paquete, repara citas inválidas y marca uso."""
    invalid = tuple(
        number
        for number in parse_doc_numbers(answer)
        if not package.citation.evidence_id_for_doc(number)
    )
    repaired = strip_invalid_doc_citations(answer, invalid) if invalid else (answer or "")
    cited = tuple(
        package.citation.evidence_id_for_doc(number)
        for number in parse_doc_numbers(repaired)
        if package.citation.evidence_id_for_doc(number)
    )
    supports = narrative_claim_support(repaired, package)
    used: list[str] = []
    for evidence_id in cited:
        if evidence_id not in used:
            used.append(evidence_id)
    for support in supports:
        evidence_id = str(support.get("evidence_id") or "")
        status = str(support.get("status") or "")
        if evidence_id and status in {SUPPORTED, PARTIAL, UNCITED} and evidence_id not in used:
            used.append(evidence_id)
    verification, grounding = narrative_verification(supports, ())
    numbers = parse_doc_numbers(repaired)
    resolved_now = {
        package.citation.evidence_id_for_doc(number)
        for number in numbers
        if package.citation.evidence_id_for_doc(number)
    }
    consistent = resolved_now == set(cited) and all(
        package.citation.evidence_id_for_doc(number) for number in numbers
    )
    return NarrativeCitationBinding(
        answer=repaired,
        cited_evidence_ids=cited,
        used_evidence_ids=tuple(used),
        invalid_doc_numbers=invalid,
        supports=supports,
        verification=verification,
        grounding=grounding,
        consistent=consistent,
    )


def citation_trace_status(binding: NarrativeCitationBinding) -> str:
    """ERROR si la respuesta cita Doc:N y la traza no marca esas evidencias."""
    if not binding.consistent:
        return "ERROR"
    numbers = parse_doc_numbers(binding.answer)
    if numbers and not binding.cited_evidence_ids:
        return "ERROR"
    return "OK"


def narrative_flow_detail(
    *,
    retrieved: int,
    selected: int,
    used: int,
    cited: int,
    documents_used: int,
    decision_evidence: int = 0,
) -> str:
    return (
        "Evidencia narrativa:\n"
        f"Recuperadas: {retrieved}\n"
        f"Seleccionadas: {selected}\n"
        f"Usadas en explicación: {used}\n"
        f"Citadas: {cited}\n"
        f"Documentos usados: {documents_used}\n"
        f"decision_evidence={decision_evidence}"
    )
