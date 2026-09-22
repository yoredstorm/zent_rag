# =============================================================================
# Language golden — español de negocio/técnico/casual, typos, Spanglish, SQL,
# field names, códigos, SKUs, registros tipo aviación y abreviaturas.
# =============================================================================
# Compara dos formas de mandar el estado a JEV:
#   raw        → el texto del usuario tal cual
#   canonical  → minúsculas + sin acentos + abreviaturas expandidas, con
#                códigos/SKUs/field names intactos
#
# NO hay traducción obligatoria: el reporte es evidencia para decidir. Los
# términos esperados nunca se "corrigen" si parecen códigos.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

MODE_RAW = "raw"
MODE_CANONICAL = "canonical"
LANGUAGE_MODES = (MODE_RAW, MODE_CANONICAL)

# Código/SKU/field name: nunca se toca (ni acentos ni abreviaturas).
_CODE_RE = re.compile(r"\b[a-z]{1,5}[-_ ]?\d{2,}\b", re.IGNORECASE)
_FIELD_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

_ABBREVIATIONS: dict[str, str] = {
    "q": "que",
    "x": "por",
    "dpto": "departamento",
    "depto": "departamento",
    "fact": "factura",
    "cta": "cuenta",
    "nro": "numero",
    "n°": "numero",
    "tel": "telefono",
    "ped": "pedido",
    "prod": "producto",
    "cant": "cantidad",
    "fec": "fecha",
    "clte": "cliente",
    "vnd": "vendedor",
    "av": "avion",
    "aero": "aerolinea",
    "pax": "pasajero",
    "vuelo": "vuelo",
    "eta": "hora_estimada_llegada",
    "etd": "hora_estimada_salida",
    "kpi": "indicador",
    "pyme": "empresa_pequena",
}


@dataclass(frozen=True, kw_only=True)
class LanguageCase:
    id: str
    text: str
    locale: str = "es"
    kind: str = "business"
    expected_family: str | None = None
    expected_terms: tuple[str, ...] = ()
    note: str = ""


def default_cases() -> list[LanguageCase]:
    return [
        LanguageCase(
            id="es_business",
            text="¿Cuántos pedidos facturados tuvimos el mes pasado por vendedor?",
            locale="es",
            kind="business",
            expected_family="database",
            expected_terms=("pedidos", "facturados", "vendedor"),
        ),
        LanguageCase(
            id="es_technical",
            text="El webhook del ERP falla con timeout al sincronizar stock",
            locale="es_tecnico",
            kind="technical",
            expected_family="knowledge",
            expected_terms=("webhook", "erp", "timeout", "stock"),
        ),
        LanguageCase(
            id="es_casual",
            text="che, ¿me pasás el horario de atención?",
            locale="es",
            kind="casual",
            expected_family="knowledge",
            expected_terms=("horario", "atencion"),
        ),
        LanguageCase(
            id="es_typos",
            text="póliza de deboluciones y garantia",
            locale="es",
            kind="typos",
            expected_family="knowledge",
            expected_terms=("poliza", "deboluciones", "garantia"),
        ),
        LanguageCase(
            id="spanglish",
            text="necesito el refund policy para un order cancelado",
            locale="mixed",
            kind="spanglish",
            expected_family="knowledge",
            expected_terms=("refund", "policy", "order"),
        ),
        LanguageCase(
            id="sql_terms",
            text="SELECT count(*) FROM pedidos WHERE fecha > '2026-01-01' GROUP BY vendedor",
            locale="es",
            kind="sql",
            expected_family="database",
            expected_terms=("select", "count", "pedidos", "vendedor"),
        ),
        LanguageCase(
            id="field_names",
            text="¿Qué significa invoice_status y account_id en la tabla invoices?",
            locale="es_tecnico",
            kind="fields",
            expected_family="knowledge",
            expected_terms=("invoice_status", "account_id", "invoices"),
        ),
        LanguageCase(
            id="codes_skus",
            text="¿Hay stock del SKU-7788 y del LOTE A-2231?",
            locale="es",
            kind="codes",
            expected_family="database",
            expected_terms=("sku-7788", "a-2231"),
        ),
        LanguageCase(
            id="aviation",
            text="vuelo AR1234 con pax 180, ETA 14:30 y demora en pista",
            locale="es",
            kind="aviation",
            expected_family="database",
            expected_terms=("ar1234", "pax", "eta", "pista"),
        ),
        LanguageCase(
            id="abbreviations",
            text="cant prod x dpto y nro de fact del clte",
            locale="es",
            kind="abbreviations",
            expected_family="database",
            expected_terms=("cantidad", "producto", "departamento", "factura"),
        ),
        LanguageCase(
            id="es_ambiguous",
            text="¿eso aplica acá?",
            locale="es",
            kind="ambiguous",
            expected_family=None,
            expected_terms=(),
        ),
    ]


def coverage(cases: Iterable[LanguageCase] | None = None) -> dict[str, dict[str, int]]:
    items = list(cases or default_cases())
    by_locale: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for case in items:
        by_locale[case.locale] = by_locale.get(case.locale, 0) + 1
        by_kind[case.kind] = by_kind.get(case.kind, 0) + 1
    return {"total": {"all": len(items)}, "by_locale": by_locale, "by_kind": by_kind}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _is_protected(token: str) -> bool:
    return bool(
        _CODE_RE.fullmatch(token)
        or _FIELD_RE.fullmatch(token)
        or _NUMBER_RE.fullmatch(token)
    )


def _expand_token(token: str) -> str:
    match = re.match(r"^([^\w]*)(.*?)([^\w]*)$", token, re.UNICODE)
    if not match:
        return token
    prefix, core, suffix = match.groups()
    if not core or _is_protected(core):
        return token
    return f"{prefix}{_ABBREVIATIONS.get(core, core)}{suffix}"


def canonicalize(text: str) -> str:
    """Normaliza lenguaje natural sin tocar códigos, SKUs ni field names."""
    lowered = strip_accents(str(text or "")).lower()
    tokens = [_expand_token(token) for token in re.split(r"\s+", lowered.strip()) if token]
    return " ".join(tokens)


def build_language_state(case: LanguageCase, *, mode: str = MODE_RAW) -> dict[str, Any]:
    """Estado mínimo para el juicio: el texto en el modo pedido."""
    text = case.text if mode == MODE_RAW else canonicalize(case.text)
    return {
        "user_request": text[:2000],
        "language_mode": mode,
        "locale": case.locale,
        "kind": case.kind,
    }


def term_preservation(case: LanguageCase, *, mode: str) -> float:
    """Fracción de términos esperados que sobreviven al modo."""
    if not case.expected_terms:
        return 1.0
    rendered = strip_accents(
        case.text if mode == MODE_RAW else canonicalize(case.text)
    ).lower()
    hits = sum(1 for term in case.expected_terms if strip_accents(term).lower() in rendered)
    return round(hits / len(case.expected_terms), 4)


def deterministic_family(case: LanguageCase, *, mode: str) -> str | None:
    """Familia de capability por reglas (baseline sin JEV)."""
    state = build_language_state(case, mode=mode)
    text = state["user_request"]
    try:
        from src.agents.tools.sql_router import SqlIntentRouter
        from src.rag.adaptive.classifier import RulesClassifier

        sql_score = float(SqlIntentRouter.heuristic_score(text))
        classification = RulesClassifier().classify(text)
        if sql_score >= 0.8 and classification.kind != "lexical":
            return "database"
        if classification.kind == "lexical":
            return "knowledge"
        return "knowledge"
    except Exception:  # noqa: BLE001
        return None


def compare_language_modes(
    cases: Iterable[LanguageCase] | None = None,
) -> dict[str, Any]:
    """Evidencia raw vs canonical: no decide por sí sola, informa."""
    items = list(cases or default_cases())
    report: dict[str, Any] = {"modes": {}, "cases": len(items)}
    for mode in LANGUAGE_MODES:
        preservation = [term_preservation(case, mode=mode) for case in items]
        hits = 0
        labeled = 0
        chars = 0
        for case in items:
            chars += len(build_language_state(case, mode=mode)["user_request"])
            if case.expected_family:
                labeled += 1
                if deterministic_family(case, mode=mode) == case.expected_family:
                    hits += 1
        report["modes"][mode] = {
            "term_preservation": round(sum(preservation) / len(preservation), 4),
            "rules_family_accuracy": round(hits / labeled, 4) if labeled else None,
            "avg_state_chars": round(chars / len(items), 1),
        }
    report["decision"] = {
        "status": "sin_traduccion_obligatoria",
        "note": (
            "canonical gana sólo si mejora term_preservation y rules_family_accuracy "
            "sobre shadow; nunca se traduce el pedido del usuario a otro idioma."
        ),
    }
    return report
