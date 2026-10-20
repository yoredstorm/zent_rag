# =============================================================================
# Intelligent Capability Registry — proyección canónica zent.capability/v1.
#
# Una capacidad no es un nombre: es un contrato ejecutable, gobernado y
# versionado. Este módulo COMPONE las fuentes de verdad existentes (registry de
# nodos, node_catalog, commerce contracts, bindings, Marketplace, agentes,
# tools, knowledge bases, managed DBs, conectores y eventos) y expone:
#
#   * CapabilityDescriptor (contrato + disponibilidad real por tenant)
#   * búsqueda determinista (exacta → alias → texto → semántica opcional)
#   * snapshot con hash de contratos y cache invalidable
#   * verificación de snapshot para no publicar con contratos obsoletos
#   * cobertura del catálogo y brechas de contrato
#
# No crea un segundo Marketplace ni duplica registros: lee y proyecta.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

CAPABILITY_SCHEMA = "zent.capability/v1"
SNAPSHOT_SCHEMA = "zent.capability.snapshot/v1"
COVERAGE_SCHEMA = "zent.capability.coverage/v1"
CONTRACT_VERSION = 1
CATALOG_VERSION = 1

AvailabilityStatus = Literal[
    "AVAILABLE",
    "NEEDS_INSTALLATION",
    "NEEDS_CREDENTIALS",
    "NEEDS_CONFIGURATION",
    "DISABLED",
    "PERMISSION_DENIED",
    "PENDING_APPROVAL",
    "DEGRADED",
    "INCOMPATIBLE",
    "DEPRECATED",
    "UNAVAILABLE",
    "UNKNOWN",
]
CapabilitySource = Literal[
    "node",
    "marketplace",
    "commerce",
    "binding",
    "agent",
    "tool",
]
SideEffect = Literal["read", "write", "external", "financial"]

_SNAPSHOT_TTL_SECONDS = 30.0
_HISTORY_TTL_SECONDS = 900.0
_HISTORY_MAX = 64

_CACHE: dict[str, tuple[float, "CapabilitySnapshot"]] = {}
_HISTORY: dict[str, tuple[float, dict[str, tuple[str, str, bool]]]] = {}
_EMBEDDING_CACHE: dict[str, list[float]] = {}

_STOPWORDS = frozenset(
    {
        "que", "con", "para", "una", "uno", "los", "las", "del", "como", "cuando",
        "sobre", "por", "se", "el", "la", "de", "y", "o", "en", "un", "a", "al",
        "si", "no", "sus", "su", "cada", "es", "son", "me", "mi", "tu", "the",
        "and", "for", "with", "all", "from", "this", "that", "into", "your",
    }
)

#: Expansión funcional de negocio. No sustituye contratos: mejora el recall.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "producto": ("product", "products", "catalog", "catalogo", "item", "sku"),
    "productos": ("product", "products", "catalog", "catalogo", "item", "sku"),
    "catalogo": ("catalog", "products", "producto", "productos"),
    "inventario": ("inventory", "stock", "existencia", "disponible"),
    "stock": ("inventory", "inventario", "existencia", "disponible"),
    "existencia": ("stock", "inventory", "disponible"),
    "precio": ("price", "pricing", "cotizacion", "quote"),
    "cotizar": ("quote", "price", "cart", "carrito"),
    "cotizacion": ("quote", "price", "cart"),
    "venta": ("sales", "order", "pedido", "orden"),
    "ventas": ("sales", "order", "pedido", "orden"),
    "pedido": ("order", "sales", "venta"),
    "orden": ("order", "sales", "venta"),
    "carrito": ("cart", "basket", "items"),
    "pago": ("payment", "payments", "checkout", "cobro"),
    "pagos": ("payment", "payments", "checkout", "cobro"),
    "cobro": ("payment", "checkout", "pago"),
    "cliente": ("customer", "client", "comprador"),
    "clientes": ("customer", "client", "comprador"),
    "contribuyente": ("taxpayer", "ruc", "sunat"),
    "ruc": ("taxpayer", "sunat", "contribuyente"),
    "dni": ("identity", "reniec", "persona"),
    "identidad": ("identity", "reniec", "dni"),
    "clima": ("weather", "temperatura", "tiempo"),
    "tiempo": ("weather", "clima", "temperatura"),
    "correo": ("email", "notify", "notification", "aviso"),
    "aviso": ("notify", "notification", "alerta", "correo"),
    "alerta": ("notify", "notification", "aviso"),
    "conocimiento": ("knowledge", "document", "documento", "politica"),
    "documento": ("knowledge", "document", "politica"),
    "politica": ("knowledge", "policy", "documento"),
    "agente": ("agent", "llm", "analysis", "analisis"),
    "analizar": ("analysis", "agent", "llm"),
    "analisis": ("analysis", "agent", "llm"),
    "resumen": ("summary", "report", "reporte"),
    "reporte": ("report", "summary", "resumen"),
    "aprobar": ("approval", "human", "approve"),
    "aprobacion": ("approval", "human", "approve"),
    "esperar": ("wait", "event", "signal"),
    "evento": ("event", "signal", "wait"),
    "tabla": ("table", "database", "sql", "tabular"),
    "datos": ("data", "database", "query", "tabular"),
}

_BUSINESS_TEXT: dict[str, tuple[str, str]] = {
    "catalog.products.search": (
        "Buscar productos del catálogo",
        "Encuentra productos por nombre, categoría o SKU y devuelve resultados seleccionables.",
    ),
    "catalog.product.get": (
        "Obtener un producto",
        "Recupera un producto del catálogo por id, SKU o consulta.",
    ),
    "catalog.product.price": (
        "Consultar precio de producto",
        "Devuelve el precio vigente y la moneda de un producto.",
    ),
    "inventory.stock.get": (
        "Consultar stock",
        "Consulta disponibilidad, reservado y si hay stock de un producto.",
    ),
    "inventory.reserve": (
        "Reservar inventario",
        "Reserva unidades para una orden con vigencia acotada.",
    ),
    "inventory.release": (
        "Liberar inventario",
        "Libera una reserva de inventario existente.",
    ),
    "inventory.commit": (
        "Confirmar inventario",
        "Descuenta inventario definitivamente con evidencia de pago autorizada.",
    ),
    "sales.order.create": (
        "Crear orden de venta",
        "Crea una orden con ítems, cliente y moneda; el total se calcula en el servidor.",
    ),
    "sales.cart.quote": (
        "Cotizar carrito",
        "Cotiza ítems y totales del carrito del lado del servidor.",
    ),
    "sales.order.get": (
        "Consultar orden",
        "Recupera una orden por id o número.",
    ),
    "sales.order.confirm": (
        "Confirmar orden",
        "Confirma una orden para iniciar el flujo de pago.",
    ),
    "sales.order.mark_paid": (
        "Marcar orden pagada",
        "Marca una orden como pagada con evidencia autorizada.",
    ),
    "sales.order.fulfill": (
        "Cumplir orden",
        "Registra el cumplimiento de una orden pagada.",
    ),
    "sales.order.cancel": (
        "Cancelar orden",
        "Cancela una orden y libera sus reservas.",
    ),
    "payments.checkout.create": (
        "Crear checkout de pago",
        "Crea un checkout para una orden; el monto siempre sale de la orden persistida.",
    ),
    "payments.qr.create": (
        "Crear QR de pago",
        "Genera un QR de pago para un checkout existente.",
    ),
    "payments.status.get": (
        "Consultar estado de pago",
        "Consulta el estado del pago de una referencia u orden.",
    ),
    "payments.cancel": (
        "Cancelar pago",
        "Cancela un checkout o pago existente.",
    ),
    "payments.refund": (
        "Reembolsar pago",
        "Solicita un reembolso con idempotencia obligatoria.",
    ),
    "conversation.send": (
        "Enviar mensaje al cliente",
        "Envía un mensaje por el canal resuelto por el binding del tenant.",
    ),
}

_MARKETPLACE_ERRORS = (
    ("ACTION_NOT_FOUND", "La acción no existe o fue retirada.", False),
    ("NOT_INSTALLED", "La integración no está instalada para el tenant.", False),
    ("ACTION_NOT_ENABLED", "La acción no está habilitada en la instalación.", False),
    ("CREDENTIALS_MISSING", "Faltan credenciales del proveedor.", False),
    ("PURPOSE_REQUIRED", "La acción requiere declarar una finalidad.", False),
    ("LEGAL_BASIS_REQUIRED", "La acción requiere base legal declarada.", False),
    ("APPROVAL_REQUIRED", "La acción requiere aprobación humana.", False),
    ("INPUT_VALIDATION", "Faltan o son inválidos los inputs requeridos.", False),
    ("INSTALL_PAUSED", "La instalación está pausada o suspendida.", True),
    ("PROVIDER_HTTP_ERROR", "El proveedor respondió con error HTTP.", True),
    ("PROVIDER_ERROR", "El proveedor falló.", True),
)

_BINDING_ERRORS = (
    ("NEEDS_CONFIGURATION", "La capacidad no tiene binding configurado.", False),
    ("NEEDS_CREDENTIALS", "El proveedor no está instalado o le faltan credenciales.", False),
    ("CONTRACT_INVALID", "Los datos no cumplen el contrato de la capacidad.", False),
    ("PROVIDER_NOT_IMPLEMENTED", "El proveedor declarado no tiene executor.", False),
    ("NOT_FOUND", "El recurso solicitado no existe.", False),
    ("CONFLICT", "La operación choca con el estado actual.", False),
    ("PROVIDER_ERROR", "El proveedor falló.", True),
)

_AGENT_ERRORS = (
    ("AGENT_NOT_FOUND", "El agente no existe o está inactivo.", False),
    ("AGENT_INACTIVE", "El agente está inactivo.", False),
    ("BUDGET_EXCEEDED", "El agente alcanzó su límite de presupuesto.", False),
    ("TOOL_ERROR", "Una herramienta del agente falló.", True),
    ("INSUFFICIENT_CONTEXT", "El agente no recibió contexto suficiente.", False),
)

_TOOL_ERRORS = (
    ("TOOL_NOT_FOUND", "La herramienta no está registrada.", False),
    ("TOOL_PERMISSION_DENIED", "El actor no tiene permiso para la herramienta.", False),
    ("TOOL_INPUT_ERROR", "Los argumentos no cumplen el input schema.", False),
    ("TOOL_TIMEOUT", "La herramienta excedió su timeout.", True),
)

_NODE_ERRORS = (
    ("UNKNOWN_NODE_TYPE", "El tipo de nodo no está registrado.", False),
    ("NODE_PERMISSION_DENIED", "El actor no tiene el permiso del nodo.", False),
    ("NODE_TIMEOUT", "El nodo excedió su timeout.", True),
    ("NODE_FAILED", "El nodo falló.", True),
)

_NODE_TO_STEP: dict[str, str | None] = {
    "trigger_event": "trigger_event",
    "trigger_schedule": "trigger_schedule",
    "trigger_webhook": "trigger_manual",
    "query_business_data": "business_query",
    "kb_query": "knowledge_query",
    "llm": "agent_analysis",
    "condition": "decision",
    "filter": "filter",
    "join": "join",
    "merge": "merge",
    "human_approval": "human_approval",
    "wait_event": "wait",
    "state_get": "state",
    "state_set": "state",
    "state_merge": "state",
    "state_append": "state",
    "state_remove": "state",
    "notify": "notify",
    "marketplace_action": "integration_action",
    "capability_call": "capability_call",
    "business_result": "business_result",
    "stop": "stop",
    "for_each": None,
    "ai_decision": None,
    "api_call": None,
    "set_variable": None,
    "business_node": None,
    "end": None,
}

_NODE_SIDE_EFFECTS: dict[str, tuple[SideEffect, ...]] = {
    "reads_db": ("read",),
    "writes_db": ("write",),
    "calls_external": ("external",),
    "calls_agent": ("read",),
    "sends_notification": ("external",),
    "needs_approval": ("read",),
}

_PARAMETER_TYPES: dict[str, str] = {
    "text": "string",
    "textarea": "string",
    "email": "string",
    "person": "string",
    "team": "string",
    "timezone": "string",
    "date": "string",
    "datetime": "string",
    "time": "string",
    "duration": "string",
    "database": "string",
    "table": "string",
    "column": "string",
    "field": "string",
    "entity": "string",
    "agent": "string",
    "integration": "string",
    "action": "string",
    "template": "string",
    "data_reference": "string",
    "secret": "string",
    "number": "number",
    "money": "number",
    "percentage": "number",
    "integer": "integer",
    "boolean": "boolean",
    "enum": "string",
    "json": "object",
    "record": "object",
    "record_list": "array",
    "document": "object",
    "evidence": "object",
    "binary": "string",
    "condition": "object",
}

_SECRET_CONFIG_KEYS = re.compile(r"(secret|token|password|api[_-]?key|private[_-]?key|credential)", re.I)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class CapabilityAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AvailabilityStatus = "UNKNOWN"
    exists: bool = True
    published: bool = False
    installed: bool = False
    enabled: bool = False
    configured: bool = False
    permitted: bool = False
    provider_healthy: bool | None = None
    executable: bool = False
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CapabilityError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retriable: bool = False


class CapabilityDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = CAPABILITY_SCHEMA
    capability_ref: str
    version: int = 1
    display_name: str
    description: str = ""
    owner_module: str
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    when_to_use: list[str] = Field(default_factory=list)
    when_not_to_use: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_inputs: list[str] = Field(default_factory=list)
    errors: list[CapabilityError] = Field(default_factory=list)
    side_effects: list[SideEffect] = Field(default_factory=list)
    risk_level: Literal["info", "normal", "elevated", "critical"] = "normal"
    required_permissions: list[str] = Field(default_factory=list)
    idempotency_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    available_events: list[str] = Field(default_factory=list)
    dependency_refs: list[str] = Field(default_factory=list)
    provider_kind: str = "internal"
    availability: CapabilityAvailability
    health_status: str | None = None
    supports_simulation: bool = False
    example_inputs: dict[str, Any] = Field(default_factory=dict)
    example_outputs: dict[str, Any] = Field(default_factory=dict)
    contract_hash: str = ""
    contract_gaps: list[str] = Field(default_factory=list)
    metadata_source: str = "registry"
    source: CapabilitySource = "node"
    planner_usage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def compact(self) -> dict[str, Any]:
        """Vista para búsqueda/prompt: sin contratos completos."""
        return {
            "capability_ref": self.capability_ref,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "source": self.source,
            "provider_kind": self.provider_kind,
            "risk_level": self.risk_level,
            "side_effects": self.side_effects,
            "required_inputs": self.required_inputs,
            "output_fields": sorted(
                (self.output_schema.get("properties") or {}).keys()
            ),
            "required_permissions": self.required_permissions,
            "availability": self.availability.model_dump(mode="json"),
            "supports_simulation": self.supports_simulation,
            "contract_hash": self.contract_hash,
            "contract_gaps": self.contract_gaps,
            "planner_usage": self.planner_usage,
        }


class ResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = "zent.resource/v1"
    resource_ref: str
    kind: str
    display_name: str
    description: str = ""
    status: str = "unknown"
    data_schema: dict[str, Any] = Field(default_factory=dict)
    schema_source: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    contract_hash: str = ""

    def compact(self) -> dict[str, Any]:
        return {
            "resource_ref": self.resource_ref,
            "kind": self.kind,
            "display_name": self.display_name,
            "description": self.description,
            "status": self.status,
            "schema_source": self.schema_source,
            "field_count": len((self.data_schema or {}).get("properties") or {}),
        }


class EventDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = "zent.event/v1"
    event_type: str
    version: int = 1
    business_name: str
    description: str = ""
    category: str = "sistema"
    fields: list[dict[str, Any]] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    contract_hash: str = ""
    available: bool = True

    def compact(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "version": self.version,
            "business_name": self.business_name,
            "description": self.description,
            "category": self.category,
            "field_count": len(self.fields),
            "contract_hash": self.contract_hash,
        }


class CapabilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = SNAPSHOT_SCHEMA
    snapshot_hash: str
    generated_at: datetime
    catalog_version: int = CATALOG_VERSION
    capabilities: list[CapabilityDescriptor]
    resources: list[ResourceDescriptor] = Field(default_factory=list)
    events: list[EventDescriptor] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)

    def index(self) -> dict[str, CapabilityDescriptor]:
        return {item.capability_ref: item for item in self.capabilities}

    def summary(self) -> dict[str, Any]:
        return {
            "snapshot_hash": self.snapshot_hash,
            "generated_at": self.generated_at.isoformat(),
            "catalog_version": self.catalog_version,
            "counts": {
                "capabilities": len(self.capabilities),
                "resources": len(self.resources),
                "events": len(self.events),
            },
            "coverage": self.coverage,
        }


class CapabilitySnapshotStale(ValueError):
    def __init__(self, changed_refs: list[str], reason: str) -> None:
        super().__init__("el catálogo de capacidades cambió; vuelve a interpretar el pedido")
        self.changed_refs = changed_refs
        self.reason = reason


# ---------------------------------------------------------------------------
# Helpers de texto / hash
# ---------------------------------------------------------------------------
def normalize_text(value: str) -> str:
    text_ = unicodedata.normalize("NFKD", str(value or ""))
    text_ = "".join(ch for ch in text_ if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text_.lower()).strip()


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def token_set(value: str) -> set[str]:
    tokens = {
        _stem(token)
        for token in re.findall(r"[a-z0-9]+", normalize_text(value))
        if len(token) > 1 and token not in _STOPWORDS
    }
    return tokens


def _aliases(*texts: str) -> list[str]:
    tokens: set[str] = set()
    for value in texts:
        tokens |= token_set(value)
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(_SYNONYMS.get(token, ()))
        for original, synonyms in _SYNONYMS.items():
            if token in synonyms:
                expanded.add(original)
    return sorted(item for item in expanded if item)[:80]


def canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _contract_hash(payload: dict[str, Any]) -> str:
    ignored = {"availability", "health_status", "contract_hash", "aliases", "metadata"}
    return canonical_hash({key: value for key, value in payload.items() if key not in ignored})


def _humanize(value: str) -> str:
    text_ = re.sub(r"[._-]+", " ", str(value or "")).strip()
    return text_[:1].upper() + text_[1:] if text_ else "Capacidad"


def _error_list(items: Iterable[tuple[str, str, bool]]) -> list[CapabilityError]:
    return [CapabilityError(code=code, message=message, retriable=retriable) for code, message, retriable in items]


def _permitted(permission: str | None, permissions: frozenset[str] | None) -> bool:
    if not permission:
        return True
    if permissions is None:
        return True  # caller admin: sin filtro RBAC (mismo criterio que catalog_availability)
    return "admin:*" in permissions or permission in permissions


def _schema_from_parameters(parameters: list[Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in parameters:
        key = str(getattr(parameter, "key", "") or "")
        if not key:
            continue
        is_secret = bool(getattr(parameter, "secret", False)) or str(getattr(parameter, "type", "")) == "secret"
        schema: dict[str, Any] = {
            "type": _PARAMETER_TYPES.get(str(getattr(parameter, "type", "text")), "string"),
            "title": str(getattr(parameter, "label", key)),
        }
        description = getattr(parameter, "description", None)
        if description:
            schema["description"] = str(description)[:400]
        validation = getattr(parameter, "validation", None) or {}
        options = validation.get("options") if isinstance(validation, dict) else None
        if isinstance(options, list) and options:
            schema["enum"] = [
                item.get("value") for item in options if isinstance(item, dict) and item.get("value") is not None
            ]
        if is_secret:
            schema["writeOnly"] = True
            schema["x-secret"] = True
        else:
            default = getattr(parameter, "default", None)
            if default is not None:
                schema["default"] = default
            examples = getattr(parameter, "examples", None) or []
            if examples:
                schema["examples"] = list(examples)[:3]
        properties[key] = schema
        if bool(getattr(parameter, "required", False)):
            required.append(key)
    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def _schema_from_outputs(outputs: list[Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for output in outputs:
        key = str(getattr(output, "key", "") or "")
        if not key:
            continue
        schema: dict[str, Any] = {
            "type": _PARAMETER_TYPES.get(str(getattr(output, "type", "text")), "string"),
            "title": str(getattr(output, "label", key)),
        }
        example = getattr(output, "example", None)
        if example is not None:
            schema["examples"] = [example]
        properties[key] = schema
    return {"type": "object", "properties": properties}


def _required_from_schema(schema: dict[str, Any]) -> list[str]:
    return [str(item) for item in (schema or {}).get("required") or []]


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if _SECRET_CONFIG_KEYS.search(str(key)) else _redact_mapping(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value[:20]]
    return value


def _examples_from_schema(schema: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    examples: dict[str, Any] = {}
    for key, spec in list(((schema or {}).get("properties") or {}).items())[:limit]:
        if not isinstance(spec, dict):
            continue
        if spec.get("x-secret") or spec.get("writeOnly"):
            continue
        example = spec.get("example")
        if example is None and spec.get("examples"):
            example = spec["examples"][0]
        if example is None and "default" in spec:
            example = spec["default"]
        if example is not None:
            examples[str(key)] = example
    return examples


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def _permission_hash(permissions: frozenset[str] | None) -> str:
    if permissions is None:
        return "admin"
    return canonical_hash(sorted(permissions))[:16]


async def _revision(organization_id: UUID, workspace_id: UUID | None) -> str:
    """Firma barata de las fuentes que cambian la disponibilidad/contratos."""
    sql = """
        SELECT 'installs' AS k,
               COUNT(*)::text || ':' || COALESCE(MAX(updated_at)::text, '') AS v
        FROM installed_integrations
        WHERE organization_id = :oid
          AND (workspace_id IS NOT DISTINCT FROM :ws OR workspace_id IS NULL)
        UNION ALL
        SELECT 'bindings',
               COUNT(*)::text || ':' || COALESCE(MAX(updated_at)::text, '')
        FROM workflow_capability_bindings
        WHERE organization_id = :oid AND (workspace_id IS NULL OR workspace_id = :ws)
        UNION ALL
        SELECT 'manifests', COUNT(*)::text || ':' || COALESCE(MAX(updated_at)::text, '')
        FROM integration_manifests
        UNION ALL
        SELECT 'actions', COUNT(*)::text || ':' || COALESCE(MAX(version)::text, '')
        FROM integration_actions
        UNION ALL
        SELECT 'agents', COUNT(*)::text || ':' || COALESCE(MAX(updated_at)::text, '')
        FROM agents WHERE organization_id = :oid
        UNION ALL
        SELECT 'kbs', COUNT(*)::text || ':' || COALESCE(MAX(updated_at)::text, '')
        FROM knowledge_bases WHERE organization_id = :oid
        UNION ALL
        SELECT 'connectors', COUNT(*)::text FROM connectors WHERE organization_id = :oid
        UNION ALL
        SELECT 'capabilities', COUNT(*)::text FROM integration_capabilities
    """
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(sql), {"oid": organization_id, "ws": workspace_id}
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — tabla opcional: revisión conservadora
        logger.warning("capability registry revision failed", error=str(exc)[:160])
        return f"fallback:{time.time()}"
    finally:
        await session.close()
    return canonical_hash({row.k: row.v for row in rows})[:24]


async def build_capability_snapshot(
    organization_id: UUID,
    workspace_id: UUID | None = None,
    *,
    permissions: frozenset[str] | None = None,
    force_refresh: bool = False,
) -> CapabilitySnapshot:
    """Snapshot canónico por tenant/workspace/permisos, cacheado y versionado."""
    started = time.monotonic()
    revision = await _revision(organization_id, workspace_id)
    key = f"{organization_id}:{workspace_id}:{_permission_hash(permissions)}:{revision}"
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and not force_refresh and cached[0] > now:
        _remember(cached[1])
        return cached[1]

    snapshot = await _build_snapshot(
        organization_id, workspace_id, permissions or frozenset(), revision=revision
    )
    _CACHE[key] = (now + _SNAPSHOT_TTL_SECONDS, snapshot)
    if len(_CACHE) > 128:
        oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])[:32]
        for stale_key, _ in oldest:
            _CACHE.pop(stale_key, None)
    _remember(snapshot)
    logger.info(
        "capability snapshot built",
        organization_id=str(organization_id),
        workspace_id=str(workspace_id) if workspace_id else None,
        snapshot_hash=snapshot.snapshot_hash,
        capabilities=len(snapshot.capabilities),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return snapshot


def _remember(snapshot: CapabilitySnapshot) -> None:
    now = time.monotonic()
    stale = [key for key, (expires, _) in _HISTORY.items() if expires <= now]
    for key in stale:
        _HISTORY.pop(key, None)
    index = {
        item.capability_ref: (
            item.contract_hash,
            item.availability.status,
            item.availability.executable,
        )
        for item in snapshot.capabilities
    }
    _HISTORY[snapshot.snapshot_hash] = (now + _HISTORY_TTL_SECONDS, index)
    if len(_HISTORY) > _HISTORY_MAX:
        oldest = sorted(_HISTORY.items(), key=lambda item: item[1][0])[:16]
        for key, _ in oldest:
            _HISTORY.pop(key, None)


def verify_snapshot(
    snapshot_hash: str | None,
    fresh: CapabilitySnapshot,
    relevant_refs: Iterable[str],
) -> dict[str, Any]:
    """¿El plan puede guardarse con el catálogo actual?

    Si el hash cambió pero ninguno de los refs que usa el plan cambió, se
    permite (un install de otro tenant/capacidad no bloquea). Si el snapshot
    es desconocido (reinicio) se pide re-interpretar: nunca publicar a ciegas.
    """
    if not snapshot_hash:
        return {"valid": True, "reason": "no_snapshot"}
    if snapshot_hash == fresh.snapshot_hash:
        return {"valid": True, "reason": "current"}

    refs = sorted({str(ref) for ref in relevant_refs if ref})
    old = _HISTORY.get(snapshot_hash)
    if old is None:
        return {
            "valid": False,
            "reason": "unknown_snapshot",
            "changed_refs": refs,
        }
    fresh_index = {
        item.capability_ref: (
            item.contract_hash,
            item.availability.status,
            item.availability.executable,
        )
        for item in fresh.capabilities
    }
    changed = [
        ref
        for ref in refs
        if old[1].get(ref) is not None and old[1].get(ref) != fresh_index.get(ref)
    ]
    return {
        "valid": not changed,
        "reason": "referenced_changes" if changed else "unrelated_changes",
        "changed_refs": changed,
    }


def _risk(value: Any) -> Literal["info", "normal", "elevated", "critical"]:
    text_ = str(value or "normal").lower()
    return text_ if text_ in ("info", "normal", "elevated", "critical") else "normal"  # type: ignore[return-value]


def _conversation_contract() -> dict[str, Any]:
    """Contrato real del executor `conversation.send` (conversation_capability.py)."""
    return {
        "input": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string"},
                "title": {"type": "string"},
                "channel": {"type": "string"},
                "conversation_id": {"type": "string"},
            },
        },
        "output": {
            "type": "object",
            "properties": {
                "sent": {"type": "boolean"},
                "channel": {"type": "string"},
                "conversation_id": {"type": "string"},
            },
        },
        "read_only": False,
    }


async def _build_snapshot(
    organization_id: UUID,
    workspace_id: UUID | None,
    permissions: frozenset[str],
    *,
    revision: str,
) -> CapabilitySnapshot:
    from src.platform.workflows.bindings import list_bindings

    resources, managed_db_ids, kb_rows, connector_rows = await _load_resources(
        organization_id, workspace_id
    )
    action_rows = await _load_marketplace_rows(organization_id, workspace_id)
    try:
        binding_rows = (await list_bindings(organization_id, workspace_id)).get("bindings", [])
    except Exception as exc:  # noqa: BLE001 — tabla de bindings opcional
        logger.warning("capability registry bindings failed", error=str(exc)[:160])
        binding_rows = []
    agent_rows = await _load_agents(organization_id, workspace_id)

    capabilities: list[CapabilityDescriptor] = []
    capabilities.extend(
        _marketplace_descriptors(action_rows, permissions)
    )
    capabilities.extend(
        _commerce_descriptors(
            binding_rows,
            action_rows,
            managed_db_ids,
            permissions,
            _conversation_contract(),
        )
    )
    capabilities.extend(_agent_descriptors(agent_rows, permissions))
    capabilities.extend(_tool_descriptors(permissions))
    capabilities.extend(
        _node_descriptors(
            capabilities,
            managed_databases=bool(managed_db_ids),
            knowledge_bases={str(row.id): str(row.name) for row in kb_rows},
            permissions=permissions,
        )
    )

    events = _event_descriptors()
    snapshot_payload = {
        "catalog_version": CATALOG_VERSION,
        "capabilities": [
            {
                "ref": item.capability_ref,
                "version": item.version,
                "contract_hash": item.contract_hash,
                "status": item.availability.status,
                "executable": item.availability.executable,
            }
            for item in sorted(capabilities, key=lambda item: item.capability_ref)
        ],
        "resources": [
            {"ref": item.resource_ref, "contract_hash": item.contract_hash}
            for item in sorted(resources, key=lambda item: item.resource_ref)
        ],
        "events": [
            {"event_type": item.event_type, "contract_hash": item.contract_hash}
            for item in sorted(events, key=lambda item: item.event_type)
        ],
        "revision": revision,
    }
    snapshot_hash = canonical_hash(snapshot_payload)
    coverage = _coverage(capabilities, resources, events)
    return CapabilitySnapshot(
        snapshot_hash=snapshot_hash,
        generated_at=datetime.now(timezone.utc),
        capabilities=sorted(capabilities, key=lambda item: item.capability_ref),
        resources=sorted(resources, key=lambda item: item.resource_ref),
        events=sorted(events, key=lambda item: item.event_type),
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Colecciones
# ---------------------------------------------------------------------------
async def _load_marketplace_rows(
    organization_id: UUID, workspace_id: UUID | None
) -> list[Any]:
    sql = """
        SELECT
            a.action_id, a.version AS action_version, a.display_name, a.description,
            a.input_schema, a.output_schema, a.risk_level, a.read_only,
            a.requires_approval, a.contains_personal_data, a.timeout_ms,
            a.retry_policy, a.idempotency_support, a.cost_model, a.provider_config,
            a.status AS action_status, a.capability_slug, a.provider AS action_provider,
            a.version AS action_contract_version,
            m.slug AS integration_slug, m.name AS integration_name,
            m.version AS manifest_version, m.status AS manifest_status,
            m.auth_modes, m.data_policy, m.events, m.contract_version,
            m.pricing, m.rate_limits, m.applies_to,
            c.name AS capability_name, c.description AS capability_description,
            i.id AS install_id, i.status AS install_status, i.enabled_actions,
            i.purpose, i.credential_ref, i.version AS install_version,
            COALESCE(creds.configured, 0) AS credentials_configured
        FROM integration_actions a
        JOIN integration_manifests m ON m.id = a.integration_id
        LEFT JOIN integration_capabilities c
            ON c.integration_id = m.id AND c.slug = a.capability_slug
        LEFT JOIN LATERAL (
            SELECT i.id, i.status, i.enabled_actions, i.purpose, i.credential_ref, i.version
            FROM installed_integrations i
            WHERE i.organization_id = :oid
              AND (i.workspace_id IS NOT DISTINCT FROM :ws OR i.workspace_id IS NULL)
              AND i.integration_id = m.id
              AND i.status IN ('installed', 'connected', 'active')
            ORDER BY i.created_at DESC
            LIMIT 1
        ) i ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS configured
            FROM integration_credentials cr
            WHERE cr.install_id = i.id AND cr.status = 'configured'
        ) creds ON TRUE
        WHERE (m.organization_id IS NULL OR m.organization_id = :oid)
          AND m.status IN ('PUBLISHED', 'DEPRECATED')
          AND a.status <> 'END_OF_LIFE'
          AND COALESCE(m.pricing->>'_pack_kind', '') = ''
        ORDER BY a.action_id
    """
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(sql), {"oid": organization_id, "ws": workspace_id}
            )
        ).fetchall()
    finally:
        await session.close()


async def _load_agents(
    organization_id: UUID, workspace_id: UUID | None
) -> list[Any]:
    sql = """
        SELECT id, name, description, tools, config_json, is_active, status, workspace_id
        FROM agents
        WHERE organization_id = :oid
          AND (workspace_id IS NULL OR workspace_id = :ws)
        ORDER BY name
        LIMIT 200
    """
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(sql), {"oid": organization_id, "ws": workspace_id}
            )
        ).fetchall()
    finally:
        await session.close()


async def _load_resources(
    organization_id: UUID, workspace_id: UUID | None
) -> tuple[list[ResourceDescriptor], set[str], list[Any], list[Any]]:
    session = await get_async_session()
    try:
        kb_rows = (
            await session.execute(
                text(
                    "SELECT id, name, description, status, metadata_schema, embedding_model, "
                    "workspace_id FROM knowledge_bases "
                    "WHERE organization_id = :oid AND (workspace_id IS NULL OR workspace_id = :ws) "
                    "ORDER BY name LIMIT 200"
                ),
                {"oid": organization_id, "ws": workspace_id},
            )
        ).fetchall()
        db_rows = (
            await session.execute(
                text(
                    "SELECT id, provider, db_name, status, workspace_id, size_quota_mb "
                    "FROM managed_databases WHERE organization_id = :oid "
                    "AND (workspace_id = :ws OR :ws IS NULL) ORDER BY db_name"
                ),
                {"oid": organization_id, "ws": workspace_id},
            )
        ).fetchall()
        try:
            connector_rows = (
                await session.execute(
                    text(
                        "SELECT id, name, type, status, workspace_id FROM connectors "
                        "WHERE organization_id = :oid "
                        "AND (workspace_id IS NULL OR workspace_id = :ws) ORDER BY name LIMIT 200"
                    ),
                    {"oid": organization_id, "ws": workspace_id},
                )
            ).fetchall()
        except Exception:  # noqa: BLE001 — base sin tabla connectors
            connector_rows = []
    finally:
        await session.close()

    resources: list[ResourceDescriptor] = []
    managed_db_ids: set[str] = set()
    for row in db_rows:
        managed_db_ids.add(str(row.id))
        resources.append(
            ResourceDescriptor(
                resource_ref=f"resource.managed_db.{row.id}",
                kind="managed_db",
                display_name=str(row.db_name),
                description=f"Base de datos gestionada ({row.provider}).",
                status=str(row.status),
                data_schema={},
                schema_source="unknown",
                metadata={
                    "provider": row.provider,
                    "status": row.status,
                    "size_quota_mb": int(row.size_quota_mb or 0),
                },
                contract_hash=canonical_hash(
                    {"id": str(row.id), "db_name": row.db_name, "provider": row.provider}
                ),
            )
        )
    for row in kb_rows:
        schema = row.metadata_schema if isinstance(row.metadata_schema, dict) else {}
        resources.append(
            ResourceDescriptor(
                resource_ref=f"resource.knowledge_base.{row.id}",
                kind="knowledge_base",
                display_name=str(row.name),
                description=str(row.description or "Base de conocimiento del tenant."),
                status=str(row.status),
                data_schema=schema,
                schema_source="metadata_schema" if schema else "unknown",
                metadata={"embedding_model": row.embedding_model},
                contract_hash=canonical_hash(
                    {"id": str(row.id), "name": row.name, "schema": schema}
                ),
            )
        )
    for row in connector_rows:
        resources.append(
            ResourceDescriptor(
                resource_ref=f"resource.connector.{row.id}",
                kind=f"connector.{row.type}",
                display_name=str(row.name),
                description=f"Conector {row.type}.",
                status=str(row.status or "unknown"),
                data_schema={},
                schema_source="unknown",
                metadata={"connector_type": row.type},
                contract_hash=canonical_hash(
                    {"id": str(row.id), "name": row.name, "type": row.type}
                ),
            )
        )
    return resources, managed_db_ids, list(kb_rows), list(connector_rows)


# ---------------------------------------------------------------------------
# Descriptores: Marketplace
# ---------------------------------------------------------------------------
def _marketplace_descriptors(
    rows: list[Any],
    permissions: frozenset[str],
) -> list[CapabilityDescriptor]:
    by_capability: dict[str, list[str]] = {}
    for row in rows:
        by_capability.setdefault(str(row.capability_slug or ""), []).append(
            str(row.action_id)
        )

    descriptors: list[CapabilityDescriptor] = []
    for row in rows:
        action_id = str(row.action_id)
        auth_modes = [str(item).upper() for item in (row.auth_modes or [])]
        requires_credentials = bool(auth_modes) and set(auth_modes) != {"NONE"}
        data_policy = row.data_policy if isinstance(row.data_policy, dict) else {}
        purpose_required = bool(data_policy.get("purpose_required"))
        installed = row.install_id is not None
        enabled_actions = [str(item) for item in (row.enabled_actions or [])]
        enabled = not enabled_actions or action_id in enabled_actions
        credentials_ok = (
            not requires_credentials
            or bool(row.credential_ref)
            or int(row.credentials_configured or 0) > 0
        )
        purpose_ok = not purpose_required or bool(row.purpose)
        permitted = _permitted("external_actions:execute", permissions)
        published = str(row.manifest_status) in ("PUBLISHED", "DEPRECATED")
        exists = True
        deprecated = str(row.manifest_status) == "DEPRECATED" or str(row.action_status) == "DEPRECATED"

        reasons: list[str] = []
        status: AvailabilityStatus
        if not exists:
            status = "UNAVAILABLE"
            reasons.append("la acción no existe")
        elif not published:
            status = "UNAVAILABLE"
            reasons.append("la integración no está publicada")
        elif not installed:
            status = "NEEDS_INSTALLATION"
            reasons.append(f"instala la integración {row.integration_slug}")
        elif str(row.install_status) in ("paused", "suspended"):
            status = "DISABLED"
            reasons.append("la instalación está pausada o suspendida")
        elif not enabled:
            status = "DISABLED"
            reasons.append("la acción no está habilitada en la instalación")
        elif not credentials_ok:
            status = "NEEDS_CREDENTIALS"
            reasons.append("faltan credenciales del proveedor")
        elif not purpose_ok:
            status = "NEEDS_CONFIGURATION"
            reasons.append("falta declarar la finalidad (datos personales)")
        elif not permitted:
            status = "PERMISSION_DENIED"
            reasons.append("permiso insuficiente: external_actions:execute")
        elif deprecated:
            status = "DEPRECATED"
            reasons.append("el proveedor está deprecado")
        else:
            status = "AVAILABLE"

        executable = (
            exists
            and published
            and installed
            and enabled
            and credentials_ok
            and purpose_ok
            and permitted
            and str(row.install_status) not in ("paused", "suspended")
        )
        error_items = _error_list(_MARKETPLACE_ERRORS)
        if bool(row.requires_approval):
            error_items.append(
                CapabilityError(
                    code="APPROVAL_REQUIRED",
                    message="La acción requiere aprobación humana antes de ejecutarse.",
                    retriable=False,
                )
            )
        input_schema = row.input_schema if isinstance(row.input_schema, dict) else {}
        output_schema = row.output_schema if isinstance(row.output_schema, dict) else {}
        gaps: list[str] = []
        if not (input_schema.get("properties") or input_schema.get("required")):
            gaps.append("input_schema")
        if not (output_schema.get("properties") or output_schema.get("$ref")):
            gaps.append("output_schema")
        if not str(row.description or "").strip():
            gaps.append("description")
        manifest_events = [
            str(event.get("id"))
            for event in (row.events or [])
            if isinstance(event, dict) and event.get("id")
        ]
        side_effects: list[SideEffect] = ["external"]
        side_effects.append("read" if bool(row.read_only) else "write")
        if bool(row.contains_personal_data):
            side_effects.append("write")
        descriptor_payload = {
            "capability_ref": action_id,
            "version": int(row.action_version or 1),
            "display_name": str(row.display_name or _humanize(action_id)),
            "description": str(row.description or ""),
            "owner_module": "src.platform.marketplace",
            "category": "marketplace",
            "tags": sorted(
                {
                    "marketplace",
                    str(row.capability_slug or ""),
                    str(row.integration_slug or ""),
                    "personal_data" if row.contains_personal_data else "",
                }
                - {""}
            ),
            "aliases": _aliases(
                action_id,
                row.display_name or "",
                row.description or "",
                str(row.capability_slug or ""),
                str(row.capability_name or ""),
                str(row.integration_name or ""),
            ),
            "use_cases": [str(row.description)] if row.description else [],
            "when_to_use": [str(row.description)] if row.description else [],
            "when_not_to_use": [],
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_inputs": _required_from_schema(input_schema),
            "errors": error_items,
            "side_effects": sorted(set(side_effects)),
            "risk_level": _risk(row.risk_level),
            "required_permissions": ["external_actions:execute"],
            "idempotency_policy": {
                "supported": bool(row.idempotency_support),
                "scope": "action",
            },
            "timeout_policy": {
                "timeout_ms": int(row.timeout_ms or 5000),
                "source": "marketplace_action",
                "retry": row.retry_policy or {},
            },
            "available_events": manifest_events,
            "dependency_refs": [
                f"integration:{row.integration_slug}",
                f"capability:{row.capability_slug}",
                *(["approval:human"] if row.requires_approval else []),
                *(["purpose:required"] if purpose_required else []),
            ],
            "provider_kind": "marketplace_action",
            "availability": CapabilityAvailability(
                status=status,
                exists=exists,
                published=published,
                installed=installed,
                enabled=enabled,
                configured=credentials_ok and purpose_ok,
                permitted=permitted,
                executable=executable,
                reasons=reasons,
            ),
            "health_status": None,
            "supports_simulation": True,
            "example_inputs": _examples_from_schema(input_schema),
            "example_outputs": _examples_from_schema(output_schema),
            "contract_gaps": gaps,
            "metadata_source": "marketplace_db",
            "source": "marketplace",
            "planner_usage": {
                "node_type": "marketplace_action",
                "step_type": "integration_action",
                "config": {"action_id": action_id},
            },
            "metadata": {
                "integration_slug": row.integration_slug,
                "integration_name": row.integration_name,
                "capability_slug": row.capability_slug,
                "capability_name": row.capability_name,
                "install_id": str(row.install_id) if row.install_id else None,
                "requires_credentials": requires_credentials,
                "requires_approval": bool(row.requires_approval),
                "cost": row.cost_model or {},
                "read_only": bool(row.read_only),
                "contains_personal_data": bool(row.contains_personal_data),
                "provider_alternatives": [
                    ref for ref in by_capability.get(str(row.capability_slug or ""), [])
                    if ref != action_id
                ],
            },
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))
    return descriptors


# ---------------------------------------------------------------------------
# Descriptores: Commerce + bindings
# ---------------------------------------------------------------------------
def _binding_availability(
    binding: dict[str, Any] | None,
    *,
    provider_kind: str,
    managed_db: bool,
    action_rows_by_id: dict[str, Any],
    permissions: frozenset[str],
) -> CapabilityAvailability:
    permitted = _permitted("external_actions:execute", permissions)
    if binding is None:
        return CapabilityAvailability(
            status="NEEDS_CONFIGURATION",
            exists=True,
            published=True,
            installed=False,
            configured=False,
            permitted=permitted,
            executable=False,
            reasons=["sin binding para este tenant"],
        )
    configured = True
    reasons: list[str] = []
    if provider_kind in ("managed_db", "connected_db") and not managed_db:
        configured = False
        reasons.append("no hay base de datos gestionada para el tenant")
    if provider_kind == "marketplace_action":
        config = binding.get("config") or {}
        install_id = str(config.get("install_id") or "")
        action_id = str(config.get("action_id") or "")
        action = action_rows_by_id.get(install_id) or action_rows_by_id.get(action_id)
        if action is None:
            configured = False
            reasons.append("la acción del binding no está instalada")
        elif not action["executable"]:
            configured = False
            reasons.append("la acción del binding no está disponible")
    if provider_kind == "rest_api" and not str((binding.get("config") or {}).get("url") or ""):
        configured = False
        reasons.append("rest_api requiere config.url")
    if not permitted:
        reasons.append("permiso insuficiente: external_actions:execute")
    if not configured:
        status: AvailabilityStatus = "NEEDS_CONFIGURATION"
    elif not permitted:
        status = "PERMISSION_DENIED"
    else:
        status = "AVAILABLE"
    return CapabilityAvailability(
        status=status,
        exists=True,
        published=True,
        installed=True,
        enabled=True,
        configured=configured,
        permitted=permitted,
        executable=configured and permitted,
        reasons=reasons,
    )


def _commerce_descriptors(
    binding_rows: list[dict[str, Any]],
    action_rows: list[Any],
    managed_db_ids: set[str],
    permissions: frozenset[str],
    conversation: dict[str, Any],
) -> list[CapabilityDescriptor]:
    from src.platform.commerce import contracts as C

    bindings = {str(item.get("capability_ref")): item for item in binding_rows}
    action_rows_by_id: dict[str, Any] = {}
    for row in action_rows:
        action_rows_by_id[str(row.action_id)] = {
            "executable": bool(row.install_id)
            and str(row.install_status) not in ("paused", "suspended")
            and (
                not [str(x) for x in (row.enabled_actions or [])]
                or str(row.action_id) in [str(x) for x in (row.enabled_actions or [])]
            ),
        }
        if row.install_id:
            action_rows_by_id[str(row.install_id)] = action_rows_by_id[str(row.action_id)]

    descriptors: list[CapabilityDescriptor] = []
    contracts = dict(C.CAPABILITY_CONTRACTS)
    contracts["conversation.send"] = conversation
    for ref, contract in contracts.items():
        binding = bindings.get(ref)
        provider_kind = str((binding or {}).get("provider_kind") or "unbound")
        availability = _binding_availability(
            binding,
            provider_kind=provider_kind,
            managed_db=bool(managed_db_ids),
            action_rows_by_id=action_rows_by_id,
            permissions=permissions,
        )
        input_schema = contract.get("input") or {}
        output_schema = contract.get("output") or {}
        required_inputs = _required_from_schema(input_schema)
        financial = bool(contract.get("financial"))
        read_only = bool(contract.get("read_only"))
        display_name, description = _BUSINESS_TEXT.get(
            ref, (_humanize(ref), f"Capacidad de negocio {ref}.")
        )
        side_effects: list[SideEffect] = ["external"]
        if financial:
            side_effects.append("financial")
        side_effects.append("read" if read_only else "write")
        risk = "critical" if financial else ("elevated" if not read_only else "info")
        events: list[str] = []
        if ref.startswith("payments."):
            events = list(C.PAYMENT_EVENTS)
        gaps: list[str] = []
        if not (input_schema.get("properties") or required_inputs):
            gaps.append("input_schema")
        if not (output_schema.get("properties") or output_schema.get("$ref")):
            gaps.append("output_schema")
        descriptor_payload = {
            "capability_ref": ref,
            "version": int((binding or {}).get("contract_version") or 1),
            "display_name": display_name,
            "description": description,
            "owner_module": (
                "src.platform.commerce"
                if ref != "conversation.send"
                else "src.platform.workflows.conversation_capability"
            ),
            "category": "payments" if ref.startswith("payments.") else (
                "communication" if ref.startswith("conversation.") else "commerce"
            ),
            "tags": sorted(
                {
                    "commerce",
                    ref.split(".")[0],
                    "financial" if financial else "",
                    "binding" if binding else "unbound",
                }
                - {""}
            ),
            "aliases": _aliases(ref, display_name, description),
            "use_cases": [description],
            "when_to_use": [description],
            "when_not_to_use": [],
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_inputs": required_inputs,
            "errors": _error_list(_BINDING_ERRORS),
            "side_effects": sorted(set(side_effects)),
            "risk_level": risk,
            "required_permissions": ["external_actions:execute"],
            "idempotency_policy": {
                "required": contract.get("idempotency") == "required",
                "scope": "business_operation" if financial else "binding",
            },
            "timeout_policy": {"timeout_ms": 60_000, "source": "runtime_default"},
            "available_events": events,
            "dependency_refs": [
                f"binding:{ref}",
                f"provider:{provider_kind}",
            ],
            "provider_kind": provider_kind,
            "availability": availability,
            "health_status": None,
            "supports_simulation": True,
            "example_inputs": _examples_from_schema(input_schema),
            "example_outputs": _examples_from_schema(output_schema),
            "contract_gaps": gaps,
            "metadata_source": (
                "binding" if ref not in C.CAPABILITY_CONTRACTS else "commerce_contract"
            ),
            "source": "commerce" if ref in C.CAPABILITY_CONTRACTS else "binding",
            "planner_usage": {
                "node_type": "capability_call",
                "step_type": "capability_call",
                "config": {"capability": ref},
            },
            "metadata": {
                "binding_id": (binding or {}).get("id"),
                "provider_kind": provider_kind,
                "contract_version": int((binding or {}).get("contract_version") or 1),
            },
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))

    # Bindings personalizados que no están en los contratos base (no se pierden).
    known = {item.capability_ref for item in descriptors}
    for ref, binding in bindings.items():
        if ref in known:
            continue
        provider_kind = str(binding.get("provider_kind") or "custom")
        input_schema = binding.get("contract_input_schema") or {}
        output_schema = binding.get("contract_output_schema") or {}
        availability = _binding_availability(
            binding,
            provider_kind=provider_kind,
            managed_db=bool(managed_db_ids),
            action_rows_by_id=action_rows_by_id,
            permissions=permissions,
        )
        descriptor_payload = {
            "capability_ref": ref,
            "version": 1,
            "display_name": _humanize(ref),
            "description": f"Capacidad personalizada con binding {provider_kind}.",
            "owner_module": "tenant_binding",
            "category": "custom",
            "tags": ["custom", provider_kind],
            "aliases": _aliases(ref, provider_kind),
            "use_cases": [],
            "when_to_use": [],
            "when_not_to_use": [],
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_inputs": _required_from_schema(input_schema),
            "errors": _error_list(_BINDING_ERRORS),
            "side_effects": ["read"],
            "risk_level": "normal",
            "required_permissions": ["external_actions:execute"],
            "idempotency_policy": {"scope": "binding"},
            "timeout_policy": {"timeout_ms": 60_000, "source": "runtime_default"},
            "available_events": [],
            "dependency_refs": [f"binding:{ref}", f"provider:{provider_kind}"],
            "provider_kind": provider_kind,
            "availability": availability,
            "health_status": None,
            "supports_simulation": True,
            "example_inputs": _examples_from_schema(input_schema),
            "example_outputs": _examples_from_schema(output_schema),
            "contract_gaps": [
                field
                for field, present in (
                    ("input_schema", bool(input_schema.get("properties"))),
                    ("output_schema", bool(output_schema.get("properties"))),
                    ("description", False),
                )
                if not present
            ],
            "metadata_source": "binding",
            "source": "binding",
            "planner_usage": {
                "node_type": "capability_call",
                "step_type": "capability_call",
                "config": {"capability": ref},
            },
            "metadata": {"binding_id": binding.get("id"), "provider_kind": provider_kind},
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))
    return descriptors


# ---------------------------------------------------------------------------
# Descriptores: agentes, tools, nodos
# ---------------------------------------------------------------------------
def _agent_descriptors(
    rows: list[Any], permissions: frozenset[str]
) -> list[CapabilityDescriptor]:
    permitted = _permitted("agents:execute", permissions)
    descriptors: list[CapabilityDescriptor] = []
    for row in rows:
        config = row.config_json if isinstance(row.config_json, dict) else {}
        purpose = str(config.get("purpose") or row.description or "").strip()
        active = bool(row.is_active) or str(row.status) in ("configured", "ready", "deployed")
        tools = [str(item) for item in (row.tools or [])][:30]
        kb_ids = [str(item) for item in (config.get("knowledge_base_ids") or [])][:20]
        output_schema = config.get("output_schema")
        if not isinstance(output_schema, dict):
            output_schema = {
                "type": "object",
                "properties": {"text": {"type": "string", "title": "Respuesta del agente"}},
            }
        reasons: list[str] = []
        if not active:
            reasons.append("el agente está inactivo")
        if not permitted:
            reasons.append("permiso insuficiente: agents:execute")
        status: AvailabilityStatus
        if not active:
            status = "DISABLED"
        elif not permitted:
            status = "PERMISSION_DENIED"
        else:
            status = "AVAILABLE"
        ref = f"agent.{row.id}"
        input_schema = {
            "type": "object",
            "required": ["prompt"],
            "properties": {"prompt": {"type": "string", "title": "Pregunta o instrucción"}},
        }
        descriptor_payload = {
            "capability_ref": ref,
            "version": 1,
            "display_name": str(row.name or _humanize(ref)),
            "description": purpose or "Agente de Zent.",
            "owner_module": "src.agents",
            "category": "ai",
            "tags": sorted({"agent", "llm", *tools}),
            "aliases": _aliases(ref, row.name or "", purpose, " ".join(tools)),
            "use_cases": [purpose] if purpose else [],
            "when_to_use": [purpose] if purpose else [],
            "when_not_to_use": ["una regla determinística alcanza"] if purpose else [],
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_inputs": ["prompt"],
            "errors": _error_list(_AGENT_ERRORS),
            "side_effects": ["read"],
            "risk_level": "normal",
            "required_permissions": ["agents:execute"],
            "idempotency_policy": {"scope": "run_node", "supported": True},
            "timeout_policy": {"timeout_ms": 60_000, "source": "runtime_default"},
            "available_events": [],
            "dependency_refs": [
                *[f"tool:{tool}" for tool in tools],
                *[f"resource:knowledge_base:{kb_id}" for kb_id in kb_ids],
            ],
            "provider_kind": "agent_runtime",
            "availability": CapabilityAvailability(
                status=status,
                exists=True,
                published=True,
                installed=True,
                enabled=active,
                configured=active,
                permitted=permitted,
                executable=active and permitted,
                reasons=reasons,
            ),
            "health_status": None,
            "supports_simulation": False,
            "example_inputs": {"prompt": "Analiza el caso y devuelve una recomendación."},
            "example_outputs": {},
            "contract_gaps": [],
            "metadata_source": "agent_db",
            "source": "agent",
            "planner_usage": {
                "node_type": "llm",
                "step_type": "agent_analysis",
                "config": {"agent_id": str(row.id)},
            },
            "metadata": {
                "agent_id": str(row.id),
                "agent_name": str(row.name or ""),
                "purpose": purpose,
                "tools": tools,
                "knowledge_base_ids": kb_ids,
                "status": str(row.status),
                "budget": config.get("budget")
                or config.get("monthly_budget")
                or config.get("limits"),
                "version": config.get("version") or 1,
                "input_schema": input_schema,
            },
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))
    return descriptors


def _tool_descriptors(permissions: frozenset[str]) -> list[CapabilityDescriptor]:
    try:
        from src.agents.tools.registry import list_tools

        tools = list_tools()
    except Exception as exc:  # noqa: BLE001 — tools opcionales
        logger.warning("capability registry tools unavailable", error=str(exc)[:160])
        return []
    descriptors: list[CapabilityDescriptor] = []
    for name, tool in sorted(tools.items()):
        permission = str(getattr(tool, "permission", "") or "")
        permitted = _permitted(permission, permissions)
        input_schema = getattr(tool, "input_schema", {}) or {}
        timeout = float(getattr(tool, "timeout_seconds", 10.0) or 10.0)
        side_effects: list[SideEffect] = ["read"]
        if name in ("call_api", "marketplace_action"):
            side_effects = ["external"]
        elif name.startswith(("query_", "search_")):
            side_effects = ["read"]
        ref = f"tool.{name}"
        descriptor_payload = {
            "capability_ref": ref,
            "version": 1,
            "display_name": _humanize(name),
            "description": str(getattr(tool, "description", "") or ""),
            "owner_module": "src.agents.tools",
            "category": "agent_tool",
            "tags": ["tool", "agent_tool"],
            "aliases": _aliases(ref, name, getattr(tool, "description", "") or ""),
            "use_cases": [str(getattr(tool, "description", ""))] if getattr(tool, "description", "") else [],
            "when_to_use": [],
            "when_not_to_use": [],
            "input_schema": input_schema,
            "output_schema": {},
            "required_inputs": _required_from_schema(input_schema),
            "errors": _error_list(_TOOL_ERRORS),
            "side_effects": side_effects,
            "risk_level": "elevated" if "external" in side_effects else "info",
            "required_permissions": [permission] if permission else [],
            "idempotency_policy": {"scope": "tool_call"},
            "timeout_policy": {"timeout_ms": int(timeout * 1000), "source": "tool_registry"},
            "available_events": [],
            "dependency_refs": [],
            "provider_kind": "agent_tool",
            "availability": CapabilityAvailability(
                status="AVAILABLE" if permitted else "PERMISSION_DENIED",
                exists=True,
                published=True,
                installed=True,
                enabled=True,
                configured=True,
                permitted=permitted,
                executable=permitted,
                reasons=[] if permitted else [f"permiso insuficiente: {permission}"],
            ),
            "health_status": None,
            "supports_simulation": False,
            "example_inputs": _examples_from_schema(input_schema),
            "example_outputs": {},
            "contract_gaps": [] if input_schema.get("properties") else ["input_schema"],
            "metadata_source": "tool_registry",
            "source": "tool",
            "planner_usage": {"agent_tool": True},
            "metadata": {"tool_name": name, "permission": permission},
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))
    return descriptors


def _node_descriptors(
    existing: list[CapabilityDescriptor],
    *,
    managed_databases: bool,
    knowledge_bases: dict[str, str],
    permissions: frozenset[str],
) -> list[CapabilityDescriptor]:
    from src.platform.workflows.node_catalog import catalog_availability, metadata_for
    from src.platform.workflows.nodes import capability_permission, registry
    from src.platform.workflows.parameters import node_business_schema

    agents = {
        str(item.metadata.get("agent_id")): item.display_name
        for item in existing
        if item.source == "agent"
    }
    actions = {
        item.capability_ref: {"action_id": item.capability_ref}
        for item in existing
        if item.source == "marketplace" and item.availability.installed
    }
    caps_like = {
        "agents": agents,
        "knowledge_bases": dict(knowledge_bases),
        "actions": actions,
        "managed_db": managed_databases,
    }

    descriptors: list[CapabilityDescriptor] = []
    for node_def in registry.all():
        meta = metadata_for(node_def.node_type)
        schema = node_business_schema(node_def.node_type)
        if schema is not None:
            input_schema = _schema_from_parameters(schema.parameters)
            output_schema = _schema_from_outputs(schema.outputs)
        else:
            input_schema = {"type": "object", "properties": {}}
            output_schema = {"type": "object", "properties": {}}
        available, reason = catalog_availability(
            node_def, caps_like, permissions=permissions
        )
        if available:
            status: AvailabilityStatus = "AVAILABLE"
        elif reason and "Permiso" in reason:
            status = "PERMISSION_DENIED"
        else:
            status = "NEEDS_CONFIGURATION"
        required_permissions = sorted(
            {
                permission
                for permission in (
                    capability_permission(capability)
                    for capability in node_def.capabilities
                )
                if permission
            }
        )
        side_effects: set[SideEffect] = set()
        for capability in node_def.capabilities:
            side_effects.update(_NODE_SIDE_EFFECTS.get(capability, ()))
        gaps: list[str] = []
        if node_def.node_type not in ("trigger_event", "trigger_schedule", "trigger_webhook", "end"):
            if not input_schema.get("properties"):
                gaps.append("input_schema")
            if not output_schema.get("properties"):
                gaps.append("output_schema")
        examples = meta.get("examples") or ()
        example_inputs: dict[str, Any] = {}
        if examples and isinstance(examples[0], dict):
            config = examples[0].get("config")
            if isinstance(config, dict):
                example_inputs = {
                    key: value
                    for key, value in config.items()
                    if not _SECRET_CONFIG_KEYS.search(str(key))
                }
        if schema is None:
            gaps.append("business_schema")
        ref = f"node.{node_def.node_type}"
        descriptor_payload = {
            "capability_ref": ref,
            "version": int(node_def.version or 1),
            "display_name": str(node_def.business_name or node_def.label),
            "description": str(node_def.short_description or node_def.label),
            "owner_module": "src.platform.workflows.nodes",
            "category": str(node_def.category),
            "tags": sorted(
                {
                    "workflow_node",
                    node_def.node_type,
                    str(node_def.category),
                    str(node_def.risk_level),
                }
            ),
            "aliases": _aliases(
                ref,
                node_def.label,
                node_def.business_name or "",
                node_def.short_description or "",
                " ".join(meta.get("when_to_use") or ()),
            ),
            "use_cases": list(meta.get("when_to_use") or ()),
            "when_to_use": list(meta.get("when_to_use") or ()),
            "when_not_to_use": list(meta.get("when_not_to_use") or ()),
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_inputs": _required_from_schema(input_schema),
            "errors": _error_list(_NODE_ERRORS),
            "side_effects": sorted(side_effects) or ["read"],
            "risk_level": _risk(node_def.risk_level),
            "required_permissions": required_permissions,
            "idempotency_policy": {"scope": "run_node", "supported": True},
            "timeout_policy": {"timeout_ms": 60_000, "source": "runtime_default"},
            "available_events": [],
            "dependency_refs": [f"requires:{item}" for item in (node_def.requires or ())],
            "provider_kind": "internal",
            "availability": CapabilityAvailability(
                status=status,
                exists=True,
                published=True,
                installed=True,
                enabled=available,
                configured=available,
                permitted=not (reason and "Permiso" in reason),
                executable=available,
                reasons=[reason] if reason else [],
            ),
            "health_status": None,
            "supports_simulation": bool(node_def.simulation_supported),
            "example_inputs": example_inputs,
            "example_outputs": _examples_from_schema(output_schema),
            "contract_gaps": sorted(set(gaps)),
            "metadata_source": "node_registry",
            "source": "node",
            "planner_usage": {
                "node_type": node_def.node_type,
                "step_type": _NODE_TO_STEP.get(node_def.node_type),
                "supported": _NODE_TO_STEP.get(node_def.node_type) is not None,
                "config": example_inputs,
            },
            "metadata": {
                "node_type": node_def.node_type,
                "category": node_def.category,
                "requires": list(node_def.requires or ()),
                "capabilities": sorted(node_def.capabilities),
            },
        }
        descriptor_payload["contract_hash"] = _contract_hash(descriptor_payload)
        descriptors.append(CapabilityDescriptor(**descriptor_payload))
    return descriptors


def _event_descriptors() -> list[EventDescriptor]:
    from src.platform.workflows.event_registry import list_catalog

    descriptors: list[EventDescriptor] = []
    for event in list_catalog():
        fields = [
            {
                "key": field.key,
                "label": field.label,
                "type": field.type,
                "description": field.description,
                "example": field.example,
            }
            for field in event.fields
        ]
        schema = {
            "type": "object",
            "properties": {
                field["key"]: {
                    "type": _PARAMETER_TYPES.get(str(field["type"]), "string"),
                    "title": field["label"],
                }
                for field in fields
            },
        }
        payload = {
            "event_type": event.id,
            "version": event.version,
            "business_name": event.business_name,
            "description": event.description or "",
            "category": event.category,
            "fields": fields,
            "input_schema": schema,
        }
        descriptors.append(
            EventDescriptor(
                **payload,
                contract_hash=canonical_hash(payload),
                available=True,
            )
        )
    return descriptors


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------
def _coverage(
    capabilities: list[CapabilityDescriptor],
    resources: list[ResourceDescriptor],
    events: list[EventDescriptor],
) -> dict[str, Any]:
    business_sources = {"marketplace", "commerce", "binding"}
    business = [item for item in capabilities if item.source in business_sources]
    complete = [item for item in business if not item.contract_gaps]
    by_source = Counter(item.source for item in capabilities)
    by_status = Counter(item.availability.status for item in capabilities)
    by_category = Counter(item.category for item in capabilities)
    gaps = [
        {"capability_ref": item.capability_ref, "missing": item.contract_gaps}
        for item in business
        if item.contract_gaps
    ]
    return {
        "schema": COVERAGE_SCHEMA,
        "total_capabilities": len(capabilities),
        "business_capabilities": len(business),
        "business_complete": len(complete),
        "business_completeness": round(len(complete) / max(len(business), 1), 4),
        "by_source": dict(sorted(by_source.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_category": dict(sorted(by_category.items())),
        "resources": len(resources),
        "events": len(events),
        "contract_gaps": gaps[:60],
    }


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def _score_descriptor(
    descriptor: CapabilityDescriptor, query: str, q_tokens: set[str]
) -> float:
    ref = descriptor.capability_ref.lower()
    query_norm = normalize_text(query)
    display = normalize_text(descriptor.display_name)
    searchable = normalize_text(
        " ".join(
            [
                descriptor.capability_ref,
                descriptor.display_name,
                descriptor.description,
                " ".join(descriptor.tags),
                " ".join(descriptor.aliases),
                " ".join(descriptor.use_cases),
            ]
        )
    )
    score = 0.0
    if query_norm and ref == query_norm:
        score += 1000
    elif query_norm and (ref.startswith(query_norm) or query_norm in ref):
        score += 400
    if query_norm and query_norm in display:
        score += 220
    if query_norm and query_norm in searchable:
        score += 40
    ref_tokens = token_set(descriptor.capability_ref)
    display_tokens = token_set(descriptor.display_name)
    alias_tokens = set(descriptor.aliases)
    desc_tokens = token_set(
        " ".join(
            [
                descriptor.description,
                " ".join(descriptor.tags),
                " ".join(descriptor.use_cases),
            ]
        )
    )
    score += 9.0 * len(q_tokens & ref_tokens)
    score += 6.0 * len(q_tokens & display_tokens)
    score += 3.0 * len(q_tokens & alias_tokens)
    score += 2.0 * len(q_tokens & desc_tokens)
    if query_norm and query_norm in " ".join(descriptor.aliases):
        score += 120
    if descriptor.availability.executable:
        score += 6
    if descriptor.source in ("commerce", "marketplace", "binding") and score > 0:
        score += 8
    if descriptor.source == "node":
        score -= 6  # las capacidades de negocio ganan ante empate
    return score


def search_descriptors(
    descriptors: list[CapabilityDescriptor],
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    category: str | None = None,
    source: str | None = None,
    status: str | None = None,
    executable: bool | None = None,
    risk_level: str | None = None,
    side_effect: str | None = None,
    provider_kind: str | None = None,
) -> tuple[list[tuple[CapabilityDescriptor, float]], int]:
    """Búsqueda determinista: exacta → alias → texto. Sin LLM por capacidad."""
    q_tokens = token_set(query)
    scored: list[tuple[CapabilityDescriptor, float]] = []
    for descriptor in descriptors:
        if category and descriptor.category != category:
            continue
        if source and descriptor.source != source:
            continue
        if status and descriptor.availability.status != status:
            continue
        if executable is not None and descriptor.availability.executable != executable:
            continue
        if risk_level and descriptor.risk_level != risk_level:
            continue
        if side_effect and side_effect not in descriptor.side_effects:
            continue
        if provider_kind and descriptor.provider_kind != provider_kind:
            continue
        score = _score_descriptor(descriptor, query, q_tokens)
        if query and score <= 0:
            continue
        scored.append((descriptor, score))
    scored.sort(
        key=lambda item: (
            -item[1],
            -int(item[0].availability.executable),
            item[0].capability_ref,
        )
    )
    total = len(scored)
    end = max(offset, 0) + max(limit, 1)
    return scored[max(offset, 0) : end], total


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


async def _semantic_rerank(
    query: str,
    scored: list[tuple[CapabilityDescriptor, float]],
    *,
    limit: int,
) -> tuple[list[tuple[CapabilityDescriptor, float]], bool]:
    """Reordena SOLO el top léxico con embeddings de Zent (opcional y acotado)."""
    if not query or not scored:
        return scored, False
    candidates = scored[: max(limit * 2, 12)]
    try:
        from src.api.deps import get_embedding_provider

        provider = get_embedding_provider()
        query_vector = await provider.embed(query)
        if not isinstance(query_vector, list):
            return scored, False
        reranked: list[tuple[CapabilityDescriptor, float]] = []
        lexical_max = max((score for _, score in candidates), default=1.0) or 1.0
        for descriptor, score in candidates:
            vector = _EMBEDDING_CACHE.get(descriptor.contract_hash)
            if vector is None:
                text_ = " ".join(
                    [
                        descriptor.capability_ref,
                        descriptor.display_name,
                        descriptor.description,
                        " ".join(descriptor.aliases),
                    ]
                )
                embedded = await provider.embed(text_[:2000])
                if not isinstance(embedded, list):
                    return scored, False
                vector = embedded
                if len(_EMBEDDING_CACHE) < 512:
                    _EMBEDDING_CACHE[descriptor.contract_hash] = vector
            semantic = max(0.0, _cosine(query_vector, vector))
            blended = 0.7 * (score / lexical_max) + 0.3 * semantic
            reranked.append((descriptor, blended))
        reranked.sort(key=lambda item: (-item[1], item[0].capability_ref))
        return reranked + scored[len(candidates) :], True
    except Exception as exc:  # noqa: BLE001 — semántica opcional nunca rompe
        logger.info("capability semantic search unavailable", error=str(exc)[:160])
        return scored, False


async def search_capabilities(
    snapshot: CapabilitySnapshot,
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    semantic: bool = False,
    **filters: Any,
) -> dict[str, Any]:
    scored, total = search_descriptors(
        snapshot.capabilities, query, limit=max(limit, 1), offset=offset, **filters
    )
    semantic_used = False
    if semantic and query:
        scored, semantic_used = await _semantic_rerank(query, scored, limit=limit)
    results = [
        {**descriptor.compact(), "score": round(score, 3)}
        for descriptor, score in scored
    ]
    return {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_hash": snapshot.snapshot_hash,
        "generated_at": snapshot.generated_at.isoformat(),
        "coverage": snapshot.coverage,
        "query": query,
        "semantic_used": semantic_used,
        "total_matches": total,
        "returned": len(results),
        "results": results,
    }


def capability_index(snapshot: CapabilitySnapshot) -> dict[str, CapabilityDescriptor]:
    return snapshot.index()


def refs_for_plan(plan: Any) -> list[str]:
    """Refs que un SemanticPlan realmente usa (para verificar snapshots)."""
    refs: list[str] = []
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps") or []
    for step in steps or []:
        step_type = getattr(step, "type", None) or (step.get("type") if isinstance(step, dict) else None)
        params = getattr(step, "params", None) or (step.get("params") if isinstance(step, dict) else {}) or {}
        if step_type == "integration_action" and params.get("action_id"):
            refs.append(str(params["action_id"]))
        elif step_type == "capability_call" and params.get("capability"):
            refs.append(str(params["capability"]))
        elif step_type == "agent_analysis" and params.get("agent_id"):
            refs.append(f"agent.{params['agent_id']}")
    return sorted(set(refs))


def reset_registry_cache() -> None:
    """Solo para tests: limpia cache e historial."""
    _CACHE.clear()
    _HISTORY.clear()
    _EMBEDDING_CACHE.clear()


__all__ = [
    "CAPABILITY_SCHEMA",
    "CATALOG_VERSION",
    "COVERAGE_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "CapabilityAvailability",
    "CapabilityDescriptor",
    "CapabilityError",
    "CapabilitySnapshot",
    "CapabilitySnapshotStale",
    "EventDescriptor",
    "ResourceDescriptor",
    "build_capability_snapshot",
    "canonical_hash",
    "capability_index",
    "normalize_text",
    "refs_for_plan",
    "reset_registry_cache",
    "search_capabilities",
    "search_descriptors",
    "token_set",
    "verify_snapshot",
]
