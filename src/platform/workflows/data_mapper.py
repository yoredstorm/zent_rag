# =============================================================================
# Universal Data & Capability Mapper.
#
# No crea vector store, catálogo ni binder. Proyecta fuentes que ya existen
# (managed_db, knowledge bases, capabilities, workflow state, memoria) a
# entradas tipadas. El LLM no elige tablas ni escribe SQL.
# =============================================================================
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

MAPPING_SCHEMA = "zent.data.mapping/v1"
PREVIEW_LIMIT = 5
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

PLANES: tuple[str, ...] = (
    "workflow.state",
    "conversation.context",
    "role.profile",
    "knowledge.rag",
    "long_term_memory",
)

# Destino tipado. Un rol nuevo reusa estos tipos; no hay rama por profesión.
TYPED_TARGETS: dict[str, dict[str, Any]] = {
    "product": {"type": "string", "plane": "workflow.state", "sensitivity": "public"},
    "quantity": {"type": "integer", "plane": "workflow.state", "sensitivity": "public"},
    "exercise": {"type": "string", "plane": "knowledge.rag", "sensitivity": "internal"},
    "progress": {
        "type": "object",
        "plane": "long_term_memory",
        "sensitivity": "personal",
        "consent": True,
    },
    "ticket": {"type": "string", "plane": "workflow.state", "sensitivity": "internal"},
    "cart": {
        "type": "array",
        "plane": "workflow.state",
        "sensitivity": "personal",
        "roles": ("seller", "support"),
    },
    "wellness_note": {
        "type": "string",
        "plane": "conversation.context",
        "sensitivity": "clinical",
        "roles": ("wellness", "human_support"),
        "retention": "none",
    },
}

_SECRET_NAMES = frozenset(
    {"password", "secret", "token", "api_key", "hook_secret", "credential", "authorization"}
)
_PRIVATE_PLANES = frozenset({"long_term_memory", "conversation.context", "workflow.state"})


class DataMapError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def data_plane_inventory() -> dict[str, Any]:
    """Dónde vive cada plano. Ninguna entrada abre un almacén nuevo."""
    return {
        "planes": list(PLANES),
        "stores": {
            "workflow.state": "workflow_instances.state",
            "conversation.context": "context_store + context_envelope",
            "role.profile": "role profile del asistente, sin datos del cliente",
            "knowledge.rag": "knowledge bases y RAG ya existentes",
            "long_term_memory": "MemoryRecord del tenant, sin índice vectorial propio",
            "sql": "bindings.managed_db, SELECT declarativo",
            "capabilities": "capability_registry + bindings",
        },
        "duplicate_vector_store": False,
    }


def project_source(raw: dict[str, Any]) -> dict[str, Any]:
    """Normaliza una fuente ya descubierta (catálogo, KB o capability)."""
    kind = str(raw.get("kind") or raw.get("provider_kind") or "")
    if kind in {"vector", "vector_store", "qdrant"}:
        raise DataMapError("duplicate_store", "el vector store ya es el de Knowledge OS")
    fields = []
    for field in raw.get("fields") or []:
        if isinstance(field, str):
            fields.append({"name": field, "type": "string"})
        elif isinstance(field, dict) and field.get("name"):
            fields.append(
                {
                    "name": str(field["name"]),
                    "type": str(field.get("type") or field.get("data_type") or "string"),
                }
            )
    source_id = str(raw.get("id") or raw.get("source_id") or raw.get("capability_ref") or "")
    if not source_id:
        raise DataMapError("contract_mismatch", "fuente sin id")
    projected = {
        "id": source_id,
        "kind": kind or "capability",
        "label": str(raw.get("label") or raw.get("name") or source_id),
        "fields": fields,
        "read_only": kind not in {"commerce", "payment_provider"},
        "capability_ref": raw.get("capability_ref"),
        "kb_id": raw.get("kb_id"),
        "document_id": raw.get("document_id"),
        "table": raw.get("table"),
        "required_permission": raw.get("required_permission"),
    }
    return {key: value for key, value in projected.items() if value is not None}


def inspect_schema(source: dict[str, Any], *, permissions: frozenset[str] | set[str] | None = None) -> dict[str, Any]:
    needed = source.get("required_permission")
    if needed and permissions is not None and str(needed) not in permissions:
        raise DataMapError("permission_denied", f"falta permiso {needed}")
    fields = []
    for field in source.get("fields") or []:
        name = str(field.get("name") or "")
        if _is_secret_name(name):
            continue
        fields.append({"name": name, "type": str(field.get("type") or "string")})
    return {
        "id": source.get("id"),
        "kind": source.get("kind"),
        "read_only": bool(source.get("read_only", True)),
        "fields": fields,
        "capability_ref": source.get("capability_ref"),
    }


def preview_rows(rows: list[dict[str, Any]] | None, *, limit: int = PREVIEW_LIMIT) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or PREVIEW_LIMIT), PREVIEW_LIMIT))
    body = list(rows or [])
    preview = [_redact_row(row) for row in body[:safe_limit]]
    return {
        "rows": preview,
        "row_count": len(body),
        "truncated": len(body) > safe_limit,
        "invented": False,
    }


def declarative_select(spec: dict[str, Any]) -> dict[str, Any]:
    """SELECT parametrizado. Un texto SQL del usuario no entra."""
    if spec.get("sql") or spec.get("statement") or spec.get("query"):
        raise DataMapError("raw_sql", "SQL libre rechazado")
    op = str(spec.get("op") or "select").lower()
    if op != "select":
        ref = str(spec.get("capability_ref") or "")
        if not ref:
            raise DataMapError("write_denied", "escritura solo con una acción de negocio autorizada")
        return {"mode": "capability", "capability_ref": ref, "sql": None, "params": {}}
    table = _ident(str(spec.get("table") or ""))
    columns = spec.get("columns") or []
    if not isinstance(columns, list) or not columns:
        raise DataMapError("contract_mismatch", "columns requerido")
    cols_sql = ", ".join(_ident(str(column)) for column in columns)
    filters = spec.get("filters") if isinstance(spec.get("filters"), dict) else {}
    where_parts: list[str] = []
    params: dict[str, Any] = {}
    for index, (column, value) in enumerate(list(filters.items())[:20]):
        where_parts.append(f"{_ident(str(column))} = :f{index}")
        params[f"f{index}"] = value
    try:
        limit = min(max(int(spec.get("limit") or PREVIEW_LIMIT), 1), 50)
    except (TypeError, ValueError):
        limit = PREVIEW_LIMIT
    sql = f"SELECT {cols_sql} FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += f" LIMIT {limit}"
    return {"mode": "read", "sql": sql, "params": params, "table": table}


def mapping_errors(
    document: dict[str, Any],
    *,
    permissions: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Errores que impiden guardar. Vacío = el documento se puede persistir."""
    if not isinstance(document, dict):
        return ["documento inválido"]
    if document.get("schema") != MAPPING_SCHEMA:
        return ["schema de mapping ausente"]
    errors: list[str] = []
    sources = document.get("sources") if isinstance(document.get("sources"), list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            errors.append("fuente inválida")
            continue
        try:
            projected = project_source(source)
        except DataMapError as exc:
            errors.append(exc.message)
            continue
        if projected["id"] in by_id:
            errors.append(f"fuente duplicada: {projected['id']}")
        by_id[projected["id"]] = projected
        kind = projected["kind"]
        if kind in {"managed_db", "connected_db", "rest_api"} and not projected.get("capability_ref"):
            errors.append(f"{projected['id']}: consulta externa sin capability_ref")
        if kind in {"knowledge_file", "knowledge_base"} and not (
            projected.get("kb_id") or projected.get("document_id")
        ):
            errors.append(f"{projected['id']}: conocimiento sin kb_id")
        needed = projected.get("required_permission")
        if needed and permissions is not None and str(needed) not in permissions:
            errors.append(f"permission_denied: {needed}")
    mappings = document.get("mappings") if isinstance(document.get("mappings"), list) else []
    if not mappings:
        errors.append("sin mappings")
    sample: dict[str, Any] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            errors.append("mapping inválido")
            continue
        source = by_id.get(str(mapping.get("source_id") or ""))
        field_name = str(mapping.get("field") or "")
        target = str(mapping.get("target") or "")
        if source is None:
            errors.append(f"fuente inexistente: {mapping.get('source_id')}")
            continue
        field = next((item for item in source["fields"] if item["name"] == field_name), None)
        if field is None:
            errors.append(f"schema_changed: {source['id']}.{field_name}")
            continue
        if _is_secret_name(field_name):
            errors.append(f"secreto no mapeable: {field_name}")
            continue
        spec = TYPED_TARGETS.get(target)
        if spec is None:
            errors.append(f"tipo desconocido: {target}")
            continue
        if str(field.get("type") or "string") != spec["type"]:
            errors.append(f"contract_mismatch: {target} espera {spec['type']}")
            continue
        plane = str(mapping.get("plane") or spec["plane"])
        if plane != spec["plane"]:
            errors.append(f"plane_mismatch: {target} vive en {spec['plane']}")
        if plane == "role.profile" and spec["sensitivity"] != "public":
            errors.append("role.profile no guarda datos del cliente")
        sample[target] = _placeholder(spec["type"])
    output_schema = document.get("output_schema") if isinstance(document.get("output_schema"), dict) else {}
    if output_schema:
        from src.platform.workflows.bindings import validate_contract

        for key in output_schema.get("required") or []:
            if key not in sample:
                errors.append(f"output sin mapping: {key}")
        errors.extend(validate_contract(sample, output_schema))
    memory = document.get("memory") if isinstance(document.get("memory"), dict) else {}
    if memory.get("enabled"):
        errors.extend(_memory_document_errors(memory, mappings))
    return errors


def assert_graph_mapping(graph: dict[str, Any] | None) -> None:
    raw = ((graph or {}).get("metadata") or {}).get("data_mapping")
    if not isinstance(raw, dict):
        return
    errors = mapping_errors(raw)
    if errors:
        raise ValueError("data mapping: " + "; ".join(errors[:8]))


def apply_read(
    rows: list[dict[str, Any]] | None,
    *,
    target: str,
    field: str,
) -> dict[str, Any]:
    """Una fila ausente no se inventa."""
    body = list(rows or [])
    if not body or field not in body[0] or body[0].get(field) in (None, ""):
        return {
            "value": None,
            "invented": False,
            "fallback": missing_fallback("row"),
        }
    spec = TYPED_TARGETS.get(target)
    if spec is None:
        raise DataMapError("contract_mismatch", f"tipo desconocido: {target}")
    return {
        "value": body[0].get(field),
        "invented": False,
        "target": target,
        "plane": spec["plane"],
        "fallback": None,
    }


def missing_fallback(kind: str) -> dict[str, Any]:
    """Sin memoria, KB o fila: preguntar, citar o reconocer el límite."""
    if kind == "clinical":
        return {
            "action": "limit",
            "claim": None,
            "message": "No tengo una fuente clínica. No afirmo síntomas ni diagnóstico.",
        }
    if kind == "progress":
        return {
            "action": "limit",
            "claim": None,
            "message": "No hay progreso consentido y respaldado. No declaro avance.",
        }
    if kind == "knowledge":
        return {
            "action": "cite",
            "claim": None,
            "message": "No encontré una fuente. Puedo preguntar o citar cuando haya un documento.",
        }
    if kind == "memory":
        return {
            "action": "ask",
            "claim": None,
            "message": "No tengo memoria autorizada para esto. ¿Me lo confirmas?",
        }
    return {
        "action": "ask",
        "claim": None,
        "message": "No encontré esa fila. Dime otro dato para buscarla.",
    }


def assemble_min_context(
    *,
    mission: str,
    actor: dict[str, Any],
    pieces: list[dict[str, Any]],
    consent: bool = False,
) -> dict[str, Any]:
    """Misión + estado + hechos con procedencia. Sin evidencia inventada."""
    kept: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    for piece in pieces:
        reason = _piece_omission(piece, actor, consent=consent)
        if reason:
            omitted.append({"source": str(piece.get("source") or ""), "reason": reason})
            continue
        kept.append(
            {
                "plane": piece.get("plane"),
                "source": piece.get("source"),
                "timestamp": piece.get("timestamp"),
                "scope": piece.get("scope"),
                "confidence": piece.get("confidence"),
                "quality": piece.get("quality"),
                "value": piece.get("value"),
                "label": piece.get("label") or piece.get("source"),
            }
        )
    return {
        "mission": str(mission or "")[:500],
        "pieces": kept,
        "omitted": omitted,
        "invented": False,
    }


def can_read(actor: dict[str, Any], piece: dict[str, Any]) -> bool:
    if str(actor.get("organization_id") or "") != str(piece.get("organization_id") or ""):
        return False
    actor_ws = actor.get("workspace_id")
    piece_ws = piece.get("workspace_id")
    if actor_ws and piece_ws and str(actor_ws) != str(piece_ws):
        return False
    if str(piece.get("plane") or "") == "conversation.context":
        if piece.get("session_id") and str(piece.get("session_id")) != str(actor.get("session_id") or ""):
            return False
    target = str(piece.get("target") or "")
    spec = TYPED_TARGETS.get(target, {})
    roles = spec.get("roles")
    if roles and str(actor.get("role") or "") not in roles:
        return False
    if spec.get("sensitivity") in {"personal", "clinical"}:
        if str(piece.get("subject_id") or "") != str(actor.get("subject_id") or ""):
            return False
    return True


def accept_memory(record: dict[str, Any], *, key: bytes | None = None) -> dict[str, Any]:
    """Opt-in: finalidad, sujeto, workspace, expiración. Clínico no se retiene."""
    if not record.get("consent"):
        raise DataMapError("consent_required", "memoria sin consentimiento")
    purpose = str(record.get("purpose") or "").strip()
    subject_id = str(record.get("subject_id") or "").strip()
    workspace_id = str(record.get("workspace_id") or "").strip()
    organization_id = str(record.get("organization_id") or "").strip()
    if not purpose or not subject_id or not workspace_id or not organization_id:
        raise DataMapError("contract_mismatch", "memoria sin finalidad, sujeto o ámbito")
    expires_at = str(record.get("expires_at") or "").strip()
    if not expires_at:
        raise DataMapError("contract_mismatch", "memoria sin expiración")
    sensitivity = str(record.get("sensitivity") or "personal")
    if sensitivity == "clinical" and not record.get("retention_justification"):
        raise DataMapError("no_retention", "conversación clínica sin retención")
    value = record.get("value")
    stored: Any = value
    if sensitivity in {"personal", "clinical"}:
        if not isinstance(value, dict) or value.get("enc") != "fernet":
            if key is None:
                raise DataMapError("encryption_required", "dato sensible sin cifra")
            stored = seal_sensitive(value, key)
    return {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "subject_id": subject_id,
        "purpose": purpose,
        "sensitivity": sensitivity,
        "expires_at": expires_at,
        "consent": True,
        "value": stored,
        "status": "active",
        "version": int(record.get("version") or 1),
        "plane": "long_term_memory",
    }


def seal_sensitive(value: Any, key: bytes) -> dict[str, str]:
    token = Fernet(key).encrypt(_plain(value).encode("utf-8")).decode("ascii")
    return {"enc": "fernet", "ciphertext": token}


def open_sensitive(envelope: dict[str, Any], key: bytes) -> str:
    if not isinstance(envelope, dict) or envelope.get("enc") != "fernet":
        raise DataMapError("encryption_required", "sobre de cifrado inválido")
    try:
        return Fernet(key).decrypt(str(envelope.get("ciphertext") or "").encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise DataMapError("encryption_required", "no se pudo abrir el dato") from exc


def export_memory(record: dict[str, Any], actor: dict[str, Any], *, key: bytes | None = None) -> dict[str, Any]:
    _assert_memory_actor(record, actor)
    value = record.get("value")
    if isinstance(value, dict) and value.get("enc") == "fernet":
        if key is None:
            raise DataMapError("encryption_required", "exportación sin llave")
        value = open_sensitive(value, key)
    return {
        "purpose": record.get("purpose"),
        "subject_id": record.get("subject_id"),
        "expires_at": record.get("expires_at"),
        "value": value,
        "plane": "long_term_memory",
    }


def correct_memory(
    record: dict[str, Any],
    actor: dict[str, Any],
    new_value: Any,
    *,
    key: bytes | None = None,
) -> dict[str, Any]:
    _assert_memory_actor(record, actor)
    updated = dict(record)
    updated["value"] = new_value
    updated["version"] = int(record.get("version") or 1) + 1
    return accept_memory(updated, key=key)


def erase_memory(record: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    _assert_memory_actor(record, actor)
    erased = dict(record)
    erased["value"] = None
    erased["status"] = "erased"
    erased["erased_at"] = datetime.now(timezone.utc).isoformat()
    return erased


def _assert_memory_actor(record: dict[str, Any], actor: dict[str, Any]) -> None:
    target = str(record.get("target") or "")
    if not target:
        target = "wellness_note" if record.get("sensitivity") == "clinical" else "progress"
    if not can_read(
        actor,
        {
            "organization_id": record.get("organization_id"),
            "workspace_id": record.get("workspace_id"),
            "subject_id": record.get("subject_id"),
            "session_id": record.get("session_id"),
            "plane": "long_term_memory",
            "target": target,
            "sensitivity": record.get("sensitivity") or "personal",
        },
    ):
        raise DataMapError("isolation", "memoria fuera del sujeto o del rol")


def _memory_document_errors(memory: dict[str, Any], mappings: list[Any]) -> list[str]:
    errors: list[str] = []
    if not memory.get("consent"):
        errors.append("consent_required")
    if not str(memory.get("purpose") or "").strip():
        errors.append("memoria sin finalidad")
    if not str(memory.get("expires_at") or "").strip():
        errors.append("memoria sin expiración")
    clinical = False
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        spec = TYPED_TARGETS.get(str(mapping.get("target") or ""))
        if spec and spec.get("sensitivity") == "clinical":
            clinical = True
    if clinical and not memory.get("retention_justification"):
        errors.append("no_retention")
    return errors


def _piece_omission(piece: dict[str, Any], actor: dict[str, Any], *, consent: bool) -> str | None:
    if not piece.get("source") or not piece.get("timestamp") or not piece.get("scope"):
        return "sin procedencia"
    if piece.get("invented"):
        return "evidencia inventada"
    plane = str(piece.get("plane") or "")
    if plane == "role.profile" and piece.get("sensitivity") not in (None, "public"):
        return "perfil no guarda datos del cliente"
    if plane in _PRIVATE_PLANES and piece.get("sensitivity") in {"personal", "clinical"} and not consent:
        return "sin consentimiento"
    if not can_read(actor, piece):
        return "aislamiento"
    return None


def _placeholder(type_name: str) -> Any:
    return {
        "string": "ejemplo",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "object": {"ok": True},
        "array": ["ejemplo"],
    }.get(type_name, "ejemplo")


def _ident(value: str) -> str:
    if not _IDENT.match(value or ""):
        raise DataMapError("raw_sql", f"identificador rechazado: {value}")
    return value


def _is_secret_name(name: str) -> bool:
    folded = str(name or "").lower()
    return folded in _SECRET_NAMES or any(part in folded for part in _SECRET_NAMES)


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in row.items():
        if _is_secret_name(str(key)):
            clean[str(key)] = "[redactado]"
        elif isinstance(value, str):
            clean[str(key)] = value[:200]
        else:
            clean[str(key)] = value
    return clean


def _plain(value: Any) -> str:
    if isinstance(value, str):
        return value
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
