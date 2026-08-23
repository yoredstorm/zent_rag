# =============================================================================
# MCP Server — backends (DI) — dependencias inyectables de las tools
# =============================================================================
# Las tools MCP nunca instancian infraestructura directamente: consumen los
# MISMOS singletons que la API REST (src/api/deps.py). En tests se puede
# inyectar un McpDeps con fakes sin tocar las tools.
# =============================================================================
from __future__ import annotations

from uuid import UUID


class McpDeps:
    """Accessors lazy de la composition root (src.api.deps)."""

    def retriever(self):
        from src.api.deps import get_retriever

        return get_retriever()

    def sql_expert(self):
        from src.api.deps import get_sql_expert

        return get_sql_expert()

    def vector_store(self):
        from src.api.deps import get_vector_store

        return get_vector_store()

    def embedding(self):
        from src.api.deps import get_embedding_provider

        return get_embedding_provider()

    def agent_runtime(self):
        from src.api.deps import get_agent_runtime

        return get_agent_runtime()

    def organization_repo(self):
        from src.api.deps import get_organization_repo

        return get_organization_repo()

    def agent_repo(self):
        from src.api.deps import get_agent_repo

        return get_agent_repo()

    def cache(self):
        from src.api.deps import get_cache_provider

        return get_cache_provider()

    async def organization_config(self, tenant_id: UUID) -> dict | None:
        """config_json del tenant (None si la organización no existe)."""
        org = await self.organization_repo().get_by_id(tenant_id)
        return org.config_json if org is not None else None
