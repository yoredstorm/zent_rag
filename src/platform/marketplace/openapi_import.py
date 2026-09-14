# =============================================================================
# Universal API Connector — OpenAPI import (misión §11-§15, §17).
#
# Pipeline determinista, sin ejecutar endpoints de la API externa:
#
#   documento OpenAPI → parse → validación de seguridad → discovery de
#   operaciones → IntegrationDraft → revisión humana → install.
#
# El LLM nunca participa de la validación HTTP/schema: los labels pueden
# mejorarse luego, pero un endpoint inexistente no puede inventarse aquí.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

import yaml

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

MAX_DOCUMENT_CHARS = 2_000_000
MAX_FETCH_SECONDS = 15.0
MAX_OPERATIONS = 50
MAX_SCHEMA_DEPTH = 4
ALLOWED_METHODS = ("get", "post", "put", "patch")
SKIPPED_METHODS = ("delete", "options", "head", "trace")

_AUTH_HEADER_PARAMS = {"authorization", "x-api-key", "api-key", "apikey", "x-auth-token"}

_METHOD_PREFIX = {
    "get": "Consultar",
    "post": "Crear",
    "put": "Actualizar",
    "patch": "Actualizar",
}

_OPERATION_VERBS = {
    "get", "list", "search", "find", "fetch", "read", "query",
    "create", "add", "new", "post",
    "update", "patch", "put", "edit", "set",
    "delete", "remove",
}


class OpenApiImportError(ValueError):
    """Error de importación (documento inválido o URL insegura)."""

    def __init__(self, message: str, code: str = "OPENAPI_INVALID") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Utilidades de nombres
# ---------------------------------------------------------------------------
def slugify(value: str, *, fallback: str = "api", max_len: int = 60) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "")).strip("-").lower()
    raw = re.sub(r"-{2,}", "-", raw)
    return (raw or fallback)[:max_len].strip("-") or fallback


def humanize_identifier(value: str) -> str:
    """getInventoryBySku → 'Inventory by Sku' (sin inventar traducciones)."""
    text = re.sub(r"[_\-]+", " ", str(value or "")).strip()
    if not text:
        return ""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).split()
    if words and words[0].lower() in _OPERATION_VERBS:
        words = words[1:]
    return " ".join(words[:6])


def _method_prefix(method: str, has_path_param: bool) -> str:
    if method == "get":
        return "Consultar" if has_path_param else "Listar"
    return _METHOD_PREFIX.get(method, method.upper())


def _suggest_display_name(method: str, path: str, operation: dict) -> str:
    summary = str(operation.get("summary") or "").strip()
    if summary:
        return summary[0].upper() + summary[1:][:110]
    resource = _resource_from_path(path)
    label = _method_prefix(method, "{" in path)
    if operation.get("operationId"):
        human = humanize_identifier(str(operation["operationId"]))
        if human:
            return f"{label} {human}"[:120]
    return f"{label} {resource}"[:120] if resource else f"{label} {path}"[:120]


def _resource_from_path(path: str) -> str:
    segments = [s for s in str(path or "").split("/") if s and not s.startswith("{")]
    if not segments:
        return ""
    return re.sub(r"[^a-zA-Z0-9]+", " ", segments[-1]).strip()[:40]


# ---------------------------------------------------------------------------
# Parseo del documento
# ---------------------------------------------------------------------------
def parse_openapi_document(value: str | bytes | dict, *, format_hint: str | None = None) -> dict:
    """Devuelve el documento OpenAPI como dict (JSON o YAML). Nunca ejecuta red."""
    if isinstance(value, dict):
        document = value
    elif isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        if len(text) > MAX_DOCUMENT_CHARS:
            raise OpenApiImportError(
                f"documento demasiado grande (máx {MAX_DOCUMENT_CHARS // 1000} KB)",
                code="OPENAPI_TOO_LARGE",
            )
        stripped = text.lstrip()
        document = None
        if format_hint in (None, "json") and stripped.startswith("{"):
            try:
                parsed = json.loads(text)
                document = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                document = None
        if document is None:
            try:
                parsed = yaml.safe_load(text)
                document = parsed if isinstance(parsed, dict) else None
            except yaml.YAMLError as exc:
                raise OpenApiImportError(
                    f"no pude leer el documento como JSON/YAML: {str(exc)[:120]}",
                    code="OPENAPI_INVALID_DOCUMENT",
                ) from exc
    else:
        raise OpenApiImportError("documento inválido", code="OPENAPI_INVALID_DOCUMENT")

    if not isinstance(document, dict):
        raise OpenApiImportError("el documento no es un objeto OpenAPI", code="OPENAPI_INVALID_DOCUMENT")
    if document.get("swagger"):
        raise OpenApiImportError(
            "Swagger 2.0 no está soportado todavía; exporta el documento como OpenAPI 3.",
            code="OPENAPI_UNSUPPORTED_VERSION",
        )
    version = str(document.get("openapi") or "")
    if not version.startswith("3."):
        raise OpenApiImportError(
            "falta la clave 'openapi: 3.x' en el documento",
            code="OPENAPI_INVALID_DOCUMENT",
        )
    if not isinstance(document.get("paths"), dict) or not document["paths"]:
        raise OpenApiImportError("el documento no declara paths", code="OPENAPI_NO_OPERATIONS")
    return document


def spec_hash(document: dict) -> str:
    raw = json.dumps(document, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Seguridad (§12, §38): servidores, SSRF, tamaño, métodos
# ---------------------------------------------------------------------------
def validate_server_url(url: str) -> str:
    """Valida un server URL de OpenAPI: https + host público. Devuelve el host."""
    from src.agents.tools.base import ToolError
    from src.agents.tools.tools_builtin import CallApiTool

    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise OpenApiImportError(
            f"server '{url}' debe ser https con host",
            code="OPENAPI_UNSAFE_SERVER",
        )
    try:
        CallApiTool._ssrf_check(parsed.hostname)
    except ToolError as exc:
        raise OpenApiImportError(
            f"server bloqueado por seguridad: {exc}",
            code="OPENAPI_UNSAFE_SERVER",
        ) from exc
    return parsed.hostname


def _resolve_server_url(server: dict) -> str | None:
    url = str(server.get("url") or "")
    if not url:
        return None
    variables = server.get("variables") or {}
    for name, spec in variables.items():
        default = (spec or {}).get("default")
        if default is not None:
            url = url.replace("{" + str(name) + "}", str(default))
    return url


def _pick_server(document: dict) -> tuple[str, list[str]]:
    servers = document.get("servers") or []
    candidates: list[str] = []
    warnings: list[str] = []
    for server in servers:
        resolved = _resolve_server_url(server)
        if resolved:
            candidates.append(resolved)
    https = [c for c in candidates if c.startswith("https://")]
    if not https:
        raise OpenApiImportError(
            "el documento no declara un server https; agrega servers[0].url",
            code="OPENAPI_NO_SERVER",
        )
    if len(https) > 1:
        warnings.append(f"El documento declara {len(https)} servers; uso el primero.")
    base_url = https[0].rstrip("/")
    validate_server_url(base_url)
    return base_url, warnings


# ---------------------------------------------------------------------------
# Auth detection (§15) — declarativa, nunca prueba credenciales
# ---------------------------------------------------------------------------
def detect_auth(document: dict) -> dict:
    schemes: dict[str, Any] = (document.get("components") or {}).get("securitySchemes") or {}
    referenced: list[str] = []
    for entry in document.get("security") or []:
        if isinstance(entry, dict):
            referenced.extend(str(k) for k in entry.keys())
    if not referenced:
        for path_item in (document.get("paths") or {}).values():
            if not isinstance(path_item, dict):
                continue
            for method in ALLOWED_METHODS:
                op = path_item.get(method)
                if isinstance(op, dict):
                    for entry in op.get("security") or []:
                        if isinstance(entry, dict):
                            referenced.extend(str(k) for k in entry.keys())
    for name in referenced:
        scheme = schemes.get(name) or {}
        kind = str(scheme.get("type") or "")
        if kind == "apiKey":
            where = str(scheme.get("in") or "header")
            header = str(scheme.get("name") or "X-API-Key")
            notes = []
            if where != "header":
                notes.append("La API espera la clave en query/cookie; el conector la envía como header.")
            return {
                "kind": "api_key",
                "security_scheme": name,
                "header_name": header,
                "in": where,
                "scheme": None,
                "notes": notes,
            }
        if kind == "http":
            http_scheme = str(scheme.get("scheme") or "").lower()
            if http_scheme == "bearer":
                return {"kind": "bearer", "security_scheme": name, "header_name": "Authorization",
                        "in": "header", "scheme": "bearer", "notes": []}
            if http_scheme == "basic":
                return {"kind": "basic", "security_scheme": name, "header_name": "Authorization",
                        "in": "header", "scheme": "basic", "notes": []}
            return {"kind": "api_key", "security_scheme": name, "header_name": "Authorization",
                    "in": "header", "scheme": None,
                    "notes": [f"Esquema http '{http_scheme}' no reconocido; se tratará como API key."]}
        if kind in ("oauth2", "openIdConnect"):
            return {"kind": "oauth2", "security_scheme": name, "header_name": "Authorization",
                    "in": "header", "scheme": "bearer",
                    "notes": ["OAuth2 requiere conectar el proveedor; puedes pegar un token temporal."]}
    return {"kind": "none", "security_scheme": None, "header_name": None,
            "in": None, "scheme": None, "notes": []}


# ---------------------------------------------------------------------------
# Schemas → business parameter schema (§9, §10, §17)
# ---------------------------------------------------------------------------
def _resolve_ref(document: dict, ref: str, *, depth: int = 0) -> dict:
    if depth > 6 or not str(ref).startswith("#/"):
        return {}
    node: Any = document
    for part in str(ref)[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def _deep_resolve(document: dict, schema: Any, *, depth: int = 0) -> dict:
    if depth > MAX_SCHEMA_DEPTH or not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        return _deep_resolve(document, _resolve_ref(document, str(schema["$ref"]), depth=depth), depth=depth + 1)
    out = {k: v for k, v in schema.items() if k not in ("$ref", "allOf", "oneOf", "anyOf", "not")}
    for combinator in ("allOf", "oneOf", "anyOf"):
        if combinator in schema and isinstance(schema[combinator], list):
            merged: dict[str, Any] = {}
            required: list[str] = []
            for part in schema[combinator]:
                resolved = _deep_resolve(document, part, depth=depth + 1)
                merged.update((resolved.get("properties") or {}))
                required.extend(resolved.get("required") or [])
            if merged:
                out.setdefault("type", "object")
                out["properties"] = merged
                if required:
                    out.setdefault("required", required)
    if out.get("type") == "object" and isinstance(out.get("properties"), dict):
        out["properties"] = {
            str(k): _deep_resolve(document, v, depth=depth + 1)
            for k, v in out["properties"].items()
        }
    if out.get("type") == "array" and isinstance(out.get("items"), dict):
        out["items"] = _deep_resolve(document, out["items"], depth=depth + 1)
    return out


def _business_property(name: str, schema: dict, *, fallback_label: str | None = None) -> dict:
    prop: dict[str, Any] = {"type": str(schema.get("type") or "string")}
    for key in ("format", "enum", "default", "minimum", "maximum", "minLength", "maxLength"):
        if key in schema and schema[key] is not None:
            prop[key] = schema[key]
    if isinstance(schema.get("example"), (str, int, float, bool)):
        prop["examples"] = [schema["example"]]
    elif isinstance(schema.get("examples"), list):
        prop["examples"] = schema["examples"][:3]
    prop["x-business-label"] = fallback_label or humanize_identifier(name) or name
    description = str(schema.get("description") or "").strip()
    if description:
        prop["x-business-help"] = description[:200]
    if prop["type"] == "object":
        prop["x-business-level"] = "advanced"
    return prop


def _param_property(document: dict, param: dict) -> dict | None:
    name = str(param.get("name") or "")
    if not name or name.lower() in _AUTH_HEADER_PARAMS:
        return None
    schema = _deep_resolve(document, param.get("schema") or {})
    prop = _business_property(name, schema)
    description = str(param.get("description") or "").strip()
    if description:
        prop["x-business-help"] = description[:200]
    return prop


def _body_properties(document: dict, request_body: dict) -> tuple[dict[str, dict], list[str]]:
    content = request_body.get("content") or {}
    media = content.get("application/json") or content.get("*/*") or {}
    schema = _deep_resolve(document, media.get("schema") or {})
    if str(schema.get("type")) == "object" and isinstance(schema.get("properties"), dict):
        props = {
            str(k): _business_property(str(k), _deep_resolve(document, v))
            for k, v in schema["properties"].items()
        }
        return props, [str(x) for x in (schema.get("required") or [])]
    if schema:
        prop = _business_property("body", schema, fallback_label="Contenido")
        prop["x-business-level"] = "advanced"
        return {"body": prop}, []
    return {}, []


def _output_schema(document: dict, responses: dict) -> tuple[dict, bool]:
    response = None
    for code in ("200", "201", "202", "203", "204", "206", "2XX"):
        if code in (responses or {}):
            response = responses[code]
            break
    if not isinstance(response, dict):
        return {"type": "object", "properties": {}}, False
    response = _deep_resolve(document, response)
    content = response.get("content") or {}
    media = content.get("application/json") or content.get("*/*") or {}
    schema = _deep_resolve(document, media.get("schema") or {})
    if str(schema.get("type")) == "object" and isinstance(schema.get("properties"), dict):
        return (
            {
                "type": "object",
                "properties": {
                    str(k): _business_property(k, _deep_resolve(document, v))
                    for k, v in list(schema["properties"].items())[:40]
                },
            },
            False,
        )
    if str(schema.get("type")) == "array":
        return (
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "x-business-label": "Registros",
                        "x-business-help": (
                            "La API devuelve una lista; cada registro queda disponible para el workflow."
                        ),
                    }
                },
            },
            True,
        )
    return {"type": "object", "properties": {}}, False


def _output_map(output_schema: dict, *, is_array: bool) -> dict[str, str]:
    if is_array:
        return {"items": "items"}
    props = (output_schema.get("properties") or {})
    return {str(k): str(k) for k in props}


# ---------------------------------------------------------------------------
# Discovery (§12, §13)
# ---------------------------------------------------------------------------
def discover_operations(document: dict, *, slug: str, base_url: str) -> tuple[list[dict], dict]:
    """Genera capabilities/actions de negocio a partir de paths/operations."""
    capabilities: dict[str, dict] = {}
    report: dict[str, Any] = {
        "operations_total": 0,
        "actions_generated": 0,
        "skipped": [],
        "warnings": [],
    }
    used_action_ids: set[str] = set()
    truncated = False

    for path, path_item in (document.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        shared_params = [p for p in (path_item.get("parameters") or []) if isinstance(p, dict)]
        for method in ALLOWED_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            report["operations_total"] += 1
            if report["actions_generated"] >= MAX_OPERATIONS:
                truncated = True
                continue
            action = _operation_to_action(
                document, path, method, operation, shared_params, slug, base_url,
                used_action_ids=used_action_ids, report=report,
            )
            if action is None:
                continue
            tag = ""
            if isinstance(operation.get("tags"), list) and operation["tags"]:
                tag = str(operation["tags"][0])
            if not tag:
                tag = _resource_from_path(path) or "General"
            cap_slug = slugify(tag, fallback="general", max_len=50)
            cap = capabilities.setdefault(
                cap_slug,
                {"slug": cap_slug, "name": tag[:80], "description": "", "actions": []},
            )
            cap["actions"].append(action)
            report["actions_generated"] += 1
        for skipped in SKIPPED_METHODS:
            if isinstance(path_item.get(skipped), dict):
                report["skipped"].append(
                    {"method": skipped.upper(), "path": path, "reason": "método fuera de la allowlist"}
                )

    if truncated:
        report["warnings"].append(
            {"code": "operations_truncated",
             "message": f"El documento supera {MAX_OPERATIONS} operaciones; importa por partes."}
        )
    return list(capabilities.values()), report


def _operation_to_action(
    document: dict,
    path: str,
    method: str,
    operation: dict,
    shared_params: list[dict],
    slug: str,
    base_url: str,
    *,
    used_action_ids: set[str],
    report: dict,
) -> dict | None:
    params: list[dict] = list(shared_params) + [
        p for p in (operation.get("parameters") or []) if isinstance(p, dict)
    ]
    properties: dict[str, dict] = {}
    required: list[str] = []
    body_collisions: list[str] = []
    for param in params:
        if str(param.get("in") or "") not in ("path", "query"):
            continue
        prop = _param_property(document, param)
        if prop is None:
            continue
        name = str(param.get("name"))
        properties[name] = prop
        if param.get("required") or str(param.get("in")) == "path":
            required.append(name)

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        request_body = _deep_resolve(document, request_body)
        body_props, body_required = _body_properties(document, request_body)
        for key, prop in body_props.items():
            if key in properties:
                body_collisions.append(key)
                continue
            properties[key] = prop
        for name in body_required:
            if name in properties and name not in required:
                required.append(name)

    output_schema, is_array = _output_schema(document, operation.get("responses") or {})

    op_slug = slugify(
        str(operation.get("operationId") or f"{method}-{path}"),
        fallback=f"{method}-{path}",
        max_len=60,
    )
    action_id = f"{slug}.{op_slug}"[:120]
    counter = 2
    while action_id in used_action_ids:
        action_id = f"{slug}.{op_slug}-{counter}"[:120]
        counter += 1
    used_action_ids.add(action_id)

    if body_collisions:
        report["warnings"].append(
            {
                "code": "parameter_collision",
                "message": (
                    f"{method.upper()} {path}: el body pisa parámetros con el mismo "
                    f"nombre ({', '.join(body_collisions)})."
                ),
            }
        )
    if not operation.get("operationId"):
        report["warnings"].append(
            {"code": "missing_operation_id",
             "message": f"{method.upper()} {path}: sin operationId; invente un id estable."}
        )

    read_only = method == "get"
    return {
        "action_id": action_id,
        "display_name": _suggest_display_name(method, path, operation),
        "description": str(operation.get("description") or operation.get("summary") or "")[:300],
        "method": method.upper(),
        "path_template": path,
        "base_url": base_url,
        "query": {},
        "output_map": _output_map(output_schema, is_array=is_array),
        "input_schema": {
            "type": "object",
            "properties": properties,
            **({"required": required} if required else {}),
        },
        "output_schema": output_schema,
        "risk_level": "info" if read_only else "normal",
        "read_only": read_only,
        "requires_approval": False,
        "enabled": True,
    }


# ---------------------------------------------------------------------------
# Draft (§11-§13)
# ---------------------------------------------------------------------------
def build_draft(
    document: dict,
    *,
    source_kind: str = "document",
    source_url: str | None = None,
    name_override: str | None = None,
    slug_override: str | None = None,
) -> dict:
    """Documento validado → IntegrationDraft (sin persistir, sin ejecutar)."""
    document = parse_openapi_document(document)
    info = document.get("info") or {}
    title = str(name_override or info.get("title") or "API importada").strip()[:150]
    slug = slugify(slug_override or title, fallback="api-importada", max_len=60)
    base_url, server_warnings = _pick_server(document)
    auth = detect_auth(document)
    capabilities, report = discover_operations(document, slug=slug, base_url=base_url)
    if not capabilities:
        raise OpenApiImportError(
            "no encontré operaciones GET/POST/PUT/PATCH en el documento",
            code="OPENAPI_NO_OPERATIONS",
        )
    report["warnings"] = list(report.get("warnings") or []) + [
        {"code": "server", "message": w} for w in server_warnings
    ]
    if auth.get("notes"):
        for note in auth["notes"]:
            report["warnings"].append({"code": "auth", "message": note})
    report["host"] = urlparse(base_url).hostname
    report["openapi_version"] = str(document.get("openapi"))
    return {
        "slug": slug,
        "name": title,
        "provider": f"API importada · {urlparse(base_url).hostname or slug}",
        "description": str(info.get("description") or "")[:400],
        "base_url": base_url,
        "auth": auth,
        "rate_limits": {},
        "source": {
            "kind": source_kind,
            "url": source_url,
            "spec_hash": spec_hash(document),
            "openapi_version": str(document.get("openapi")),
        },
        "capabilities": capabilities,
        "report": report,
    }


def draft_to_manifest(draft: dict, *, slug: str, organization_id: Any) -> dict:
    """IntegrationDraft → IntegrationManifest v2 registrable."""
    auth_kind = str((draft.get("auth") or {}).get("kind") or "none")
    public = auth_kind == "none"
    draft_slug = str(draft.get("slug") or "")
    actions: list[dict] = []
    for capability in draft.get("capabilities") or []:
        cap_actions = []
        for action in capability.get("actions") or []:
            if not action.get("enabled", True):
                continue
            action_id = str(action["action_id"])
            if draft_slug and action_id.startswith(f"{draft_slug}."):
                action_id = f"{slug}." + action_id[len(draft_slug) + 1:]
            base_url = str(action.get("base_url") or draft.get("base_url") or "")
            cap_actions.append(
                {
                    "action_id": action_id,
                    "display_name": action.get("display_name") or action["action_id"],
                    "description": action.get("description") or "",
                    "input_schema": action.get("input_schema") or {"type": "object", "properties": {}},
                    "output_schema": action.get("output_schema") or {"type": "object", "properties": {}},
                    "risk_level": action.get("risk_level") or ("info" if action.get("read_only") else "normal"),
                    "read_only": bool(action.get("read_only", True)),
                    "requires_approval": bool(action.get("requires_approval", False)),
                    "cache_policy": {"allow": False},
                    "cost_model": {"model": "FREE"},
                    "timeout_ms": 8000,
                    "provider_config": {
                        "kind": "public_rest" if public else "rest",
                        "base_url": base_url,
                        "path_template": action.get("path_template") or "/",
                        "method": action.get("method") or "GET",
                        "query": action.get("query") or {},
                        "output_map": action.get("output_map") or {},
                    },
                    "output_map": action.get("output_map") or {},
                }
            )
        if cap_actions:
            actions.append(
                {
                    "slug": capability.get("slug") or "general",
                    "name": capability.get("name") or capability.get("slug") or "General",
                    "description": capability.get("description") or "",
                    "actions": cap_actions,
                }
            )
    if not actions:
        raise OpenApiImportError(
            "el borrador no tiene acciones habilitadas",
            code="OPENAPI_NO_OPERATIONS",
        )
    return {
        "slug": slug,
        "name": draft.get("name") or slug,
        "provider": draft.get("provider") or "API importada",
        "description": draft.get("description") or "",
        "category": "data",
        "auth_modes": ["NONE"] if public else ["BYOC"],
        "pricing": {"model": "BYOC_NO_MARKUP"},
        "rate_limits": draft.get("rate_limits") or {},
        "data_policy": {},
        "support": {
            "imported": True,
            "source": (draft.get("source") or {}).get("url"),
            "organization_id": str(organization_id),
        },
        "status": "PUBLISHED",
        "organization_id": organization_id,
        "capabilities": actions,
    }


__all__ = [
    "OpenApiImportError",
    "ALLOWED_METHODS",
    "MAX_DOCUMENT_CHARS",
    "MAX_OPERATIONS",
    "build_draft",
    "detect_auth",
    "discover_operations",
    "draft_to_manifest",
    "fetch_openapi_document",
    "parse_openapi_document",
    "slugify",
    "spec_hash",
    "validate_server_url",
]


async def fetch_openapi_document(url: str) -> str:
    """Descarga el documento OpenAPI (nunca endpoints de la API).

    HTTPS, sin redirects, timeout acotado, tamaño máximo y SSRF check.
    """
    import httpx

    from src.agents.tools.base import ToolError
    from src.agents.tools.tools_builtin import CallApiTool

    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise OpenApiImportError("la URL debe ser https con host", code="OPENAPI_UNSAFE_URL")
    try:
        CallApiTool._ssrf_check(parsed.hostname)
    except ToolError as exc:
        raise OpenApiImportError(
            f"host bloqueado por seguridad: {exc}", code="OPENAPI_UNSAFE_URL"
        ) from exc
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=MAX_FETCH_SECONDS) as client:
            resp = await client.get(
                url, headers={"Accept": "application/json, application/yaml, text/yaml, */*"}
            )
    except OpenApiImportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OpenApiImportError(
            f"no pude descargar el documento: {str(exc)[:150]}", code="OPENAPI_FETCH_FAILED"
        ) from exc
    if resp.status_code in (301, 302, 303, 307, 308):
        raise OpenApiImportError(
            "el documento redirige a otra URL; pega la URL final", code="OPENAPI_REDIRECT"
        )
    if resp.status_code >= 400:
        raise OpenApiImportError(
            f"la URL respondió {resp.status_code}", code="OPENAPI_FETCH_FAILED"
        )
    if len(resp.text) > MAX_DOCUMENT_CHARS:
        raise OpenApiImportError("documento demasiado grande", code="OPENAPI_TOO_LARGE")
    return resp.text
