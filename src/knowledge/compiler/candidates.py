# =============================================================================
# P18.1-06/07 — Puerta semántica de candidatos
# =============================================================================
# Una cadena extraída no es un concepto por existir. Esta puerta explica por
# qué se acepta, se envía a revisión o se rechaza. No usa una blacklist de
# números: un ID puede ser válido si el contexto lo declara campo/registro.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.domain.knowledge_v2 import StructuredDocument

_MIN_AUTONOMY = 3
_DIALOGUE = re.compile(r"^[\s“”«»—–-]|[\?¿]")
_QUESTION_LABEL = re.compile(r"^[¿\s]*.+[\?]\s*$")
_DIALOGUE_VERB = re.compile(
    r"\b(dijo|respondió|respondio|preguntó|pregunto|exclamó|exclamo|"
    r"susurró|susurro|contestó|contesto|refutó|refuto)\b",
    re.IGNORECASE,
)
_NARRATIVE = re.compile(
    r"\b(era|fue|había|habia|principito|rosa|zorro|planeta|"
    r"yo|mi|me|nosotros)\b",
    re.IGNORECASE,
)
_NORMATIVE_HEADING = re.compile(
    r"pol[ií]tica|procedimiento|norma|contrato|cl[aá]usula|acuerdo|"
    r"especificaci[oó]n|api|schema|regla|control interno",
    re.IGNORECASE,
)
_TECHNICAL = re.compile(
    r"\b(campo|byte|bit|posici[oó]n|m[aá]scara|columna|registro|"
    r"schema|formato|longitud|api|endpoint|fare|basis|tarifa|tariff|"
    r"atpco|c[oó]digo|code|record|layout|tabla)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateDecision:
    accepted: bool
    needs_review: bool
    reason: str
    claim_kind: str = ""
    detail: str = ""


def _genre(document: StructuredDocument | None) -> str:
    if document is None:
        return "unknown"
    profile = (document.metadata or {}).get("understanding") or {}
    profile = profile.get("profile") if isinstance(profile, dict) else None
    if isinstance(profile, dict):
        value = str(profile.get("document_genre") or "").strip()
        if value and value != "unknown":
            return value
    # Documentos crudos (tests, conectores) pueden no traer el perfil. El
    # nombre no es una etiqueta canónica: solo desempata el contexto normativo.
    hint = f"{document.title or ''} {document.external_id or ''}".lower()
    if re.search(r"record|manual|spec|atpco|layout|especificaci[oó]n", hint):
        return "technical"
    if re.search(r"cuento|relato|novela|principito|narrativa", hint):
        return "narrative"
    return "unknown"


def looks_like_dialogue(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if value[0] in "“”«»—–-":
        return True
    return bool(_DIALOGUE.search(value) and _DIALOGUE_VERB.search(value))


def looks_like_question(text: str) -> bool:
    return bool(_QUESTION_LABEL.match((text or "").strip()))


def is_isolated_number(text: str) -> bool:
    value = (text or "").strip()
    return bool(value) and value.replace(",", "").replace(".", "").isdigit()


def assess_entity_candidate(
    label: str,
    *,
    kind: str,
    document: StructuredDocument | None = None,
    text: str = "",
    has_locator: bool = True,
) -> CandidateDecision:
    value = (label or "").strip()
    if len(value) < 2:
        return CandidateDecision(False, False, "TOO_SHORT", detail="menos de 2 caracteres")
    if not has_locator:
        return CandidateDecision(False, False, "MISSING_EVIDENCE", detail="sin página/bloque")
    if looks_like_question(value):
        return CandidateDecision(
            False,
            True,
            "QUESTION_OR_DIALOGUE",
            detail="etiqueta interrogativa: se conserva como pasaje, no como concepto",
        )
    if looks_like_dialogue(value) or looks_like_dialogue(text[:200]):
        return CandidateDecision(
            False,
            True,
            "DIALOGUE_FRAGMENT",
            detail="fragmento de diálogo, no unidad semántica autónoma",
        )

    genre = _genre(document)
    if is_isolated_number(value):
        # Solo vale si el tipo y el contexto declaran un identificador real.
        if kind not in {"field", "column", "table", "record"}:
            return CandidateDecision(
                False,
                False,
                "ISOLATED_NUMBER",
                detail="número sin contexto de esquema",
            )
        if not _TECHNICAL.search(text or "") and not _TECHNICAL.search(genre):
            return CandidateDecision(
                False,
                True,
                "NUMBER_WITHOUT_SCHEMA",
                detail="número aislado sin declaración de campo",
            )

    if genre in {"narrative", "educational"} and kind in {"concept", "definition"}:
        if _DIALOGUE_VERB.search(text or "") or _NARRATIVE.search(value):
            return CandidateDecision(
                False,
                True,
                "NARRATIVE_PASSAGE",
                detail="pasaje narrativo: no se promueve a concepto canónico",
            )
    return CandidateDecision(True, False, "ACCEPTED")


def classify_claim_kind(
    statement: str,
    *,
    document: StructuredDocument | None = None,
    section_path: tuple[str, ...] = (),
) -> str:
    """Clasificación explicable de una afirmación normativa o narrativa."""
    text = (statement or "").strip()
    genre = _genre(document)
    headings = " ".join(section_path)
    if looks_like_dialogue(text):
        return "quoted_dialogue"
    if re.search(r"\b(metáfora|como si|parecía|parecia)\b", text, re.IGNORECASE) and genre == "narrative":
        return "metaphor"
    if genre == "narrative" and not _NORMATIVE_HEADING.search(headings):
        return "narrative_statement"
    if genre == "educational" and not _NORMATIVE_HEADING.search(headings):
        return "advice"
    if re.search(r"contrato|cl[aá]usula|proveedor|contratista", headings, re.IGNORECASE):
        return "contract_obligation"
    if genre == "legal":
        return "contract_obligation"
    if re.search(r"pol[ií]tica|procedimiento|norma|control interno", headings, re.IGNORECASE):
        return "policy_rule"
    if genre == "policy":
        return "policy_rule"
    if _TECHNICAL.search(text) or genre == "technical":
        return "technical_constraint"
    return "unclassified"


def assess_rule_candidate(
    statement: str,
    *,
    subject: str,
    document: StructuredDocument | None = None,
    section_path: tuple[str, ...] = (),
) -> CandidateDecision:
    text = " ".join((statement or "").split())
    if len(text) < 24:
        return CandidateDecision(False, False, "TOO_SHORT", detail="enunciado incompleto")
    if is_isolated_number(subject):
        return CandidateDecision(
            False, False, "NUMERIC_SUBJECT", detail="el sujeto es un número aislado"
        )
    if looks_like_question(subject) or looks_like_question(text):
        return CandidateDecision(
            False,
            True,
            "QUESTION_NOT_RULE",
            detail="una pregunta no es una obligación",
        )
    claim_kind = classify_claim_kind(
        text, document=document, section_path=section_path
    )
    if claim_kind in {"quoted_dialogue", "narrative_statement", "metaphor", "advice"}:
        return CandidateDecision(
            False,
            True,
            "NON_NORMATIVE_CONTEXT",
            claim_kind=claim_kind,
            detail="contexto narrativo/didáctico sin autoridad normativa",
        )
    if claim_kind == "unclassified":
        return CandidateDecision(
            False,
            True,
            "UNCLASSIFIED_CLAIM",
            claim_kind=claim_kind,
            detail="sin contexto normativo verificable",
        )
    return CandidateDecision(True, False, "ACCEPTED", claim_kind=claim_kind)


__all__ = [
    "CandidateDecision",
    "assess_entity_candidate",
    "assess_rule_candidate",
    "classify_claim_kind",
    "is_isolated_number",
    "looks_like_dialogue",
    "looks_like_question",
]
