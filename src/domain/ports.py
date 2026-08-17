# =============================================================================
# Ports Layer — Interfaces Abstractas (ABCs) — Clean Architecture
# =============================================================================
# El dominio define QUÉ necesita, la infraestructura define CÓMO se hace.
# Cada adaptador (Postgres, Qdrant, LiteLLM, Redis) implementa uno de estos
# puertos. Así el dominio nunca depende de frameworks ni librerías externas.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID

from src.domain.entities import (
    ApiToken,
    LLMResponse,
    Plan,
    RAGQueryResult,
    RetrievalContext,
    Subscription,
    Tenant,
    User,
)


class TenantRepository(ABC):
    """Puerto para acceso a datos de Tenants (PostgreSQL)."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID) -> Tenant | None: ...

    @abstractmethod
    async def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None: ...

    @abstractmethod
    async def check_rate_limit(self, tenant_id: UUID) -> bool: ...

    @abstractmethod
    async def log_usage(
        self, tenant_id: UUID, user_id: UUID, tokens: int, latency_ms: float
    ) -> None: ...

    @abstractmethod
    async def create_tenant(
        self, tenant_id: UUID, name: str, api_key_hash: str
    ) -> Tenant: ...

    @abstractmethod
    async def update_tenant(
        self, tenant_id: UUID, **fields
    ) -> Tenant: ...

    @abstractmethod
    async def update_config(self, tenant_id: UUID, config: dict) -> Tenant: ...

    @abstractmethod
    async def list_tenants(self) -> list[Tenant]: ...


class UserRepository(ABC):
    """Puerto para acceso a datos de Usuarios (PostgreSQL)."""

    @abstractmethod
    async def get_by_id(self, user_id: UUID, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_external_id(
        self, tenant_id: UUID, external_id: str
    ) -> User | None: ...

    @abstractmethod
    async def get_any_user(self, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def create_default_user(
        self,
        tenant_id: UUID,
        email_hash: str,
        *,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> User: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def set_password(self, user_id: UUID, password_hash: str) -> None: ...


class VectorStore(ABC):
    """Puerto para búsqueda semántica (Qdrant)."""

    @abstractmethod
    async def search(
        self,
        tenant_id: UUID,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
    ) -> RetrievalContext: ...

    @abstractmethod
    async def upsert(
        self,
        tenant_id: UUID,
        document_id: UUID,
        embedding: list[float],
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> None: ...

    @abstractmethod
    async def upsert_batch(
        self,
        tenant_id: UUID,
        points: list[tuple[UUID, list[float], str, dict[str, str] | None]],
    ) -> None: ...

    @abstractmethod
    async def delete_by_tenant(self, tenant_id: UUID) -> None: ...


class LLMProvider(ABC):
    """Puerto para invocación de LLMs (LiteLLM)."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Genera una respuesta token a token.

        Yields:
            {"type": "delta", "text": str} por cada fragmento.
            {"type": "done", "content": str, "model": str, "usage": {...},
             "finish_reason": str, "latency_ms": float} al finalizar.
        """

    @abstractmethod
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]: ...


class EmbeddingProvider(ABC):
    """Puerto para generación de embeddings (LiteLLM o proveedor directo)."""

    @abstractmethod
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]: ...


class CacheProvider(ABC):
    """Puerto para caché (Redis)."""

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def append_to_list(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        """Agrega un item al final de una lista con TTL."""
        ...

    @abstractmethod
    async def get_list(self, key: str) -> list[str]:
        """Obtiene todos los items de una lista."""
        ...

    @abstractmethod
    async def trim_list(self, key: str, max_items: int) -> None:
        """Recorta la lista a max_items más recientes."""
        ...


class RAGQueryStore(ABC):
    """Puerto para persistencia de resultados de consultas (auditoría)."""

    @abstractmethod
    async def save(self, result: RAGQueryResult) -> None: ...

    @abstractmethod
    async def get_by_id(self, query_id: UUID, tenant_id: UUID) -> RAGQueryResult | None: ...


class BillingRepository(ABC):
    """Puerto para gestión de billing (planes, suscripciones, tokens, cuotas)."""

    @abstractmethod
    async def get_plan_by_id(self, plan_id: UUID) -> Plan | None: ...

    @abstractmethod
    async def get_plans(self, public_only: bool = True) -> list[Plan]: ...

    @abstractmethod
    async def get_subscription_by_tenant(self, tenant_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def get_subscription_by_id(self, subscription_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def create_subscription(
        self,
        tenant_id: UUID,
        plan_id: UUID,
        interval: str = "monthly",
        trial_days: int = 0,
    ) -> Subscription: ...

    @abstractmethod
    async def update_subscription_status(
        self, subscription_id: UUID, status: str
    ) -> None: ...

    @abstractmethod
    async def get_token_by_hash(self, token_hash: str) -> ApiToken | None: ...

    @abstractmethod
    async def get_token_by_subscription(
        self, subscription_id: UUID
    ) -> ApiToken | None: ...

    @abstractmethod
    async def create_token(
        self, subscription_id: UUID, token: str, name: str = "Default", scopes: list[str] | None = None
    ) -> ApiToken: ...

    @abstractmethod
    async def touch_token_last_used(self, token_id: UUID) -> None: ...

    @abstractmethod
    async def deactivate_token(self, token_id: UUID) -> None: ...

    @abstractmethod
    async def check_and_increment_quota(
        self, subscription_id: UUID, plan_requests_per_month: int
    ) -> bool: ...

    @abstractmethod
    async def get_quota_usage(self, subscription_id: UUID) -> tuple[int, int]: ...

    @abstractmethod
    async def list_subscriptions(self) -> list[dict]: ...

    @abstractmethod
    async def change_plan(self, subscription_id: UUID, plan_id: UUID) -> Subscription: ...

    @abstractmethod
    async def delete_subscription(self, subscription_id: UUID) -> None: ...
