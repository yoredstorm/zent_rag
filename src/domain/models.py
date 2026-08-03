# =============================================================================
# Domain Models — Pydantic Models para Validación de Entrada/Salida
# =============================================================================
# Cada request/response pasa validación estricta Pydantic antes de tocar
# la lógica de negocio. Esto mitiga inyección y garantiza integridad.
# =============================================================================
from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# -----------------------------------------------------------------------------
# Constantes de validación
# -----------------------------------------------------------------------------
TENANT_ID_PATTERN = re.compile(
    r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
)
PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"disregard\s+(prior|previous|all)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"forget\s+everything", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"<<\s*SYS\s*>>", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|an?\s+unfiltered)", re.IGNORECASE),
    re.compile(r"\[INST\].*\[/INST\]", re.IGNORECASE),  # Llama/Mistral jailbreak
]


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
        description="Override del modelo LLM. Si no se especifica, usa el default del tenant.",
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
