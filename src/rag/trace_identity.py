"""Identidad canónica de fuentes y evidencia — Traceability Schema v2.

Dos problemas reales que resuelve este módulo:

1. Una misma fuente física podía aparecer como varios `document_id` según cómo
   la ingestión la fragmentó (chunks, páginas, semantic units, documentos
   derivados). Acá se deriva un `canonical_source_id` estable desde la
   identidad física disponible, no desde el id generado en procesamiento.
2. Una misma evidencia lógica podía recibir ids distintos o ninguno
   (`EVIDENCE_ID_MISSING`). Acá el `evidence_id` es determinístico: misma
   fuente + ubicación + texto normalizado ⇒ mismo id, siempre.

Reglas:
- Nunca se inventa una identidad: si sólo hay señales débiles se declara
  `weak = true` y el diagnóstico lo explica.
- `UNKNOWN != ZERO`: sin material para derivar un id se devuelve `None`, no un
  placeholder aleatorio.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

_UUIDISH = re.compile(r"^[0-9a-fA-F-]{20,36}$")
_GENERATED_NAME = re.compile(r"^documento\s+[0-9a-f]{6,}$", re.IGNORECASE)
_UNAVAILABLE_NAMES = {
    "",
    "documento sin título",
    "documento sin titulo",
    "sin título",
    "sin titulo",
    "fuente sin nombre",
    "fuente no identificada",
    "untitled",
    "unknown",
}

#: Orden de resolución del nombre visible (§7). El primero con valor gana.
DISPLAY_NAME_KEYS: tuple[str, ...] = (
    "display_name",
    "original_filename",
    "uploaded_filename",
    "source_profile_title",
    "storage_filename",
    "filename",
    "source_filename",
    "document_name",
    "source_title",
    "document_title",
    "title",
)

#: Identidad física por orden de fuerza (§3). NO se depende de document_id.
_PHYSICAL_IDENTITY_KEYS: tuple[str, ...] = (
    "original_file_id",
    "file_id",
    "source_file_id",
    "storage_object_id",
    "object_id",
)
_URI_KEYS: tuple[str, ...] = (
    "source_uri",
    "storage_uri",
    "object_uri",
    "s3_uri",
    "uri",
    "url",
    "path",
)
_FILENAME_KEYS: tuple[str, ...] = (
    "original_filename",
    "uploaded_filename",
    "storage_filename",
    "filename",
    "source_filename",
)
_CONTENT_HASH_KEYS: tuple[str, ...] = (
    "content_hash",
    "checksum",
    "sha256",
    "file_hash",
)
_VERSION_KEYS: tuple[str, ...] = ("document_version", "version", "revision")
_WEAK_IDENTITY_KEYS: tuple[str, ...] = ("document_id", "source_id", "catalog_id")
_TENANT_KEYS: tuple[str, ...] = ("organization_id", "tenant_id", "tenant")
_KB_KEYS: tuple[str, ...] = (
    "knowledge_base_id",
    "knowledge_base",
    "collection_id",
    "collection",
    "corpus_id",
    "scope_id",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(raw: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _text(raw.get(key))
        if value:
            return value
    return ""


def normalize_text(value: Any) -> str:
    """Espacios colapsados; preserva mayúsculas (para mostrar)."""
    return re.sub(r"\s+", " ", _text(value))


def normalize_hash_text(value: Any) -> str:
    """Forma canónica para hashing/dedup: colapsada y casefold."""
    return normalize_text(value).casefold()


def text_fingerprint(value: Any, *, size: int = 16) -> str | None:
    normalized = normalize_hash_text(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8", "ignore")).hexdigest()[:size]


def base_name(value: Any) -> str:
    candidate = _text(value).replace("\\", "/").rstrip("/").split("/")[-1]
    return candidate.strip()


def is_uuidish(value: str) -> bool:
    return bool(_UUIDISH.fullmatch(value.replace(" ", "")))


def is_generated_name(value: str) -> bool:
    return bool(_GENERATED_NAME.match(value))


def is_unavailable_name(value: str) -> bool:
    return value.strip().casefold() in _UNAVAILABLE_NAMES


def _nested_text(raw: Mapping[str, Any], key: str, nested: str) -> str:
    block = raw.get(key)
    if isinstance(block, Mapping):
        return _text(block.get(nested))
    return ""


def resolve_display_name(
    raw: Mapping[str, Any],
    *,
    canonical_source_id: str | None = None,
) -> dict[str, Any]:
    """Resuelve el nombre humano con jerarquía explícita (§7).

    Devuelve `{value, origin, missing}`. `value = None` sólo cuando no existe
    absolutamente ninguna señal; en ese caso el llamador emite diagnóstico.
    """
    for key in DISPLAY_NAME_KEYS:
        value = _text(raw.get(key))
        if not value or is_uuidish(value) or is_generated_name(value):
            continue
        if is_unavailable_name(value):
            continue
        if key in _URI_KEYS:
            value = base_name(value)
        if value:
            return {"value": value, "origin": key, "missing": False}

    profile_title = _nested_text(raw, "source_profile", "title") or _nested_text(
        raw, "source_profile", "name"
    )
    if profile_title and not is_generated_name(profile_title):
        return {"value": profile_title, "origin": "source_profile.title", "missing": False}

    for key in ("source_uri", "uri", "url", "path"):
        value = base_name(raw.get(key))
        if value and not is_uuidish(value):
            return {"value": value, "origin": f"storage:{key}", "missing": False}

    # Último recurso: etiqueta canónica legible; NO es un nombre real y se
    # declara como tal para que el diagnóstico de metadatos sea explícito.
    label = (
        f"Fuente {canonical_source_id.removeprefix('src_')[:8]}"
        if canonical_source_id
        else None
    )
    return {"value": None, "origin": None, "missing": True, "label": label}


def canonical_source_identity(
    raw: Mapping[str, Any],
    *,
    organization_id: str | None = None,
    knowledge_base_id: str | None = None,
) -> dict[str, Any]:
    """Deriva `canonical_source_id` desde la identidad física disponible.

    Tensión documentada: cuando sólo hay `document_id`/`source_id` generados la
    identidad es débil (`weak = true`) y puede no sobrevivir a una reingesta;
    el diagnóstico `CANONICAL_SOURCE_WEAK_IDENTITY` lo declara.
    """
    tenant = _text(organization_id) or _first_text(raw, _TENANT_KEYS)
    kb = (
        _text(knowledge_base_id)
        or _first_text(raw, _KB_KEYS)
        or _nested_text(raw, "source_profile", "knowledge_base_id")
    )
    version = _first_text(raw, _VERSION_KEYS)

    basis = ""
    anchor = ""
    weak = False
    for key in _PHYSICAL_IDENTITY_KEYS:
        value = _text(raw.get(key))
        if value:
            basis, anchor = key, value
            break
    if not anchor:
        uri = _first_text(raw, _URI_KEYS)
        if uri:
            basis, anchor = "source_uri", uri
    if not anchor:
        filename = _first_text(raw, _FILENAME_KEYS)
        if filename:
            basis, anchor = "filename", normalize_hash_text(base_name(filename))
    if not anchor:
        content_hash = _first_text(raw, _CONTENT_HASH_KEYS)
        if content_hash:
            basis, anchor = "content_hash", normalize_hash_text(content_hash)
    if not anchor:
        for key in _WEAK_IDENTITY_KEYS:
            value = _text(raw.get(key))
            if value:
                basis, anchor, weak = key, value, True
                break

    if not anchor:
        return {
            "canonical_source_id": None,
            "identity_basis": None,
            "weak": True,
            "tenant": tenant or None,
            "knowledge_base_id": kb or None,
            "version": version or None,
        }

    material = "|".join(
        part
        for part in (
            tenant and f"t:{tenant}",
            kb and f"kb:{kb}",
            f"b:{basis}",
            f"a:{anchor}",
            version and f"v:{version}",
        )
        if part
    )
    digest = hashlib.sha256(material.encode("utf-8", "ignore")).hexdigest()[:20]
    return {
        "canonical_source_id": f"src_{digest}",
        "identity_basis": basis,
        "weak": weak,
        "tenant": tenant or None,
        "knowledge_base_id": kb or None,
        "version": version or None,
    }


def derive_evidence_id(
    *,
    canonical_source_id: str | None,
    page: int | None,
    section: str | None,
    text: str | None,
    chunk_id: str | None = None,
    raw_evidence_id: str | None = None,
) -> dict[str, Any]:
    """Id estable y determinístico para una evidencia lógica (§4).

    Nunca genera dos ids para el mismo fragmento. `basis` declara de qué se
    derivó; `stable = false` cuando hubo que heredar el id original.
    """
    fingerprint = text_fingerprint(text)
    if canonical_source_id and fingerprint:
        material = f"{canonical_source_id}|p:{page or '-'}|s:{section or '-'}|{fingerprint}"
        return {
            "evidence_id": f"ev_{hashlib.sha256(material.encode('utf-8', 'ignore')).hexdigest()[:16]}",
            "basis": "canonical_source+location+text",
            "stable": True,
        }
    if canonical_source_id and chunk_id:
        material = f"{canonical_source_id}|chunk:{chunk_id}"
        return {
            "evidence_id": f"ev_{hashlib.sha256(material.encode('utf-8', 'ignore')).hexdigest()[:16]}",
            "basis": "canonical_source+chunk",
            "stable": True,
        }
    if raw_evidence_id:
        return {
            "evidence_id": raw_evidence_id,
            "basis": "inherited_evidence_id",
            "stable": False,
        }
    return {"evidence_id": None, "basis": None, "stable": False}


__all__ = [
    "DISPLAY_NAME_KEYS",
    "base_name",
    "canonical_source_identity",
    "derive_evidence_id",
    "is_generated_name",
    "is_unavailable_name",
    "is_uuidish",
    "normalize_hash_text",
    "normalize_text",
    "resolve_display_name",
    "text_fingerprint",
]
