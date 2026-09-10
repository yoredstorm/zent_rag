# =============================================================================
# Data Onboarding — Flow Profiles (producto por tipo de conocimiento)
# =============================================================================
# Cada flujo (database, documents, spreadsheets, drive, website, api) define
# su propio producto: fases de análisis, término de revisión, dimensiones de
# readiness, heading de preguntas y acciones de salida. La UI y los endpoints
# se comportan distinto por flow sin if/s generados a mano.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalyzePhase:
    key: str
    label: str


@dataclass(frozen=True)
class ReadyAction:
    label: str
    to: str


@dataclass(frozen=True)
class ReadinessDimension:
    key: str
    label: str


@dataclass(frozen=True)
class FlowProfile:
    kind: str
    title: str
    analyze_headline: str
    review_term: str
    analyze_phases: tuple[AnalyzePhase, ...]
    readiness_dimensions: tuple[ReadinessDimension, ...]
    ready_headline: str
    ready_subtitle: str
    ready_actions: tuple[ReadyAction, ...]
    questions_heading: str
    warning_template: str


_DEFAULT_ACTION = (
    ReadyAction("Pregúntale a Zent", "/chat"),
    ReadyAction("Crear agente", "/agents/new"),
    ReadyAction("Revisar mejoras", "/knowledge/improvements"),
)

_DATA_PHASES = (
    AnalyzePhase("connection", "Conexión verificada"),
    AnalyzePhase("structure", "Estructura descubierta"),
    AnalyzePhase("content", "Contenido analizado"),
    AnalyzePhase("meaning", "Significado de negocio"),
    AnalyzePhase("relationships", "Relaciones"),
    AnalyzePhase("quality", "Revisión de calidad"),
)

_DATA_DIMENSIONS = (
    ReadinessDimension("data_connected", "Datos conectados"),
    ReadinessDimension("structure_understood", "Estructura entendida"),
    ReadinessDimension("business_mappings", "Significado de negocio"),
    ReadinessDimension("relationships", "Relaciones"),
    ReadinessDimension("test_questions_passed", "Preguntas de prueba"),
)

_DOC_PHASES = (
    AnalyzePhase("connection", "Conexión verificada"),
    AnalyzePhase("structure", "Archivo recibido"),
    AnalyzePhase("content", "Texto extraído"),
    AnalyzePhase("facts", "Datos clave detectados"),
    AnalyzePhase("indexing", "Indexación"),
    AnalyzePhase("quality", "Revisión de calidad"),
)

_DOC_DIMENSIONS = (
    ReadinessDimension("content_extracted", "Contenido extraído"),
    ReadinessDimension("metadata", "Metadatos"),
    ReadinessDimension("key_facts", "Datos clave"),
    ReadinessDimension("indexing", "Indexación"),
    ReadinessDimension("test_questions", "Preguntas de prueba"),
)


def _data_flow(kind: str, title: str, review_term: str) -> FlowProfile:
    return FlowProfile(
        kind=kind,
        title=title,
        analyze_headline="Zent está entendiendo tus datos",
        review_term=review_term,
        analyze_phases=_DATA_PHASES,
        readiness_dimensions=_DATA_DIMENSIONS,
        ready_headline="Tu conocimiento está listo.",
        ready_subtitle="Fuentes conectadas, cobertura entendida y revisión pendiente.",
        ready_actions=_DEFAULT_ACTION,
        questions_heading="Prueba tus datos",
        warning_template=(
            "Zent encontró {n} {term} sin confirmar. Revísalos para respuestas más precisas."
        ),
    )


FLOWS: dict[str, FlowProfile] = {
    "database": _data_flow("database", "Base de datos", "mappings"),
    "spreadsheets": _data_flow("spreadsheets", "Hojas de cálculo", "campos"),
    "drive": _data_flow("drive", "Nube", "archivos"),
    "website": FlowProfile(
        kind="website",
        title="Sitio web",
        analyze_headline="Zent está analizando tu sitio",
        review_term="páginas",
        analyze_phases=_DATA_PHASES,
        readiness_dimensions=_DATA_DIMENSIONS,
        ready_headline="Tu sitio está listo.",
        ready_subtitle="Contenido del sitio entendido y preguntas respondidas.",
        ready_actions=_DEFAULT_ACTION,
        questions_heading="Prueba tu sitio",
        warning_template="Zent revisó {n} {term} sin confirmar.",
    ),
    "api": FlowProfile(
        kind="api",
        title="API",
        analyze_headline="Zent está analizando tu API",
        review_term="campos",
        analyze_phases=_DATA_PHASES,
        readiness_dimensions=_DATA_DIMENSIONS,
        ready_headline="Tu API está lista.",
        ready_subtitle="Endpoint conectado, campos entendidos y preguntas respondidas.",
        ready_actions=_DEFAULT_ACTION,
        questions_heading="Prueba tu API",
        warning_template="Zent detectó {n} {term} sin confirmar.",
    ),
    "documents": FlowProfile(
        kind="documents",
        title="Documentos",
        analyze_headline="Zent está leyendo tu documento",
        review_term="datos clave",
        analyze_phases=_DOC_PHASES,
        readiness_dimensions=_DOC_DIMENSIONS,
        ready_headline="Tu documento está listo.",
        ready_subtitle="Texto extraído, datos clave revisados y preguntas respondidas.",
        ready_actions=(
            ReadyAction("Pregúntale al documento", "/chat"),
            ReadyAction("Crear agente para contratos", "/agents/new"),
            ReadyAction("Añadir otro documento", "/knowledge/add"),
        ),
        questions_heading="Prueba el documento",
        warning_template=(
            "Zent extrajo {n} {term} sin confirmar. Revísalos para respuestas más precisas."
        ),
    ),
}


def get_flow(kind: str) -> FlowProfile:
    flow = FLOWS.get(kind)
    if flow is not None:
        return flow
    return _data_flow(kind, kind, "items")


def readiness_labels(flow: FlowProfile) -> dict[str, str]:
    return {d.key: d.label for d in flow.readiness_dimensions}
