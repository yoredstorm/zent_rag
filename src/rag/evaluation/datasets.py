# =============================================================================
# Evaluation Datasets — schema v2 con normalización legacy
# =============================================================================
# Schema canónico v2 por caso:
#   {
#     "id": "caso-001",                       # opcional (auto-generado)
#     "question": "pregunta en lenguaje natural",
#     "expected_answer": "respuesta esperada", # opcional (juez de relevancia)
#     "expected_sources": ["etiqueta|fragmento", ...],
#     "metadata": {"role": "admin", "top_k": 20, "category": "catálogo",
#                  "difficulty": "easy", "target": "rag"}
#   }
#
# Compatibilidad legacy (golden sets v1):
#   query -> question
#   expected_keywords -> metadata.expected_keywords (proxy determinista)
#   relevant_chunks  -> expected_sources (fragmentos de contenido)
#   top_k / role     -> metadata.top_k / metadata.role
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_SCHEMA_VERSION = 2
_LEGACY_KEY_MAP = (
    ("query", "question"),
)


@dataclass(kw_only=True)
class EvalCase:
    """Caso de evaluación normalizado (schema v2)."""

    id: str
    question: str
    expected_answer: str | None = None
    expected_sources: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def legacy_keywords(self) -> list[str]:
        return list(self.metadata.get("expected_keywords") or [])


@dataclass(kw_only=True)
class EvalDataset:
    """Dataset de evaluación cargado y validado."""

    name: str
    cases: list[EvalCase]
    schema_version: int = _SCHEMA_VERSION
    weights: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def case_count(self) -> int:
        return len(self.cases)


def _normalize_case(raw: dict, index: int) -> EvalCase:
    if not isinstance(raw, dict):
        raise ValueError(f"Eval case #{index} no es un objeto JSON")

    question = raw.get("question") or raw.get("query")
    if not question or not str(question).strip():
        raise ValueError(f"Eval case #{index}: falta 'question'")

    case_id = str(raw.get("id") or f"case-{index + 1:03d}")
    metadata = dict(raw.get("metadata") or {})

    # Normalización legacy -> v2
    if "expected_keywords" in raw and "expected_keywords" not in metadata:
        metadata["expected_keywords"] = list(raw["expected_keywords"] or [])
    if "top_k" in raw and "top_k" not in metadata:
        metadata["top_k"] = raw["top_k"]
    if "role" in raw and "role" not in metadata:
        metadata["role"] = raw["role"]

    expected_sources = list(raw.get("expected_sources") or [])
    if not expected_sources and raw.get("relevant_chunks"):
        expected_sources = [str(c) for c in raw["relevant_chunks"]]

    expected_answer = raw.get("expected_answer")
    return EvalCase(
        id=case_id,
        question=str(question).strip(),
        expected_answer=str(expected_answer) if expected_answer else None,
        expected_sources=[str(s) for s in expected_sources],
        metadata=metadata,
    )


def load_dataset(payload: list[dict], name: str = "dataset") -> EvalDataset:
    """Carga y valida una lista de casos (schema v2 con fallback legacy)."""
    if not isinstance(payload, list):
        raise ValueError("El dataset debe ser una lista JSON de casos")
    if not payload:
        raise ValueError("El dataset no contiene casos")

    cases = [_normalize_case(raw, i) for i, raw in enumerate(payload)]
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"Id de caso duplicado: {case.id}")
        seen.add(case.id)

    return EvalDataset(name=name, cases=cases)


def load_dataset_file(path: str | Path) -> EvalDataset:
    """Carga un golden set desde archivo JSON."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Golden set no encontrado: {file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return load_dataset(payload, name=file_path.stem)


def dataset_to_payload(dataset: EvalDataset) -> list[dict]:
    """Serializa el dataset normalizado a JSON (schema v2)."""
    return [
        {
            "id": case.id,
            "question": case.question,
            "expected_answer": case.expected_answer,
            "expected_sources": case.expected_sources,
            "metadata": case.metadata,
        }
        for case in dataset.cases
    ]
