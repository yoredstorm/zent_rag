# =============================================================================
# Knowledge Session — semántica humana de los eventos técnicos
# =============================================================================
# El backend emite ENTITY_MATCHED; la UI muestra "ZENT reconoció una entidad
# que ya conocía". La traducción vive aquí para que cualquier consumidor
# (portal, SDK, webhooks) hable el mismo idioma.
#
# Nada de esto inventa actividad: cada texto describe un evento real y su
# payload viene del trabajo del Knowledge Compiler.
# =============================================================================
from __future__ import annotations


def _first(payload: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return default


def _count(payload: dict) -> int:
    try:
        return max(1, int(payload.get("count") or 1))
    except (TypeError, ValueError):
        return 1


def describe(event_type: str, payload: dict | None = None) -> str:
    """Mensaje humano para un evento semántico real."""
    data = payload or {}
    count = _count(data)
    suffix = f" (+{count})" if count > 1 else ""

    if event_type == "SOURCE_RECEIVED":
        name = _first(data, "name", "filename", default="fuente")
        return f"ZENT recibió {name}"
    if event_type == "PARSING_STARTED":
        name = _first(data, "name", "filename", default="la fuente")
        return f"ZENT empezó a leer {name}"
    if event_type == "STRUCTURE_DISCOVERED":
        pages = int(data.get("pages") or 0)
        tables = int(data.get("tables") or 0)
        if pages and tables:
            return f"ZENT comprendió la estructura: {pages} páginas, {tables} tablas"
        if pages:
            return f"ZENT comprendió la estructura de {pages} páginas"
        return "ZENT comprendió la estructura de la fuente"
    if event_type == "TABLE_DETECTED":
        name = _first(data, "table", "name", default="una tabla")
        columns = int(data.get("columns") or 0)
        rows = int(data.get("rows") or 0)
        detail = []
        if columns:
            detail.append(f"{columns} columnas")
        if rows:
            detail.append(f"{rows} registros")
        extra = f" ({', '.join(detail)})" if detail else ""
        if name == "una tabla" and count > 1:
            return f"ZENT detectó {count} tablas"
        return f"ZENT detectó la tabla {name}{extra}{suffix}"
    if event_type == "SEMANTIC_RECONSTRUCTED":
        raw_blocks = int(data.get("raw_blocks") or 0)
        reconstructed = int(data.get("reconstructed") or 0)
        if reconstructed:
            return (
                f"ZENT reconstruyó el significado de la fuente "
                f"({reconstructed} unidades recompuestas de {raw_blocks} bloques)"
            )
        if raw_blocks:
            return f"ZENT reconstruyó la estructura de {raw_blocks} bloques"
        return "ZENT reconstruyó el significado de la fuente"
    if event_type == "CONTINUATIONS_MERGED":
        return (
            f"ZENT reconstruyó {count} bloques que estaban divididos por el formato original"
            if count > 1
            else "ZENT reconstruyó un bloque dividido por el formato original"
        )
    if event_type == "FRAGMENTS_REJECTED":
        return (
            f"ZENT descartó {count} fragmentos incompletos"
            if count > 1
            else "ZENT descartó un fragmento incompleto"
        )
    if event_type == "SCHEMAS_INFERRED":
        return (
            f"ZENT reconoció la estructura de {count} tablas u hojas"
            if count > 1
            else "ZENT reconoció la estructura de una tabla u hoja"
        )
    if event_type == "SEMANTIC_UNIT_CREATED":
        return f"ZENT creó {count} unidades semánticas" if count > 1 else "ZENT creó una unidad semántica"
    if event_type == "ENTITY_DISCOVERED":
        if count > 1:
            return f"ZENT reconoció {count} entidades nuevas"
        name = _first(data, "name", default="una entidad")
        return f"ZENT reconoció una entidad nueva: {name}"
    if event_type == "ENTITY_MATCHED":
        if count > 1:
            return f"ZENT reconoció {count} entidades que ya conocía"
        name = _first(data, "name", default="una entidad")
        return f"ZENT reconoció una entidad que ya conocía: {name}"
    if event_type == "ENTITY_MERGED":
        if count > 1:
            return f"ZENT consolidó {count} entidades con su nodo existente"
        merged = _first(data, "merged_alias", "name", default="un alias")
        canonical = _first(data, "canonical_name", default="")
        if canonical:
            return f"ZENT fusionó {merged} con {canonical}"
        return f"ZENT fusionó {merged} con un nodo existente"
    if event_type == "FACT_DISCOVERED":
        if count > 1:
            return f"ZENT incorporó {count} hechos"
        subject = _first(data, "subject", default="una entidad")
        return f"ZENT incorporó un hecho sobre {subject}"
    if event_type == "FACT_REINFORCED":
        if count > 1:
            return f"ZENT reforzó {count} hechos ya conocidos"
        subject = _first(data, "subject", default="una entidad")
        return f"ZENT reforzó un hecho que ya conocía sobre {subject}"
    if event_type == "RELATIONSHIP_DISCOVERED":
        if count > 1:
            return f"ZENT descubrió {count} relaciones"
        subject = _first(data, "subject", default="")
        obj = _first(data, "object", "object_name", default="")
        if subject and obj:
            return f"ZENT descubrió una relación: {subject} y {obj}"
        return "ZENT descubrió una relación nueva"
    if event_type == "RULE_DISCOVERED":
        if count > 1:
            return f"ZENT aprendió {count} reglas"
        return "ZENT aprendió una regla del negocio"
    if event_type == "TEMPORAL_RANGE_DISCOVERED":
        start = _first(data, "effective_from", "from", default="")
        end = _first(data, "effective_to", "to", default="")
        if start and end:
            return f"ZENT entendió la vigencia: {start} a {end}"
        if start:
            return f"ZENT entendió la vigencia desde {start}"
        return "ZENT entendió la vigencia temporal de esta fuente"
    if event_type == "KNOWLEDGE_OBJECT_CREATED":
        objects = int(data.get("objects") or 0)
        return f"ZENT creó {objects} objetos de conocimiento" if objects else "ZENT creó objetos de conocimiento"
    if event_type == "CONFLICT_DETECTED":
        return "ZENT detectó una posible inconsistencia"
    if event_type == "DUPLICATE_DETECTED":
        return "ZENT consolidó contenido duplicado"
    if event_type == "EVIDENCE_LINKED":
        return f"ZENT vinculó {count} evidencias" if count > 1 else "ZENT vinculó una evidencia"
    if event_type == "INDEX_UPDATED":
        chunks = int(data.get("chunks") or 0)
        if chunks:
            return f"ZENT actualizó los índices ({chunks} fragmentos)"
        return "ZENT actualizó los índices de búsqueda"
    if event_type == "KNOWLEDGE_READY":
        return "El conocimiento de esta fuente ya está consolidado"
    if event_type == "SOURCE_AVAILABLE":
        name = _first(data, "name", "filename", default="la fuente")
        return f"{name} ya puede responder preguntas"
    if event_type == "SOURCE_FAILED":
        return "ZENT tuvo un problema con esta fuente"
    if event_type == "SESSION_STARTED":
        return "ZENT comenzó a aprender"
    if event_type == "SESSION_COMPLETED":
        return "ZENT terminó de aprender esta información"
    if event_type == "SESSION_FAILED":
        return "ZENT no pudo completar el aprendizaje"
    if event_type == "WARNING":
        return _first(data, "warning", "message", default="Aviso durante el aprendizaje")
    return event_type.replace("_", " ").capitalize()


def severity_for(event_type: str, payload: dict | None = None) -> str:
    if event_type in {"SOURCE_FAILED", "SESSION_FAILED"}:
        return "error"
    if event_type in {"CONFLICT_DETECTED", "DUPLICATE_DETECTED", "WARNING"}:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# Recuperación: errores humanos con detalle técnico adjunto (requisito 22)
# ---------------------------------------------------------------------------

_HUMAN_ERRORS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("rate limit", "429", "quota", "resource_exhausted"),
        "ZENT llegó al límite del proveedor de embeddings. Reintentará automáticamente.",
    ),
    (
        ("timeout", "timed out", "deadline"),
        "La fuente tardó demasiado en responder. ZENT reintentará con más tiempo.",
    ),
    (
        ("encrypted", "password", "corrupt", "malformed pdf", "invalid pdf"),
        "ZENT no pudo leer el archivo: parece protegido o dañado.",
    ),
    (
        ("no structured parser", "unsupported", "unsupported format", "mimerejected"),
        "ZENT no reconoce este formato todavía. La fuente quedó sin aprender.",
    ),
    (
        ("table", "sheet", "xlsx", "excel", "csv"),
        "ZENT tuvo un problema al interpretar una tabla. El resto de la fuente se conservó.",
    ),
    (
        ("connector", "connection", "connect", "dns", "refused", "unreachable"),
        "ZENT no pudo conectarse con esta fuente. Las demás continuaron procesándose.",
    ),
)


def humanize_error(exc: BaseException | str | None) -> str:
    """Traduce un fallo técnico a una frase que un humano entiende."""
    raw = str(exc or "").lower()
    if not raw:
        return "ZENT tuvo un problema al procesar esta fuente."
    for needles, message in _HUMAN_ERRORS:
        if any(needle in raw for needle in needles):
            return message
    return "ZENT tuvo un problema al procesar esta fuente. Las demás continuaron."


__all__ = ["describe", "humanize_error", "severity_for"]
