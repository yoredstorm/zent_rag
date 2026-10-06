# =============================================================================
# Parser Lab — serialización de artefactos shadow
# =============================================================================
# El StructuredDocument de evaluación se guarda como JSON para inspección y
# para correr el benchmark de conocimiento después, sin tocar la base. Nunca
# es un Knowledge Object: solo un artefacto de diagnóstico.
# =============================================================================
from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument

SCHEMA = "zent.parser_shadow.1"
_SAFE_NAME = re.compile(r"[^\w.-]+", re.UNICODE)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def document_to_dict(document: StructuredDocument) -> dict[str, Any]:
    """StructuredDocument -> JSON seguro (UUID/datetime/tuplas incluidas)."""
    return _jsonable(document)


def shadow_artifact_filename(external_id: str, evaluation_label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe = _SAFE_NAME.sub("_", external_id or "document")[:80]
    return f"{safe}.{evaluation_label}.{stamp}.json"


def write_shadow_artifact(
    directory: str | Path,
    *,
    external_id: str,
    document: StructuredDocument,
    comparison: dict[str, Any],
    evaluation_label: str,
) -> str:
    """Persiste documento de evaluación + comparación; devuelve la ruta."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / shadow_artifact_filename(external_id, evaluation_label)
    payload = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "external_id": external_id,
        "evaluation_label": evaluation_label,
        "document": document_to_dict(document),
        "comparison": comparison,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)


__all__ = [
    "SCHEMA",
    "document_to_dict",
    "shadow_artifact_filename",
    "write_shadow_artifact",
]
