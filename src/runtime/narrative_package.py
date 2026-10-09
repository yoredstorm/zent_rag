# =============================================================================
# Paquete narrativo final — Doc:N es presentación, evidence_id es la identidad.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

from src.runtime.evidence import EvidenceItem, EvidenceSelection, render_evidence

_DOC_RE = re.compile(r"\[(?:Doc|doc)\s*[: ]?\s*(\d{1,3})\b\]?")
_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñ]{4,}", re.IGNORECASE)

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
UNSUPPORTED = "UNSUPPORTED"
UNCITED = "UNCITED"
#: Claim sin cita pero con respaldo léxico en el paquete. Es el caso menos grave.
UNCITED_BUT_SUPPORTED = UNCITED
#: Claim que introduce una entidad/categoría/regla que no existe en el paquete
#: que vio el modelo. Es más grave que un claim sin cita: puede ser conocimiento
#: externo presentado como documental.
OUT_OF_PACKAGE_CLAIM = "OUT_OF_PACKAGE_CLAIM"

#: Referencias de dominio con número: «Category 15», «Record 2», «byte 105».
_EXTERNAL_REF_RE = re.compile(
    r"\b(?:categor\w{0,6}|cat|records?|registros?|bytes?|tablas?|tables?|tbl)"
    r"[\s._-]*(\d{1,4})\b",
    re.IGNORECASE,
)
#: Una limitación declarada no es un claim documental: «no encontré respaldo
#: sobre Record 5» no introduce conocimiento externo.
_LIMITATION_RE = re.compile(
    r"\b(?:no\s+(?:encontr[eé]|hay|est[aá]|aparece|contiene|incluye|se\s+encontr)|"
    r"sin\s+(?:respaldo|evidencia|informaci[oó]n)|"
    r"falta\s+(?:informaci[oó]n|evidencia|respaldo))\b",
    re.IGNORECASE,
)
_REF_VARIANTS: dict[str, tuple[str, ...]] = {
    "categoria": ("categoria", "category", "cat"),
    "record": ("record", "registro"),
    "byte": ("byte", "bytes"),
    "tabla": ("tabla", "table", "tbl"),
}


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
    external_claims: tuple[dict, ...] = ()


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


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).lower().strip()


def _package_blob(package: FinalNarrativeEvidencePackage) -> str:
    return _fold(
        "\n".join(
            _item_text(package, evidence_id)
            for evidence_id in package.citation.evidence_ids
        )
    )


def _reference_family(keyword: str) -> str:
    text = _fold(keyword)
    if text.startswith("cat"):
        return "categoria"
    if text.startswith("registro") or text.startswith("record"):
        return "record"
    if text.startswith("byte"):
        return "byte"
    if text.startswith("tabla") or text.startswith("table") or text.startswith("tbl"):
        return "tabla"
    return ""


def _reference_variants(family: str, number: str) -> tuple[str, ...]:
    bases = _REF_VARIANTS.get(family, ())
    forms: list[str] = []
    for base in bases:
        forms.append(f"{base} {number}")
        forms.append(f"{base}{number}")
    return tuple(forms)


def external_reference(
    claim: str,
    package: FinalNarrativeEvidencePackage,
) -> str:
    """Referencia de dominio que el paquete no contiene, o "" si está cubierta.

    «Category 15 is Seasonality.» con un paquete de Fare Class / Footnote
    devuelve «Category 15». Es comparación de texto contra el paquete, no
    opinión sobre el dominio.
    """
    if _LIMITATION_RE.search(claim or ""):
        return ""
    blob = _package_blob(package)
    for match in _EXTERNAL_REF_RE.finditer(claim or ""):
        raw = " ".join(match.group(0).split())
        digits = re.search(r"\d{1,4}", raw)
        if digits is None:
            continue
        keyword = raw[: digits.start()].strip(" ._-")
        family = _reference_family(keyword)
        if not family:
            continue
        variants = _reference_variants(family, digits.group(0))
        if any(_fold(variant) in blob for variant in variants):
            continue
        return raw
    return ""


def _best_overlap(
    claim: str,
    package: FinalNarrativeEvidencePackage,
) -> tuple[str, int]:
    claim_tokens = _tokens(claim)
    best_id = ""
    best_overlap = 0
    for evidence_id in package.citation.evidence_ids:
        overlap = len(claim_tokens & _tokens(_item_text(package, evidence_id)))
        if overlap > best_overlap:
            best_overlap = overlap
            best_id = evidence_id
    return best_id, best_overlap


def _out_of_package_support(
    claim: str,
    reference: str,
    *,
    doc_number: int | None = None,
    evidence_id: str = "",
) -> dict:
    return {
        "claim": claim[:240],
        "status": OUT_OF_PACKAGE_CLAIM,
        "doc_number": doc_number,
        "evidence_id": evidence_id,
        "external_reference": reference,
    }


def _sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (answer or "").strip())
    return [part.strip() for part in parts if len(part.strip()) >= 24]


def _claim_units(answer: str) -> list[str]:
    """Oraciones, filas de tabla y ítems de lista. El corte por punto no ve una tabla."""
    units: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        cleaned = " ".join((text or "").split()).strip(" |")
        if len(cleaned) < 8 or cleaned in seen:
            return
        if set(cleaned) <= set("-:| "):
            return
        seen.add(cleaned)
        units.append(cleaned[:240])

    for raw in (answer or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            add(line.strip("|"))
            continue
        item = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            add(item.group(1))
    prose = re.sub(r"(?m)^\s*\|.*$", " ", answer or "")
    prose = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+.*$", " ", prose)
    for sentence in _sentences(prose):
        add(sentence)
    return units


def narrative_claim_support(
    answer: str,
    package: FinalNarrativeEvidencePackage,
) -> tuple[dict, ...]:
    """Soporte léxico de cada afirmación contra el paquete que vio el modelo.

    Un claim con respaldo pero sin cita queda UNCITED_BUT_SUPPORTED. Un claim
    que introduce una referencia de dominio ausente del paquete (p. ej.
    «Category 15 is Seasonality» sobre evidencia de Fare Class) queda
    OUT_OF_PACKAGE_CLAIM, más grave que la falta de cita.
    """
    supports: list[dict] = []
    for sentence in _claim_units(answer):
        numbers = parse_doc_numbers(sentence)
        reference = external_reference(sentence, package)
        if numbers:
            claim_tokens = _tokens(sentence)
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
                if reference and not overlap:
                    supports.append(
                        _out_of_package_support(
                            sentence,
                            reference,
                            doc_number=number,
                            evidence_id=evidence_id,
                        )
                    )
                    continue
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
        best_id, best_overlap = _best_overlap(sentence, package)
        if best_id and best_overlap >= 2:
            supports.append(
                {
                    "claim": sentence[:240],
                    "status": UNCITED,
                    "doc_number": None,
                    "evidence_id": best_id,
                }
            )
        elif reference:
            supports.append(_out_of_package_support(sentence, reference))
    return tuple(supports)


def _unit_text(text: str) -> str:
    return " ".join((text or "").split()).strip(" |")[:240]


def _is_heading_paragraph(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    stripped = lines[0]
    if stripped.startswith("#"):
        return True
    words = stripped.split()
    return bool(words) and len(words) <= 8 and not stripped.endswith((".", ",", ";"))


def _ungrounded_units(
    paragraph: str, package: FinalNarrativeEvidencePackage
) -> list[tuple[str, str]]:
    """Unidades del párrafo que introducen referencias fuera del paquete."""
    found: list[tuple[str, str]] = []
    for unit in _claim_units(paragraph):
        reference = external_reference(unit, package)
        if not reference:
            continue
        _, overlap = _best_overlap(unit, package)
        if overlap < 2:
            found.append((unit, reference))
    return found


def _strip_units_from_paragraph(paragraph: str, banned: list[str]) -> str:
    banned_set = set(banned)
    kept_lines: list[str] = []
    for raw in (paragraph or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            if _unit_text(line.strip("|")) in banned_set:
                continue
            kept_lines.append(raw)
            continue
        item = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            if _unit_text(item.group(1)) in banned_set:
                continue
            kept_lines.append(raw)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        remaining = [
            sentence.strip()
            for sentence in sentences
            if _unit_text(sentence) not in banned_set
        ]
        if remaining:
            kept_lines.append(" ".join(remaining))
    return "\n".join(kept_lines)


def strip_external_ungrounded(
    answer: str,
    package: FinalNarrativeEvidencePackage,
) -> tuple[str, tuple[dict, ...]]:
    """Trimming determinista de claims externos. Sin segunda generación.

    Si todas las afirmaciones de un párrafo son externas, el párrafo entero
    cae (y su heading si queda huérfano: «Implicación práctica» sin respaldo).
    Si no, sólo caen las oraciones externas.
    """
    text = answer or ""
    if not text.strip():
        return text, ()
    kept: list[str] = []
    removed: list[dict] = []
    for paragraph in re.split(r"\n{2,}", text):
        units = _ungrounded_units(paragraph, package)
        if not units:
            kept.append(paragraph)
            continue
        all_units = _claim_units(paragraph)
        if all_units and len(units) >= len(all_units):
            if kept and _is_heading_paragraph(kept[-1]):
                heading = kept.pop()
                removed.append(
                    {
                        "claim": _unit_text(heading),
                        "status": OUT_OF_PACKAGE_CLAIM,
                        "doc_number": None,
                        "evidence_id": "",
                        "external_reference": "",
                        "removed_heading": True,
                    }
                )
            for unit, reference in units:
                removed.append(_out_of_package_support(unit, reference))
            continue
        cleaned = _strip_units_from_paragraph(paragraph, [unit for unit, _ in units])
        if cleaned.strip():
            kept.append(cleaned)
        for unit, reference in units:
            removed.append(_out_of_package_support(unit, reference))
    joined = "\n\n".join(part.strip() for part in kept if part.strip()).strip()
    return joined, tuple(removed)


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
    if any(
        str(item.get("status") or "") in {UNSUPPORTED, OUT_OF_PACKAGE_CLAIM}
        for item in cited_claims
    ):
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
    """Resuelve Doc:N contra el paquete, repara citas inválidas y marca uso.

    Antes de resolver citas, los claims que introducen referencias fuera del
    paquete se quitan de forma determinista (sin segunda generación).
    """
    original = answer or ""
    trimmed, external_claims = strip_external_ungrounded(original, package)
    invalid = tuple(
        number
        for number in parse_doc_numbers(trimmed)
        if not package.citation.evidence_id_for_doc(number)
    )
    repaired = strip_invalid_doc_citations(trimmed, invalid) if invalid else trimmed
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
        external_claims=external_claims,
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
    external_claims: int = 0,
) -> str:
    return (
        "Evidencia narrativa:\n"
        f"Recuperadas: {retrieved}\n"
        f"Seleccionadas: {selected}\n"
        f"Usadas en explicación: {used}\n"
        f"Citadas: {cited}\n"
        f"Documentos usados: {documents_used}\n"
        f"Claims externos removidos: {int(external_claims or 0)}\n"
        f"decision_evidence={decision_evidence}"
    )
