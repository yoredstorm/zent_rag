# =============================================================================
# Golden sets V2 — Enterprise Evaluation (brief §27)
# =============================================================================
# Un golden set declara: query, documentos relevantes (ids), y (opcional) los
# documentos que deben aparecer citados + frases que deben quedar UNSUPPORTED.
# Carga JSON/YAML para datasets automatizados; eval también provee un seed de
# ejemplo construido sobre el flujo V2 (documentos estructurados reales).
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class GoldenCase:
    query: str
    relevant_document_ids: tuple[UUID, ...] = ()
    cited_document_ids: tuple[UUID, ...] = ()
    expected_unsupported: tuple[str, ...] = ()
    context: str = ""


@dataclass(frozen=True, kw_only=True)
class GoldenSet:
    name: str
    cases: tuple[GoldenCase, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cases": [
                {
                    "query": case.query,
                    "relevant_document_ids": [str(x) for x in case.relevant_document_ids],
                    "cited_document_ids": [str(x) for x in case.cited_document_ids],
                    "expected_unsupported": list(case.expected_unsupported),
                }
                for case in self.cases
            ],
        }


def golden_set_from_dict(payload: dict) -> GoldenSet:
    cases: list[GoldenCase] = []
    for item in payload.get("cases", []):
        cases.append(
            GoldenCase(
                query=str(item["query"]),
                relevant_document_ids=tuple(
                    UUID(str(x)) for x in item.get("relevant_document_ids", [])
                ),
                cited_document_ids=tuple(
                    UUID(str(x)) for x in item.get("cited_document_ids", [])
                ),
                expected_unsupported=tuple(str(x) for x in item.get("expected_unsupported", [])),
                context=str(item.get("context", "")),
            )
        )
    return GoldenSet(name=str(payload.get("name", "unnamed")), cases=tuple(cases))


def load_golden_set(path: str | Path) -> GoldenSet:
    """Carga un golden set desde JSON (o YAML si termina en .yaml/.yml)."""
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - opcional
            raise ImportError("PyYAML required to load .yaml golden sets") from exc
        payload = yaml.safe_load(raw)
    else:
        payload = json.loads(raw)
    return golden_set_from_dict(payload)


def build_corpus_golden_set(
    cases: list[tuple[str, list[UUID], list[UUID]]],
    *,
    name: str = "corpus",
) -> GoldenSet:
    """Construye un golden set desde triplas (query, relevantes, citados)."""
    return GoldenSet(
        name=name,
        cases=tuple(
            GoldenCase(
                query=q,
                relevant_document_ids=tuple(relevant),
                cited_document_ids=tuple(cited),
            )
            for q, relevant, cited in cases
        ),
    )
