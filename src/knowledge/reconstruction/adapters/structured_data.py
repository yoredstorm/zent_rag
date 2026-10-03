# =============================================================================
# Semantic Reconstruction Layer — JSON / XML Source Adapters
# =============================================================================
# Conservar la jerarquía es la reconstrucción. Nada se aplana antes de tiempo:
# objects, arrays, propiedades, atributos, tipos y rutas estables (JSONPath /
# XPath) sobreviven hasta el Knowledge Compiler.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from xml.etree import ElementTree

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
from .document import TextSourceAdapter


def _value_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _preview(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ""
    if value is None:
        return ""
    return str(value)[:200]


class JsonSourceAdapter(SourceAdapter):
    kind = SourceKind.JSON.value
    description = "JSON: jerarquía, objects/arrays/propiedades y JSONPath"

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
        payload = _json_payload(document, raw_text)
        if payload is None:
            fallback = TextSourceAdapter().extract(document, raw_text=raw_text)
            fallback.source_kind = self.kind
            fallback.adapter = self.name
            fallback.warnings.append("JSON payload unavailable; used document blocks")
            return fallback

        nodes = 0
        max_depth = 0

        def visit(value: Any, path: str, depth: int, parent_id) -> None:
            nonlocal nodes, max_depth
            max_depth = max(max_depth, depth)
            kind = _value_kind(value)
            if kind == "object":
                for key, child in value.items():
                    child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
                    child_id = element_uuid(document.id, nodes, child_path)
                    nodes += 1
                    extraction.elements.append(
                        RawElement(
                            id=child_id,
                            kind=ElementKind.PROPERTY.value,
                            text=str(key),
                            order=nodes,
                            depth=depth + 1,
                            parent_id=parent_id,
                            provenance=_provenance(
                                document, self.kind, self.name, child_path, str(key)
                            ),
                            confidence=0.95,
                            attributes={
                                "json_path": child_path,
                                "value_type": _value_kind(child),
                                "preview": _preview(child),
                                "child_count": len(child) if isinstance(child, (dict, list)) else 0,
                            },
                        )
                    )
                    visit(child, child_path, depth + 1, child_id)
            elif kind == "array":
                array_id = parent_id
                for index, child in enumerate(value):
                    child_path = f"{path}[{index}]"
                    child_id = element_uuid(document.id, nodes, child_path)
                    nodes += 1
                    extraction.elements.append(
                        RawElement(
                            id=child_id,
                            kind=ElementKind.PROPERTY.value,
                            text=f"[{index}]",
                            order=nodes,
                            depth=depth + 1,
                            parent_id=array_id,
                            provenance=_provenance(
                                document, self.kind, self.name, child_path, f"[{index}]"
                            ),
                            confidence=0.9,
                            attributes={
                                "json_path": child_path,
                                "value_type": _value_kind(child),
                                "preview": _preview(child),
                            },
                        )
                    )
                    visit(child, child_path, depth + 1, child_id)

        root_id = element_uuid(document.id, 0, "$")
        root_kind = ElementKind.OBJECT.value if isinstance(payload, dict) else ElementKind.ARRAY.value
        extraction.elements.append(
            RawElement(
                id=root_id,
                kind=root_kind,
                text="$",
                order=0,
                depth=0,
                provenance=_provenance(document, self.kind, self.name, "$", "$"),
                confidence=0.95,
                attributes={"value_type": _value_kind(payload)},
            )
        )
        nodes = 1
        visit(payload, "$", 0, root_id)
        extraction.stats = {"nodes": nodes, "max_depth": max_depth}
        return extraction


class XmlSourceAdapter(SourceAdapter):
    kind = SourceKind.XML.value
    description = "XML: árbol de elementos, atributos y XPath"

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
        root = _xml_root(document, raw_text)
        if root is None:
            fallback = TextSourceAdapter().extract(document, raw_text=raw_text)
            fallback.source_kind = self.kind
            fallback.adapter = self.name
            fallback.warnings.append("XML payload unavailable; used document blocks")
            return fallback

        nodes = 0

        def visit(element: ElementTree.Element, xpath: str, depth: int, parent_id) -> None:
            nonlocal nodes
            node_id = element_uuid(document.id, nodes, xpath)
            nodes += 1
            text = (element.text or "").strip()
            extraction.elements.append(
                RawElement(
                    id=node_id,
                    kind=ElementKind.PROPERTY.value,
                    text=element.tag,
                    order=nodes,
                    depth=depth,
                    parent_id=parent_id,
                    provenance=_provenance(
                        document, self.kind, self.name, xpath, text or element.tag, xpath=xpath
                    ),
                    confidence=0.92,
                    attributes={
                        "xpath": xpath,
                        "attributes": dict(element.attrib),
                        "text": text[:200],
                        "child_count": len(list(element)),
                    },
                )
            )
            by_tag: dict[str, int] = {}
            for child in element:
                by_tag[child.tag] = by_tag.get(child.tag, 0) + 1
                position = by_tag[child.tag]
                child_xpath = f"{xpath}/{child.tag}[{position}]"
                visit(child, child_xpath, depth + 1, node_id)

        visit(root, f"/{root.tag}[1]", 0, None)
        extraction.stats = {"nodes": nodes, "max_depth": _xml_depth(root)}
        return extraction


def _provenance(
    document: StructuredDocument,
    source_kind: str,
    adapter: str,
    json_path: str | None,
    excerpt: str,
    *,
    xpath: str | None = None,
) -> SourceProvenance:
    return SourceProvenance(
        source_kind=source_kind,
        adapter=adapter,
        source_id=document.source_id,
        document_id=document.id,
        document_title=document.title,
        json_path=json_path,
        xpath=xpath,
        excerpt=excerpt[:400],
    )


def _json_payload(document: StructuredDocument, raw_text: str | None) -> Any:
    if raw_text:
        stripped = raw_text.lstrip()
        if stripped[:1] in "{[":
            try:
                return json.loads(raw_text)
            except (json.JSONDecodeError, ValueError):
                return None
    metadata_payload = document.metadata.get("json")
    if isinstance(metadata_payload, (dict, list)):
        return metadata_payload
    return None


def _xml_root(document: StructuredDocument, raw_text: str | None) -> ElementTree.Element | None:
    candidate = raw_text
    if not candidate or candidate.lstrip()[:1] != "<":
        metadata_payload = document.metadata.get("xml")
        if isinstance(metadata_payload, str):
            candidate = metadata_payload
    if not candidate:
        return None
    try:
        # ElementTree estándar no resuelve entidades externas ni DTDs remotos;
        # el XML ya pasó el límite de ingesta autenticado.
        return ElementTree.fromstring(candidate)  # noqa: S314
    except ElementTree.ParseError:
        return None


def _xml_depth(element: ElementTree.Element) -> int:
    children = list(element)
    if not children:
        return 1
    return 1 + max(_xml_depth(child) for child in children)


__all__ = ["JsonSourceAdapter", "XmlSourceAdapter"]
