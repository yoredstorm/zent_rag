# =============================================================================
# Semantic Reconstruction Layer — API Source Adapter
# =============================================================================
# Una API (OpenAPI/Swagger, REST, GraphQL) no es texto plano: es service ->
# endpoint -> method -> parámetros -> request/response schema -> status codes.
# El adapter reconstruye ese contrato y conserva el ejemplo como evidencia.
# =============================================================================
from __future__ import annotations

import json
from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument

from ..contracts import (
    ElementKind,
    RawElement,
    RawExtraction,
    SourceKind,
    SourceProvenance,
    element_uuid,
)
from .base import SourceAdapter
from .structured_data import JsonSourceAdapter

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


class ApiSourceAdapter(SourceAdapter):
    kind = SourceKind.API.value
    description = "API/OpenAPI: servicio, endpoint, método, parámetros, schemas, status"

    def extract(
        self,
        document: StructuredDocument,
        *,
        raw_text: str | None = None,
    ) -> RawExtraction:
        extraction = RawExtraction(
            source_kind=self.kind,
            adapter=self.name,
            title=document.title or document.external_id,
        )
        spec = _api_spec(document, raw_text)
        if not spec or not isinstance(spec, dict) or "paths" not in spec:
            fallback = JsonSourceAdapter().extract(document, raw_text=raw_text)
            fallback.source_kind = self.kind
            fallback.adapter = self.name
            fallback.warnings.append("OpenAPI document unavailable; used JSON hierarchy")
            return fallback

        info = spec.get("info") or {}
        version = str(info.get("version") or spec.get("openapi") or "")
        service = str(info.get("title") or document.title or "service")
        servers = [
            str(server.get("url"))
            for server in spec.get("servers") or ()
            if isinstance(server, dict) and server.get("url")
        ]
        position = 0

        def add(element: RawElement) -> None:
            nonlocal position
            position += 1
            extraction.elements.append(element)

        add(
            RawElement(
                id=element_uuid(document.id, position, f"api:{service}"),
                kind=ElementKind.METADATA.value,
                text=service,
                order=position,
                depth=0,
                provenance=SourceProvenance(
                    source_kind=self.kind,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    endpoint=None,
                    excerpt=service,
                ),
                confidence=0.95,
                attributes={
                    "version": version,
                    "description": str(info.get("description") or "")[:500],
                    "servers": servers[:5],
                },
            )
        )

        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            for method in _HTTP_METHODS:
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                endpoint_id = element_uuid(
                    document.id, position, f"endpoint:{method.upper()}:{path}"
                )
                parameter_rows = _parameters(path_item, operation)
                responses = _responses(operation)
                request_schema = _request_schema(operation)
                add(
                    RawElement(
                        id=endpoint_id,
                        kind=ElementKind.ENDPOINT.value,
                        text=f"{method.upper()} {path}",
                        order=position,
                        depth=1,
                        provenance=SourceProvenance(
                            source_kind=self.kind,
                            adapter=self.name,
                            source_id=document.source_id,
                            document_id=document.id,
                            document_title=document.title,
                            endpoint=path,
                            method=method.upper(),
                            excerpt=str(operation.get("summary") or f"{method.upper()} {path}")[:400],
                        ),
                        confidence=0.95,
                        attributes={
                            "operation_id": operation.get("operationId"),
                            "summary": operation.get("summary"),
                            "description": str(operation.get("description") or "")[:500],
                            "tags": list(operation.get("tags") or ()),
                            "parameters": parameter_rows,
                            "request_schema": request_schema,
                            "responses": responses,
                            "version": version,
                            "servers": servers[:5],
                        },
                    )
                )
                for parameter in parameter_rows:
                    add(
                        RawElement(
                            id=element_uuid(
                                document.id,
                                position,
                                f"param:{method}:{path}:{parameter.get('name')}",
                            ),
                            kind=ElementKind.PARAMETER.value,
                            text=str(parameter.get("name") or ""),
                            order=position,
                            depth=2,
                            parent_id=endpoint_id,
                            provenance=SourceProvenance(
                                source_kind=self.kind,
                                adapter=self.name,
                                source_id=document.source_id,
                                document_id=document.id,
                                document_title=document.title,
                                endpoint=path,
                                method=method.upper(),
                                excerpt=str(parameter.get("description") or parameter.get("name") or ""),
                            ),
                            confidence=0.9,
                            attributes=dict(parameter),
                        )
                    )
                for code, response in responses.items():
                    response_path = f"paths.{path}.{method}.responses.{code}"
                    add(
                        RawElement(
                            id=element_uuid(document.id, position, f"response:{method}:{path}:{code}"),
                            kind=ElementKind.RESPONSE.value,
                            text=f"{code} {response.get('description') or ''}".strip(),
                            order=position,
                            depth=2,
                            parent_id=endpoint_id,
                            provenance=SourceProvenance(
                                source_kind=self.kind,
                                adapter=self.name,
                                source_id=document.source_id,
                                document_id=document.id,
                                document_title=document.title,
                                endpoint=path,
                                method=method.upper(),
                                response_path=response_path,
                                excerpt=str(response.get("description") or code)[:400],
                            ),
                            confidence=0.9,
                            attributes={
                                "status_code": code,
                                "description": response.get("description"),
                                "schema": response.get("schema"),
                            },
                        )
                    )

        operations = sum(
            1
            for path_item in (spec.get("paths") or {}).values()
            if isinstance(path_item, dict)
            for method in _HTTP_METHODS
            if isinstance(path_item.get(method), dict)
        )
        extraction.stats = {
            "endpoints": len(spec.get("paths") or {}),
            "operations": operations,
            "elements": len(extraction.elements),
        }
        return extraction


def _api_spec(document: StructuredDocument, raw_text: str | None) -> dict[str, Any] | None:
    for key in ("openapi", "api_spec", "swagger"):
        value = document.metadata.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = _parse(str(value))
            if parsed is not None:
                return parsed
    if raw_text:
        return _parse(raw_text)
    return None


def _parse(text: str) -> dict[str, Any] | None:
    stripped = text.lstrip()
    if stripped[:1] == "{":
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    try:
        import yaml  # type: ignore[import-untyped]

        parsed = yaml.safe_load(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001 — YAML opcional: sin él, JSON solamente
        return None


def _parameters(path_item: dict, operation: dict) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for parameter in list(path_item.get("parameters") or ()) + list(operation.get("parameters") or ()):
        if not isinstance(parameter, dict):
            continue
        schema = parameter.get("schema") or {}
        merged.append(
            {
                "name": parameter.get("name"),
                "in": parameter.get("in"),
                "required": bool(parameter.get("required", False)),
                "type": schema.get("type") if isinstance(schema, dict) else None,
                "description": parameter.get("description"),
            }
        )
    return merged[:50]


def _responses(operation: dict) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for code, response in (operation.get("responses") or {}).items():
        if not isinstance(response, dict):
            continue
        schema = response.get("content")
        if isinstance(schema, dict):
            schema = next(
                (
                    media.get("schema")
                    for media in schema.values()
                    if isinstance(media, dict)
                ),
                None,
            )
        else:
            schema = response.get("schema")
        result[str(code)] = {
            "description": str(response.get("description") or "")[:300],
            "schema": _schema_ref(schema),
        }
    return result


def _request_schema(operation: dict) -> dict[str, Any] | None:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content") or {}
    if not isinstance(content, dict):
        return None
    for media in content.values():
        if isinstance(media, dict) and media.get("schema"):
            return _schema_ref(media["schema"])
    return None


def _schema_ref(schema: Any) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    return {
        "type": schema.get("type"),
        "ref": schema.get("$ref"),
        "required": list(schema.get("required") or ())[:20],
        "properties": list((schema.get("properties") or {}).keys())[:50],
    }


__all__ = ["ApiSourceAdapter"]
