# =============================================================================
# P19.1-04 - Contrato de resultado del nodo data_query (v2).
#
# Separa estados de dominio (NOT_FOUND no es un fallo) de fallos operativos y
# de seguridad/contrato. El envelope v2 se agrega sobre los campos v1 para no
# romper workflows existentes.
# =============================================================================
from __future__ import annotations

from typing import Any

DATA_QUERY_RESULT_SCHEMA = "zent.workflow.data-query.result/v2"
DOMAIN_STATUSES = frozenset({"FOUND", "NOT_FOUND", "MULTIPLE_MATCHES", "NO_LONGER_VALID"})
OPERATIONAL_CODES = frozenset(
    {
        "TIMEOUT",
        "CONNECTION_FAILED",
        "PROVIDER_UNAVAILABLE",
        "SCHEMA_DRIFT",
        "PROVIDER_ERROR",
        "PROVIDER_NOT_SUPPORTED",
        "RESOURCE_NOT_EXPOSED",
        "NEEDS_CREDENTIALS",
        "NEEDS_CONFIGURATION",
    }
)
SECURITY_CODES = frozenset(
    {
        "PERMISSION_DENIED",
        "IDENTITY_REQUIRED",
        "PLAN_STALE",
        "BINDING_CHANGED",
        "SENSITIVE_COLUMN_DENIED",
        "POLICY_STALE",
        "POLICY_REQUIRED",
        "RESOURCE_NOT_ALLOWED",
        "COLUMN_NOT_ALLOWED",
        "SYSTEM_SCHEMA_DENIED",
        "PURPOSE_REQUIRED",
    }
)
CONTRACT_CODES = frozenset(
    {
        "INVALID_PARAMS",
        "UNEXPECTED_PARAMETER",
        "CONTRACT_INVALID",
    }
)

_SAFE_MESSAGES = {
    "PERMISSION_DENIED": "No tienes permiso para esta lectura.",
    "IDENTITY_REQUIRED": "Falta verificar la identidad del titular.",
    "PLAN_STALE": "La consulta cambió; revisar y republicar.",
    "BINDING_CHANGED": "La consulta cambió; revisar y republicar.",
    "POLICY_STALE": "La política de datos cambió; revisar y republicar.",
    "POLICY_REQUIRED": "La conexión no tiene una política de publicación.",
    "SENSITIVE_COLUMN_DENIED": "La consulta incluye una columna restringida.",
    "TIMEOUT": "La consulta tardó demasiado.",
    "CONNECTION_FAILED": "La conexión no respondió.",
    "PROVIDER_UNAVAILABLE": "La fuente no está disponible.",
    "SCHEMA_DRIFT": "La estructura de la fuente cambió.",
    "INVALID_PARAMS": "Los datos de búsqueda no son válidos.",
    "NOT_FOUND": "No hay coincidencias.",
    "MULTIPLE_MATCHES": "Hay varias coincidencias.",
    "FOUND": "Encontré la información.",
}


def _category(code: str) -> str:
    if code in SECURITY_CODES:
        return "security"
    if code in CONTRACT_CODES:
        return "contract"
    if code in OPERATIONAL_CODES:
        return "operational"
    return "configuration"


def _base_envelope(
    *,
    status: str,
    category: str,
    reason_code: str | None,
    capability_ref: str | None,
    correlation_id: str | None,
    recoverable: bool,
    retryable: bool,
    safe_message: str,
) -> dict[str, Any]:
    return {
        "schema": DATA_QUERY_RESULT_SCHEMA,
        "status": status,
        "category": category,
        "reason_code": reason_code,
        "recoverable": recoverable,
        "retryable": retryable,
        "found": False,
        "record": None,
        "rows": [],
        "count": None,
        "row_count": 0,
        "truncated": False,
        "data_as_of": None,
        "source_ref": None,
        "binding_ref": None,
        "binding_hash": None,
        "duration_ms": 0,
        "correlation_id": correlation_id,
        "provenance": {},
        "safe_message": safe_message,
        "capability": capability_ref,
    }


def error_envelope(
    code: str,
    *,
    capability_ref: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    safe_code = str(code or "PROVIDER_ERROR")
    return _base_envelope(
        status="ERROR",
        category=_category(safe_code),
        reason_code=safe_code,
        capability_ref=capability_ref,
        correlation_id=correlation_id,
        recoverable=safe_code in {"IDENTITY_REQUIRED", "PURPOSE_REQUIRED"},
        retryable=safe_code in {"TIMEOUT", "CONNECTION_FAILED", "PROVIDER_UNAVAILABLE"},
        safe_message=_SAFE_MESSAGES.get(safe_code, "No se pudo completar la consulta."),
    )


def success_envelope(output: dict[str, Any], *, capability_ref: str | None = None) -> dict[str, Any]:
    status = str(output.get("status") or ("FOUND" if output.get("found") else "NOT_FOUND"))
    if status == "SIMULATED":
        category = "simulation"
        safe_message = "Vista previa simulada; no es un dato certificado."
    elif status in DOMAIN_STATUSES:
        category = "domain"
        safe_message = _SAFE_MESSAGES.get(status, "Consulta completada.")
    else:
        category = "operational"
        safe_message = "La consulta no devolvió un resultado utilizable."
    envelope = dict(output)
    envelope.update(
        {
            "schema": DATA_QUERY_RESULT_SCHEMA,
            "status": status,
            "category": category,
            "reason_code": output.get("reason_code"),
            "recoverable": bool(output.get("recoverable", False)),
            "retryable": bool(output.get("retryable", False)),
            "found": bool(output.get("found", False)),
            "count": (
                output.get("row_count")
                if status == "FOUND" and output.get("operation") == "count"
                else None
            ),
            "rows": list(output.get("rows") or []),
            "record": output.get("record"),
            "truncated": bool(output.get("truncated", False)),
            "data_as_of": output.get("data_as_of"),
            "source_ref": output.get("source_ref"),
            "binding_ref": output.get("binding_ref"),
            "binding_hash": output.get("binding_hash"),
            "duration_ms": int(output.get("duration_ms") or 0),
            "provenance": dict(output.get("provenance") or {}),
            "safe_message": safe_message,
            "capability": capability_ref or output.get("capability"),
        }
    )
    return envelope


__all__ = [
    "CONTRACT_CODES",
    "DATA_QUERY_RESULT_SCHEMA",
    "DOMAIN_STATUSES",
    "OPERATIONAL_CODES",
    "SECURITY_CODES",
    "error_envelope",
    "success_envelope",
]
