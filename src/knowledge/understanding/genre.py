# =============================================================================
# P18.1-05 — Género documental determinista
# =============================================================================
# El género describe la FORMA del documento (narrativa, manual, política,
# contrato, tabular...). No es un dominio de negocio y nunca se deriva de
# `document_type` ni de dos campos técnicos aislados.
#
# Contrato aditivo: `document_genre`, `genre_confidence`, `genre_evidence`,
# `topic_domain`, `business_domain`. El clasificador no escribe conocimiento
# canónico ni llama a un LLM.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.core.domain.knowledge_v2 import StructuredDocument, StructuredBlockKind

_GENRE_VERSION = "p18.1-genre-1"

_DIALOGUE_MARKS = re.compile(
    r"[“”«»]|(?:^|\n)\s*[—–]\s*|(?:^|\n)\s*-\s+"
)
_QUESTION = re.compile(r"[¿?]")
_FIRST_PERSON = re.compile(
    r"\b(yo|mi|mis|me|conmigo|nosotros|nuestro|nuestra)\b", re.IGNORECASE
)
_NARRATIVE_VERBS = re.compile(
    r"\b(era|eran|fue|dijo|respondió|preguntó|miró|vio|pensó|recordó|"
    r"exclamó|susurró|contó|había)\b",
    re.IGNORECASE,
)
_NORMATIVE = re.compile(
    r"\b(debe|deben|deberá|deberán|obligatorio|obligatoria|prohibido|"
    r"prohibida|política|procedimiento|norma|aprobación|autorización|"
    r"empleado|empleados|responsable)\b",
    re.IGNORECASE,
)
_LEGAL = re.compile(
    r"\b(contrato|contratista|cláusula|clausula|proveedor|proveedores|"
    r"partes|jurisdicción|jurisdiccion|indemnización|indemnizacion|"
    r"rescisión|rescision|obligaciones)\b",
    re.IGNORECASE,
)
_TECHNICAL = re.compile(
    r"\b(especificación|especificacion|api|endpoint|campo|byte|bit|"
    r"posición|posicion|máscara|mascara|schema|registro|columna|"
    r"formato|validación|validacion)\b",
    re.IGNORECASE,
)
_EDUCATIONAL = re.compile(
    r"\b(capítulo|capitulo|lección|leccion|ejercicio|módulo|modulo|"
    r"aprendizaje|curso|unidad didáctica)\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,3}\s|^\d+(?:\.\d+)*\s+\S", re.MULTILINE)


@dataclass(frozen=True)
class GenreSignal:
    name: str
    weight: float
    detail: str

    def as_dict(self) -> dict:
        return {
            "signal": self.name,
            "weight": round(self.weight, 3),
            "detail": self.detail,
        }


def _sample(document: StructuredDocument) -> tuple[str, list[str], int]:
    blocks = [
        block
        for block in document.blocks[:400]
        if block.kind
        in {
            StructuredBlockKind.PARAGRAPH,
            StructuredBlockKind.QUOTE,
            StructuredBlockKind.LIST_ITEM,
            StructuredBlockKind.HEADING,
            StructuredBlockKind.TITLE,
        }
    ]
    text = "\n".join((block.text or "").strip() for block in blocks if block.text)
    headings = [
        section.heading
        for section in document.sections
        if getattr(section, "heading", None)
    ][:24]
    lines = max(1, len([line for line in text.splitlines() if line.strip()]))
    return text[:20000], headings, lines


def _folder_domain(document: StructuredDocument) -> str | None:
    path = (document.metadata or {}).get("folder_path")
    if isinstance(path, str) and path.strip():
        return path.strip().strip("/").split("/")[0][:120] or None
    return None


def classify_document_genre(
    document: StructuredDocument,
    extracted: dict,
    *,
    filename: str | None = None,
) -> dict:
    """Clasificación explicable por estructura, no por una etiqueta previa."""
    text, headings, lines = _sample(document)
    lower = text.lower()
    suffix = Path(filename or document.title or "").suffix.lower()
    field_names = [
        str(item.get("name") or "")
        for item in extracted.get("technical_fields") or []
        if str(item.get("name") or "").strip()
    ]
    mask_literals = [
        item
        for item in extracted.get("exact_literals") or []
        if item.get("pattern_type") == "mask"
    ]
    code_blocks = sum(
        1 for block in document.blocks if block.kind is StructuredBlockKind.CODE
    )
    dialogue = len(_DIALOGUE_MARKS.findall(text))
    questions = len(_QUESTION.findall(text))
    first_person = len(_FIRST_PERSON.findall(text))
    narrative_verbs = len(_NARRATIVE_VERBS.findall(text))
    normative = len(_NORMATIVE.findall(text))
    legal = len(_LEGAL.findall(text))
    technical_terms = len(_TECHNICAL.findall(lower))
    educational = len(_EDUCATIONAL.findall(lower))
    heading_count = len(headings) + len(_HEADING.findall(text))

    signals: list[GenreSignal] = []
    scores: dict[str, float] = {
        "narrative": 0.0,
        "technical": 0.0,
        "policy": 0.0,
        "legal": 0.0,
        "educational": 0.0,
        "tabular": 0.0,
    }

    if document.tabular is not None or suffix in {".csv", ".xlsx", ".xls"}:
        scores["tabular"] = 0.96 if document.tabular is not None else 0.82
        signals.append(
            GenreSignal(
                "tabular_structure",
                0.96,
                f"workbook={document.tabular is not None}; suffix={suffix or 'none'}",
            )
        )

    # Técnico: exige señales de esquema, no solo números o barras.
    schema_score = 0.0
    if len(field_names) >= 3:
        schema_score += 0.35
        signals.append(
            GenreSignal(
                "technical_fields",
                min(0.35 + len(field_names) / 40, 0.6),
                f"{len(field_names)} campos con nombre",
            )
        )
    if document.tables:
        schema_score += min(0.2 + len(document.tables) / 20, 0.35)
        signals.append(
            GenreSignal(
                "tables",
                min(0.2 + len(document.tables) / 20, 0.35),
                f"{len(document.tables)} tablas",
            )
        )
    if mask_literals:
        schema_score += 0.2
        signals.append(
            GenreSignal("mask_literals", 0.2, f"{len(mask_literals)} máscaras")
        )
    if code_blocks:
        schema_score += min(0.1 + code_blocks / 20, 0.25)
        signals.append(
            GenreSignal("code_blocks", min(0.1 + code_blocks / 20, 0.25), f"{code_blocks} bloques de código")
        )
    if technical_terms >= 4:
        schema_score += min(technical_terms / 40, 0.2)
        signals.append(
            GenreSignal(
                "technical_vocabulary",
                min(technical_terms / 40, 0.2),
                f"{technical_terms} términos técnicos",
            )
        )
    scores["technical"] = min(schema_score, 0.95)

    # Narrativa: diálogo, preguntas y verbos de relato, en densidad.
    dialogue_ratio = dialogue / lines
    narrative = 0.0
    if dialogue >= 3:
        narrative += min(0.15 + dialogue_ratio * 2.5, 0.45)
        signals.append(
            GenreSignal(
                "dialogue",
                min(0.15 + dialogue_ratio * 2.5, 0.45),
                f"{dialogue} marcas de diálogo",
            )
        )
    if narrative_verbs >= 3:
        narrative += min(narrative_verbs / 60, 0.3)
        signals.append(
            GenreSignal(
                "narrative_verbs",
                min(narrative_verbs / 60, 0.3),
                f"{narrative_verbs} verbos de relato",
            )
        )
    if questions >= 2:
        narrative += min(questions / 40, 0.15)
        signals.append(
            GenreSignal("questions", min(questions / 40, 0.15), f"{questions} preguntas")
        )
    if first_person >= 3 and narrative_verbs >= 2:
        narrative += 0.1
        signals.append(
            GenreSignal("first_person", 0.1, f"{first_person} marcas de primera persona")
        )
    scores["narrative"] = min(narrative, 0.95)

    # Política: contexto normativo + vocabulario de gobierno.
    policy = 0.0
    if normative >= 3:
        policy += min(normative / 25, 0.55)
        signals.append(
            GenreSignal("normative_language", min(normative / 25, 0.55), f"{normative} marcas normativas")
        )
    if any(
        re.search(r"pol[ií]tica|procedimiento|norma|control interno", str(h), re.IGNORECASE)
        for h in headings
    ):
        policy += 0.25
        signals.append(GenreSignal("policy_heading", 0.25, "encabezado normativo"))
    if re.search(r"empleado|aprobaci[oó]n|autorizaci[oó]n", lower):
        policy += 0.1
    scores["policy"] = min(policy, 0.95)

    # Legal: contrato/cláusulas/partes.
    legal_score = 0.0
    if legal >= 3:
        legal_score += min(legal / 20, 0.6)
        signals.append(
            GenreSignal("legal_language", min(legal / 20, 0.6), f"{legal} términos legales")
        )
    if any(re.search(r"contrato|cl[aá]usula|acuerdo", str(h), re.IGNORECASE) for h in headings):
        legal_score += 0.25
        signals.append(GenreSignal("legal_heading", 0.25, "encabezado contractual"))
    scores["legal"] = min(legal_score, 0.95)

    if educational >= 3:
        scores["educational"] = min(educational / 20, 0.7)
        signals.append(
            GenreSignal("educational_language", min(educational / 20, 0.7), f"{educational} términos didácticos")
        )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_genre, top_score = ranked[0]
    second_genre, second_score = ranked[1]
    if top_score < 0.35:
        genre = "unknown"
        confidence = round(max(top_score, 0.2), 3)
    elif second_score >= 0.55 and abs(top_score - second_score) <= 0.08:
        genre = "mixed"
        confidence = round((top_score + second_score) / 2, 3)
    else:
        genre = top_genre
        confidence = round(top_score, 3)

    # Un manual técnico con muchas secciones y campos sigue siendo técnico.
    if genre == "technical" and len(field_names) < 2 and not document.tables:
        genre = "unknown"
        confidence = min(confidence, 0.34)

    return {
        "document_genre": genre,
        "genre_confidence": confidence,
        "genre_scores": {key: round(value, 3) for key, value in scores.items()},
        "genre_evidence": [signal.as_dict() for signal in signals[:12]],
        "genre_version": _GENRE_VERSION,
        "topic_domain": _folder_domain(document),
        "business_domain": (document.metadata or {}).get("business_domain") or None,
        "heading_count": heading_count,
    }


__all__ = ["GenreSignal", "classify_document_genre"]
