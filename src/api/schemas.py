# =============================================================================
# API Schemas — DTOs HTTP (request/response) con validación Pydantic
# =============================================================================
# Separados del core/domain: los DTOs son una preocupación del transporte.
# =============================================================================
from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.agents.policies.authorization import PROMPT_INJECTION_PATTERNS
from src.core.domain.entities import RAGQueryResult

# -----------------------------------------------------------------------------
# Constantes de validación
# -----------------------------------------------------------------------------
ORGANIZATION_ID_PATTERN = re.compile(
    r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
)


# -----------------------------------------------------------------------------
# Request Models
# -----------------------------------------------------------------------------
class RAGQueryRequest(BaseModel):
    """Petición de consulta RAG con validación anti-Prompt Injection."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",  # Rechaza campos no declarados
    )

    query: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=32000,
            strip_whitespace=True,
            pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",  # Sin caracteres de control (evita null bytes)
        ),
    ] = Field(
        ...,
        description="Texto de la consulta del usuario (max 32k chars).",
        examples=["¿Cuál es la política de vacaciones para empleados remotos?"],
    )

    max_tokens: int = Field(
        default=2048,
        ge=1,
        le=100_000,
        description="Máximo de tokens en la respuesta del LLM.",
    )

    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Temperatura del modelo LLM (0=determinista, 1=creativo).",
    )

    model: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_\-./]+$",
        description="Override del modelo LLM. Si no se especifica, usa el default del organization.",
    )

    top_k: int = Field(
        default=200,
        ge=1,
        le=500,
        description="Número de chunks de contexto a recuperar de la BD vectorial.",
    )

    conversation_id: UUID | None = Field(
        default=None,
        description="ID de conversación para mantener contexto multi-turno.",
    )

    role: Literal["admin", "customer"] = Field(
        default="admin",
        description="Rol del usuario. Afecta visibilidad de datos y permisos SQL.",
    )

    metadata_filters: dict[str, str] | None = Field(
        default=None,
        description=(
            "Filtros de metadata del motor de retrieval "
            "(ej: metadata.source, metadata.doc_type, metadata.language)."
        ),
    )

    rerank_top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Override del top N del reranker.",
    )

    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override del umbral mínimo de score del retrieval.",
    )

    retrieval_strategy: Literal["vector", "lexical", "hybrid"] | None = Field(
        default=None,
        description="Override de la estrategia de retrieval del tenant.",
    )

    language: str | None = Field(
        default=None,
        max_length=10,
        pattern=r"^[a-z]{2,5}(-[A-Z]{2})?$",
        description="Idioma de la consulta para filtros (ej: es, en).",
    )

    @model_validator(mode="after")
    def detect_prompt_injection(self) -> "RAGQueryRequest":
        """Escanea la consulta en búsqueda de patrones de Prompt Injection.

        No bloquea la request por defecto (podría afectar UX legítima),
        pero registra una advertencia de seguridad para auditoría.
        """
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(self.query):
                # La advertencia se captura en el log estructurado del middleware.
                # No lanzamos excepción para evitar falsos positivos que bloqueen a usuarios.
                self.__dict__["_prompt_injection_warning"] = True
                break
        return self

    @property
    def has_injection_warning(self) -> bool:
        return self.__dict__.get("_prompt_injection_warning", False)


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------
class RetrievalChunkResponse(BaseModel):
    """Fragmento de documento recuperado (expuesto en API)."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    content: str
    score: float
    image_base64: str | None = None
    metadata: dict[str, str] | None = None


def sources_for_client(result: RAGQueryResult) -> list[RetrievalChunkResponse]:
    """Vector chunks are document provenance; SQL-first answers must not show them."""
    if result.method == "sql" or not result.retrieval_context:
        return []
    return [
        RetrievalChunkResponse(
            document_id=chunk.document_id,
            content=chunk.content[:500],
            score=chunk.score,
            image_base64=chunk.metadata.get("image_base64") if chunk.metadata else None,
            metadata={
                key: str(value)
                for key, value in (chunk.metadata or {}).items()
                if key != "image_base64"
            }
            or None,
        )
        for chunk in result.retrieval_context.chunks
    ]


class RAGQueryResponse(BaseModel):
    """Respuesta de la API RAG para el cliente."""

    model_config = ConfigDict(extra="forbid")

    query_id: UUID
    conversation_id: UUID | None = None
    role: str = "admin"
    status: str
    answer: str
    sources: list[RetrievalChunkResponse] = Field(default_factory=list)
    model: str
    usage: dict[str, int]  # {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
    latency_ms: float
    method: str = "rag"  # "sql" = SQL-first, "rag" = vector-only
    sql_query: str | None = None  # admin-only when method == "sql"
    lazy_ingested: bool = False


class ErrorResponse(BaseModel):
    """Respuesta de error estandarizada."""

    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    query_id: UUID | None = None
    details: dict[str, str] | None = None


# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "0.1.0"
    environment: str
    checks: dict[str, str] | None = None
