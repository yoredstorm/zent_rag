# =============================================================================
# Late Chunking — solo si el provider REAL lo soporta
# =============================================================================
# Late chunking NO es "prefijar la sección" ni "embeber el padre": es un
# contrato del API donde los chunks del mismo documento se envían juntos y el
# modelo contextualiza cada uno con el documento completo (Jina-style).
#
# Reglas:
#   - off: nunca se intenta.
#   - auto (default): se intenta SOLO si el registry declaró la capacidad del
#     modelo Y el provider expone `embed_late_chunking`. Si el proveedor falla,
#     se cae a contextual embedding sin romper la ingesta.
#   - on: exige capacidad declarada; sin ella es un error de configuración
#     (se registra y se usa contextual embedding).
#
# El modo y la versión entran al representation_fingerprint: cambiar de
# contextual a late (o al revés) reindexa SOLO el embedding.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .registry import resolve_embedding_capability

LATE_CHUNKING_VERSION = "late-chunking-1"
LATE_CHUNKING_MODES = ("off", "auto", "on")


def _settings():
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001
        return None


def _setting(name: str, default):
    settings = _settings()
    if settings is None:
        return default
    return getattr(settings, name, default)


def late_chunking_mode() -> str:
    mode = str(_setting("RAG_EMBEDDING_LATE_CHUNKING", "auto") or "auto").strip().lower()
    return mode if mode in LATE_CHUNKING_MODES else "auto"


def configured_late_chunking_models() -> set[str]:
    raw = str(_setting("RAG_EMBEDDING_LATE_CHUNKING_MODELS", "") or "")
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def can_late_chunk(provider, *, model: str | None = None, mode: str | None = None) -> bool:
    """True solo si capacidad declarada + método real en el provider."""
    resolved_mode = (mode or late_chunking_mode()).strip().lower()
    if resolved_mode == "off":
        return False
    if not callable(getattr(provider, "embed_late_chunking", None)):
        return False
    model_name = str(
        model or _setting("EMBEDDING_MODEL", "") or ""
    ).strip()
    capability = resolve_embedding_capability(
        model_name,
        late_chunking_models=configured_late_chunking_models(),
    )
    return bool(capability.supports_late_chunking)


@dataclass(frozen=True, kw_only=True)
class LateChunkingBatch:
    """Chunks del mismo padre/documento que se envían juntos al provider."""

    parent_id: str
    chunk_ids: tuple[str, ...]
    texts: tuple[str, ...]
    fingerprint: str = ""
    version: str = LATE_CHUNKING_VERSION

    @property
    def size(self) -> int:
        return len(self.chunk_ids)


def plan_late_chunking_batches(
    chunks: list,
    representations: dict,
    *,
    min_children: int = 2,
) -> list[LateChunkingBatch]:
    """Agrupa children por padre con el texto ya planificado para embedding."""
    grouped: dict[str, list] = {}
    for chunk in chunks:
        parent_id = getattr(chunk, "parent_id", None)
        if parent_id is None:
            continue
        grouped.setdefault(str(parent_id), []).append(chunk)
    batches: list[LateChunkingBatch] = []
    for parent_id, children in grouped.items():
        if len(children) < max(1, int(min_children)):
            continue
        ordered = sorted(children, key=lambda item: int(item.chunk_index))
        texts: list[str] = []
        chunk_ids: list[str] = []
        for child in ordered:
            representation = representations.get(child.id) or {}
            text = representation.get("embed") or getattr(child, "content", "")
            if not text:
                continue
            texts.append(str(text))
            chunk_ids.append(str(child.id))
        if len(texts) < max(1, int(min_children)):
            continue
        material = "|".join(f"{cid}:{text}" for cid, text in zip(chunk_ids, texts))
        batches.append(
            LateChunkingBatch(
                parent_id=parent_id,
                chunk_ids=tuple(chunk_ids),
                texts=tuple(texts),
                fingerprint=sha256(material.encode("utf-8")).hexdigest(),
            )
        )
    return batches


async def embed_late_chunking_batches(
    provider,
    batches: list[LateChunkingBatch],
    *,
    model: str | None = None,
) -> dict[str, list[float]]:
    """Ejecuta los batches; un fallo del provider deja el batch sin vectores.

    Nunca lanza: el engine completa esos chunks con contextual embedding.
    """
    vectors: dict[str, list[float]] = {}
    for batch in batches:
        try:
            result = await provider.embed_late_chunking(  # type: ignore[attr-defined]
                list(batch.texts), model=model
            )
        except Exception as exc:  # noqa: BLE001 — fallback a contextual embedding
            try:
                from src.infrastructure.observability.logging_config import (
                    get_logger,
                )

                get_logger(__name__).warning(
                    "Late chunking batch failed; contextual embedding fallback",
                    parent_id=batch.parent_id,
                    error=str(exc)[:200],
                )
            except Exception:  # noqa: BLE001
                pass
            continue
        if not isinstance(result, list) or len(result) != batch.size:
            continue
        for chunk_id, vector in zip(batch.chunk_ids, result):
            vectors[chunk_id] = list(vector)
    return vectors


__all__ = [
    "LATE_CHUNKING_MODES",
    "LATE_CHUNKING_VERSION",
    "LateChunkingBatch",
    "can_late_chunk",
    "configured_late_chunking_models",
    "embed_late_chunking_batches",
    "late_chunking_mode",
    "plan_late_chunking_batches",
]
