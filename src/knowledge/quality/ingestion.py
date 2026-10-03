# =============================================================================
# Knowledge OS — Calidad de ingesta (INGESTION_QUALITY_QUEUE)
# =============================================================================
# Un problema de parsing no es un problema de conocimiento. Todo candidato
# rechazado por el pipeline (fragmento, sin fuente, sin evidencia, extracción
# de baja calidad) se registra aquí y NO entra al conocimiento canónico.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class QualityKind(StrEnum):
    """Motivo del rechazo. Corto, accionable y auditable."""

    SOURCE_MISSING = "SOURCE_MISSING"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    FRAGMENT_OF_EXISTING_TEXT = "FRAGMENT_OF_EXISTING_TEXT"
    LOW_QUALITY_EXTRACTION = "LOW_QUALITY_EXTRACTION"
    LAYOUT_ARTIFACT = "LAYOUT_ARTIFACT"
    TRUNCATED_WORD = "TRUNCATED_WORD"
    SENTENCE_FRAGMENT = "SENTENCE_FRAGMENT"
    TOO_LONG_FOR_TERM = "TOO_LONG_FOR_TERM"
    PARSER_FRAGMENT = "PARSER_FRAGMENT"
    ALIAS_CONFLICT = "ALIAS_CONFLICT"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


_SEVERITY_BY_KIND: dict[str, str] = {
    QualityKind.SOURCE_MISSING.value: "high",
    QualityKind.EVIDENCE_MISSING.value: "high",
    QualityKind.FRAGMENT_OF_EXISTING_TEXT.value: "medium",
    QualityKind.PARSER_FRAGMENT.value: "medium",
    QualityKind.LAYOUT_ARTIFACT.value: "medium",
    QualityKind.TRUNCATED_WORD.value: "medium",
    QualityKind.LOW_QUALITY_EXTRACTION.value: "medium",
    QualityKind.SENTENCE_FRAGMENT.value: "low",
    QualityKind.TOO_LONG_FOR_TERM.value: "low",
    QualityKind.ALIAS_CONFLICT.value: "medium",
    QualityKind.INSUFFICIENT_CONTEXT.value: "medium",
}


def severity_for(kind: str) -> str:
    return _SEVERITY_BY_KIND.get(kind, "medium")


@dataclass
class QualityCollector:
    """Acumula problemas de ingesta durante una compilación (sin I/O)."""

    issues: list[dict] = field(default_factory=list)

    def add(
        self,
        kind: str,
        subject: str,
        *,
        detail: dict | None = None,
        evidence: object | None = None,
        source_id: object | None = None,
        document_id: object | None = None,
        severity: str | None = None,
        confidence: float | None = None,
    ) -> None:
        self.issues.append(
            {
                "kind": str(kind),
                "subject": (subject or "")[:512],
                "detail": detail or {},
                "evidence": evidence,
                "source_id": source_id,
                "document_id": document_id,
                "severity": severity or severity_for(str(kind)),
                "confidence": confidence,
            }
        )

    def extend(self, issues: list[dict]) -> None:
        self.issues.extend(issues)

    def __bool__(self) -> bool:
        return bool(self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            key = str(issue.get("kind") or "UNKNOWN")
            counts[key] = counts.get(key, 0) + 1
        return counts


__all__ = ["QualityKind", "QualityCollector", "severity_for"]
