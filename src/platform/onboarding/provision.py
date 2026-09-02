from __future__ import annotations

# =============================================================================
# Onboarding & Tenancy Self-Serve
# Provisioning de tenant en 1 clic, migración entre tenants, trial extendido.
# =============================================================================
import json
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def provision_tenant(
    company_name: str,
    email: str,
    plan_name: str = "trial",
    with_demo: bool = False,
    sso_issuer: str | None = None,
    sso_client_id: str | None = None,
    sso_client_secret: str | None = None,
) -> dict:
    """Crea org + owner + suscripción + API key (+ demo + SSO opcional)."""
    from src.infrastructure.postgres.relational_db import (
        PostgresAgentRepository,
        PostgresApiKeyRepository,
        PostgresBillingRepository,
        PostgresMembershipRepository,
        PostgresOrganizationRepository,
        PostgresUserRepository,
    )
    from src.platform.billing.service import BillingService

    org_repo = PostgresOrganizationRepository()
    org_id = uuid4()
    await org_repo.create_organization(org_id, company_name)

    # Owner (JIT, sin password).
    user_repo = PostgresUserRepository()
    user_id = await user_repo.create_sso_user(
        org_id, email.strip().lower(), external_id="default-admin"
    )
    await PostgresMembershipRepository().assign_role(org_id, user_id, "owner")

    # Suscripción trial + API key.
    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    subscription, token = await billing.create_trial_subscription(org_id)

    # Plan distinto de trial → upgrade automático.
    if plan_name and plan_name != "trial":
        await billing.upgrade_plan(subscription.id, plan_name, "monthly")

    demo_kb = None
    demo_agent = None
    if with_demo:
        session = await get_async_session()
        try:
            kb_id = uuid4()
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases (id, organization_id, name, description, "
                    "status, embedding_model, chunking_strategy, retrieval_strategy) "
                    "VALUES (:id, :oid, 'Demo KB', 'Contenido de ejemplo', 'active', "
                    "'default', 'smart', 'hybrid')"
                ),
                {"id": kb_id, "oid": org_id},
            )
            demo_kb = str(kb_id)
            await session.commit()
        finally:
            await session.close()
        demo_agent = await PostgresAgentRepository().create_agent(
            org_id,
            name="Demo Agent",
            description="Agente de demostración",
            system_prompt=(
                "Eres el asistente de demostración. Responde usando la knowledge "
                "base Demo KB cuando corresponda."
            ),
            tools=[],
            model="gpt-4o-mini",
            config_json={"temperature": 0.3},
        )

    # SSO opcional.
    if sso_issuer and sso_client_id:
        from src.platform.enterprise.sso import save_sso_config

        await save_sso_config(
            org_id,
            enabled=True,
            issuer=sso_issuer,
            client_id=sso_client_id,
            client_secret=sso_client_secret or "placeholder-change-me",
        )

    return {
        "status": "provisioned",
        "organization_id": str(org_id),
        "owner_user_id": str(user_id),
        "plan": plan_name or "trial",
        "subscription_id": str(subscription.id),
        "api_token": token,
        "demo_kb_id": demo_kb,
        "demo_agent_id": str(demo_agent.id) if demo_agent else None,
    }


async def migrate_tenant(
    source_organization_id: UUID,
    target_organization_id: UUID,
    migrate_kbs: bool = True,
    migrate_agents: bool = True,
) -> dict:
    """Copia KBs (metadatos) y agentes del tenant origen al destino."""
    session = await get_async_session()
    try:
        target_exists = (
            await session.execute(
                text("SELECT 1 FROM organizations WHERE id = :oid"),
                {"oid": target_organization_id},
            )
        ).fetchone()
        if target_exists is None:
            return {"status": "target_not_found"}
        migrated_kbs = 0
        if migrate_kbs:
            existing = {
                r.name
                for r in (
                    await session.execute(
                        text(
                            "SELECT name FROM knowledge_bases WHERE organization_id = :oid"
                        ),
                        {"oid": target_organization_id},
                    )
                ).fetchall()
            }
            kbs = (
                await session.execute(
                    text(
                        "SELECT name, description, embedding_model, chunking_strategy, "
                        "chunk_size, chunk_overlap, retrieval_strategy, reranker, "
                        "metadata_schema, config_json FROM knowledge_bases "
                        "WHERE organization_id = :oid"
                    ),
                    {"oid": source_organization_id},
                )
            ).fetchall()
            for kb in kbs:
                name = kb.name
                if name in existing:
                    name = f"{name} (migrada)"
                existing.add(name)
                await session.execute(
                    text(
                        "INSERT INTO knowledge_bases (id, organization_id, name, "
                        "description, status, embedding_model, chunking_strategy, "
                        "chunk_size, chunk_overlap, retrieval_strategy, reranker, "
                        "metadata_schema, config_json) "
                        "VALUES (gen_random_uuid(), :oid, :name, :desc, 'active', "
                        ":emb, :chunk, :chunk_size, :chunk_overlap, :retr, :rerank, "
                        ":meta, :cfg)"
                    ),
                    {
                        "oid": target_organization_id,
                        "name": name,
                        "desc": kb.description,
                        "emb": kb.embedding_model,
                        "chunk": kb.chunking_strategy,
                        "chunk_size": kb.chunk_size,
                        "chunk_overlap": kb.chunk_overlap,
                        "retr": kb.retrieval_strategy,
                        "rerank": kb.reranker,
                        "meta": json.dumps(kb.metadata_schema) if kb.metadata_schema else "{}",
                        "cfg": json.dumps(kb.config_json) if kb.config_json else "{}",
                    },
                )
                migrated_kbs += 1
        migrated_agents = 0
        if migrate_agents:
            agents = (
                await session.execute(
                    text(
                        "SELECT name, description, system_prompt, tools, model, "
                        "config_json FROM agents WHERE organization_id = :oid "
                        "AND is_active = true"
                    ),
                    {"oid": source_organization_id},
                )
            ).fetchall()
            from src.infrastructure.postgres.relational_db import PostgresAgentRepository

            repo = PostgresAgentRepository()
            for agent in agents:
                await repo.create_agent(
                    target_organization_id,
                    name=f"{agent.name} (migrado)",
                    description=agent.description,
                    system_prompt=agent.system_prompt,
                    tools=list(agent.tools or []),
                    model=agent.model,
                    config_json=agent.config_json or {},
                )
                migrated_agents += 1
        await session.commit()
    finally:
        await session.close()
    return {
        "status": "migrated",
        "knowledge_bases": migrated_kbs,
        "agents": migrated_agents,
        "note": "KBs copiadas sin contenido (re-ingest en el destino).",
    }


async def extend_trial(organization_id: UUID, days: int) -> dict:
    """Extiende el trial auto-aprobado (plataforma)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE subscriptions SET trial_end = trial_end + "
                    "MAKE_INTERVAL(days => :days) "
                    "WHERE organization_id = :oid AND status = 'trialing' "
                    "RETURNING trial_end"
                ),
                {"days": days, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            return {"status": "not_trialing"}
        await session.commit()
        from src.platform.governance.governance import record_compliance_event

        await record_compliance_event(
            organization_id,
            "trial.extended",
            metadata={"days": days},
        )
    finally:
        await session.close()
    return {"status": "extended", "trial_end": row.trial_end.isoformat(), "days": days}
