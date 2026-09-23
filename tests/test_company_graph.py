# =============================================================================
# Company Intelligence Graph — dominio puro + Postgres + tenant isolation.
# Tablas en la migración 129. Sin conclusiones LLM: el grafo devuelve hechos
# verificables (entidades, relaciones, evidencia, vigencia, autoridad).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.company.service import (
    NEVER_AUTO_CONFIRM,
    CompanyAuthorityService,
    CompanyGraphService,
    is_structurally_verifiable,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    ProvenanceKind,
    ProvenanceRef,
    RelationshipRegistry,
    SourceAuthorityLevel,
    assert_status_transition,
    company_entity_uuid,
    is_current,
    normalize_entity_type,
    normalize_relationship_type,
)
from src.core.ports.company_graph import (
    GraphTraversalLimits,
    RelationshipFilter,
)
from src.infrastructure.postgres.company_graph import (
    PostgresCompanyGraphRepository,
    filter_current_relationships,
)

ORG_A = uuid4()
ORG_B = uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _entity(org, name: str, etype: str = "concept", **over) -> CompanyEntity:
    payload = {
        "organization_id": org,
        "entity_type": etype,
        "canonical_name": name,
        "display_name": name.title(),
    }
    payload.update(over)
    return CompanyEntity(**payload)


def _proof(kind: ProvenanceKind = ProvenanceKind.MANUAL) -> ProvenanceRef:
    return ProvenanceRef(kind=kind, ref=f"ref-{uuid4().hex[:8]}")


# ---------------------------------------------------------------------------
# Dominio puro
# ---------------------------------------------------------------------------


def test_entity_id_is_deterministic_per_org_type_name() -> None:
    a = _entity(ORG_A, "pending transaction")
    b = _entity(ORG_A, "Pending Transaction")
    assert a.id == b.id
    assert a.id == company_entity_uuid(ORG_A, "concept", "pending transaction")
    assert _entity(ORG_B, "pending transaction").id != a.id
    assert _entity(ORG_A, "pending transaction", etype="process").id != a.id


def test_entity_type_is_extensible_without_enum_change() -> None:
    custom = _entity(ORG_A, "x", etype="  Custom_Thing ")
    assert custom.entity_type == "custom_thing"
    with pytest.raises(ValueError):
        _entity(ORG_A, "x", etype="   ")
    with pytest.raises(ValueError):
        normalize_entity_type("t" * 65)


def test_relationship_registry_accepts_custom_types() -> None:
    assert normalize_relationship_type("maps_to") == "MAPS_TO"
    assert RelationshipRegistry.normalize("applies_to") == "APPLIES_TO"
    assert "BELONGS_TO" in RelationshipRegistry.all()
    RelationshipRegistry.register("concerns")
    assert RelationshipRegistry.is_known("CONCERNS")
    assert not RelationshipRegistry.is_known("not a type!!")
    with pytest.raises(ValueError):
        normalize_relationship_type("")


def test_status_transitions_follow_the_law() -> None:
    assert_status_transition(EntityStatus.DISCOVERED, EntityStatus.SUPPORTED)
    assert_status_transition(EntityStatus.SUPPORTED, EntityStatus.CONFIRMED)
    assert_status_transition(EntityStatus.CONFIRMED, EntityStatus.DEPRECATED)
    assert_status_transition(EntityStatus.STALE, EntityStatus.DISCOVERED)
    # Verificación estructural: el schema puede auto-confirmar lo que descubre.
    assert_status_transition(EntityStatus.DISCOVERED, EntityStatus.AUTO_CONFIRMED)
    assert_status_transition(EntityStatus.SUPPORTED, EntityStatus.AUTO_CONFIRMED)
    with pytest.raises(ValueError):
        assert_status_transition(EntityStatus.STALE, EntityStatus.AUTO_CONFIRMED)
    with pytest.raises(ValueError):
        assert_status_transition(EntityStatus.DEPRECATED, EntityStatus.DISCOVERED)
    with pytest.raises(ValueError):
        assert_status_transition(EntityStatus.REJECTED, EntityStatus.SUPPORTED)
    assert not is_current(EntityStatus.DEPRECATED, None, None)
    assert not is_current(EntityStatus.REJECTED, None, None)
    assert is_current(EntityStatus.DISCOVERED, None, None)


def test_structural_auto_confirm_is_closed_by_design() -> None:
    assert is_structurally_verifiable("table", "CONTAINS", "field")
    assert is_structurally_verifiable("database", "contains", "table")
    # LLM infiere semántica: jamás auto-confirmable aunque el par exista.
    assert not is_structurally_verifiable("field", "MAPS_TO", "concept")
    assert not is_structurally_verifiable("table", "CONTAINS", "concept")
    assert "MAPS_TO" in NEVER_AUTO_CONFIRM
    assert "DESCRIBES" in NEVER_AUTO_CONFIRM


def test_provenance_never_stores_chain_of_thought() -> None:
    proof = _proof(ProvenanceKind.CLAIM)
    assert proof.to_dict() == {"kind": "claim", "ref": proof.ref}
    assert ProvenanceRef.from_dict(proof.to_dict()) == proof
    with pytest.raises(ValueError):
        ProvenanceRef(kind=ProvenanceKind.MANUAL, ref="  ")


def test_traversal_limits_reject_unbounded_queries() -> None:
    with pytest.raises(ValueError):
        GraphTraversalLimits(max_depth=0)
    with pytest.raises(ValueError):
        GraphTraversalLimits(max_depth=11)
    with pytest.raises(ValueError):
        GraphTraversalLimits(max_nodes=0)
    assert GraphTraversalLimits().max_depth == 4


def test_current_view_excludes_deprecated_and_expired() -> None:
    now = _utcnow()
    rels = [
        CompanyRelationship(
            organization_id=ORG_A,
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relationship_type="USES",
        ),
        CompanyRelationship(
            organization_id=ORG_A,
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relationship_type="USES",
            status=EntityStatus.DEPRECATED,
        ),
        CompanyRelationship(
            organization_id=ORG_A,
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relationship_type="USES",
            valid_from=now - timedelta(days=10),
            valid_to=now - timedelta(days=1),
        ),
    ]
    current = filter_current_relationships(rels, as_of=now)
    assert len(current) == 1
    assert current[0].status is EntityStatus.DISCOVERED


# ---------------------------------------------------------------------------
# Postgres (migración 129)
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Company Org {uuid4().hex[:6]}")


@pytest.fixture
def repo():
    return PostgresCompanyGraphRepository()


@pytest.fixture
def service(repo):
    return CompanyGraphService(repo)


@pytest.mark.asyncio
async def test_entity_upsert_is_idempotent_and_tenant_scoped(org, repo) -> None:
    first = await repo.upsert_entity(_entity(org.id, "pending transaction"))
    second = await repo.upsert_entity(
        _entity(org.id, "Pending Transaction", description="upd")
    )
    assert first.id == second.id
    assert second.description == "upd"

    assert await repo.get_entity(org.id, first.id) is not None
    assert await repo.get_entity(uuid4(), first.id) is None

    found = await repo.find_entities(org.id, query="pending")
    assert [e.id for e in found] == [first.id]
    assert await repo.find_entities(uuid4(), query="pending") == []


@pytest.mark.asyncio
async def test_relationship_propose_confirm_deprecate(org, repo) -> None:
    a = await repo.upsert_entity(_entity(org.id, "concept a"))
    b = await repo.upsert_entity(_entity(org.id, "table t", etype="table"))

    rel = CompanyRelationship(
        organization_id=org.id,
        from_entity_id=a.id,
        to_entity_id=b.id,
        relationship_type="maps_to",
        source="manual",
        evidence_refs=(_proof(),),
    )
    saved = await repo.propose_relationship(rel)
    assert saved.relationship_type == "MAPS_TO"
    assert saved.status is EntityStatus.DISCOVERED

    confirmed = await repo.confirm_relationship(
        org.id, saved.id, status=EntityStatus.CONFIRMED
    )
    assert confirmed.status is EntityStatus.CONFIRMED

    with pytest.raises(ValueError):
        await repo.confirm_relationship(
            org.id, saved.id, status=EntityStatus.DISCOVERED
        )

    deprecated = await repo.deprecate_relationship(org.id, saved.id)
    assert deprecated.status is EntityStatus.DEPRECATED

    current = await repo.find_relationships(org.id, current_only=True)
    assert all(r.id != saved.id for r in current)
    history = await repo.entity_history(org.id, a.id)
    assert any(r.id == saved.id for r in history)


@pytest.mark.asyncio
async def test_relationship_rejects_cross_tenant_endpoints(org, repo) -> None:
    mine = await repo.upsert_entity(_entity(org.id, "mine"))
    other_org = uuid4()
    with pytest.raises(ValueError):
        await repo.propose_relationship(
            CompanyRelationship(
                organization_id=other_org,
                from_entity_id=mine.id,
                to_entity_id=uuid4(),
                relationship_type="USES",
            )
        )
    with pytest.raises(ValueError):
        await repo.confirm_relationship(other_org, uuid4(), status=EntityStatus.CONFIRMED)


@pytest.mark.asyncio
async def test_temporal_relationships_valid_at_date(org, repo) -> None:
    now = _utcnow()
    a = await repo.upsert_entity(_entity(org.id, "process p", etype="process"))
    b = await repo.upsert_entity(_entity(org.id, "system s", etype="system"))
    old = await repo.propose_relationship(
        CompanyRelationship(
            organization_id=org.id,
            from_entity_id=a.id,
            to_entity_id=b.id,
            relationship_type="USES",
            valid_from=now - timedelta(days=60),
            valid_to=now - timedelta(days=30),
        )
    )
    new = await repo.propose_relationship(
        CompanyRelationship(
            organization_id=org.id,
            from_entity_id=a.id,
            to_entity_id=b.id,
            relationship_type="USES",
            valid_from=now - timedelta(days=5),
        )
    )
    as_past = await repo.find_relationships(
        org.id, as_of=now - timedelta(days=45), current_only=False
    )
    assert {r.id for r in as_past} == {old.id}
    as_now = await repo.find_relationships(org.id, as_of=now)
    assert {r.id for r in as_now} == {new.id}


@pytest.mark.asyncio
async def test_traversal_respects_max_depth_handles_cycles(org, repo) -> None:
    nodes = [await repo.upsert_entity(_entity(org.id, f"n{i}")) for i in range(5)]
    for i in range(4):
        await repo.propose_relationship(
            CompanyRelationship(
                organization_id=org.id,
                from_entity_id=nodes[i].id,
                to_entity_id=nodes[i + 1].id,
                relationship_type="CONNECTS_TO",
            )
        )
    await repo.propose_relationship(
        CompanyRelationship(
            organization_id=org.id,
            from_entity_id=nodes[4].id,
            to_entity_id=nodes[0].id,
            relationship_type="CONNECTS_TO",
        )
    )
    shallow = await repo.traverse(
        org.id,
        nodes[0].id,
        direction="out",
        limits=GraphTraversalLimits(max_depth=2),
    )
    assert {e.id for e in shallow.entities} == {n.id for n in nodes[:3]}

    full = await repo.traverse(
        org.id,
        nodes[0].id,
        direction="out",
        limits=GraphTraversalLimits(max_depth=6),
    )
    assert {e.id for e in full.entities} == {n.id for n in nodes}


@pytest.mark.asyncio
async def test_path_search_and_impact(org, repo) -> None:
    sale = await repo.upsert_entity(_entity(org.id, "sale", etype="event"))
    proc = await repo.upsert_entity(_entity(org.id, "billing", etype="process"))
    wf = await repo.upsert_entity(_entity(org.id, "invoice-wf", etype="workflow"))
    agent = await repo.upsert_entity(_entity(org.id, "collector", etype="agent"))
    for frm, to, rtype in [
        (sale, proc, "TRIGGERS"),
        (proc, wf, "AUTOMATES"),
        (wf, agent, "ASSISTS"),
    ]:
        await repo.propose_relationship(
            CompanyRelationship(
                organization_id=org.id,
                from_entity_id=frm.id,
                to_entity_id=to.id,
                relationship_type=rtype,
            )
        )
    path = await repo.find_path(org.id, sale.id, agent.id)
    assert path is not None
    assert [e.id for e in path.entities] == [sale.id, proc.id, wf.id, agent.id]
    assert [r.relationship_type for r in path.relationships] == [
        "TRIGGERS",
        "AUTOMATES",
        "ASSISTS",
    ]
    assert await repo.find_path(org.id, agent.id, uuid4()) is None

    impact = await repo.impact_analysis(org.id, proc.id)
    assert impact.root is not None and impact.root.id == proc.id
    assert impact.by_type.get("workflow") == 1
    assert impact.by_type.get("agent") == 1
    assert {e.id for e in impact.entities} >= {sale.id, wf.id, agent.id}


@pytest.mark.asyncio
async def test_no_multi_hop_cross_tenant_leakage(org, repo) -> None:
    mine = await repo.upsert_entity(_entity(org.id, "mine"))
    mid = await repo.upsert_entity(_entity(org.id, "mid"))
    await repo.propose_relationship(
        CompanyRelationship(
            organization_id=org.id,
            from_entity_id=mine.id,
            to_entity_id=mid.id,
            relationship_type="USES",
        )
    )
    stranger = uuid4()
    hood = await repo.neighbors(stranger, mine.id)
    assert hood.entities == () and hood.relationships == ()
    walked = await repo.traverse(stranger, mine.id)
    assert walked.entities == () and walked.relationships == ()
    leaked = await repo.impact_analysis(stranger, mine.id)
    assert leaked.root is None and leaked.entities == ()


@pytest.mark.asyncio
async def test_service_auto_confirm_structural_only(org, service) -> None:
    table = await service.upsert_entity(_entity(org.id, "pxsaudit.a1672", etype="table"))
    field_e = await service.upsert_entity(_entity(org.id, "a1672sto0", etype="field"))
    structural = await service.propose_relationship(
        org.id,
        table.id,
        field_e.id,
        "CONTAINS",
        source="schema",
        auto_confirm_structural=True,
    )
    assert structural.status is EntityStatus.AUTO_CONFIRMED

    concept = await service.upsert_entity(_entity(org.id, "pending transaction"))
    semantic = await service.propose_relationship(
        org.id,
        field_e.id,
        concept.id,
        "MAPS_TO",
        source="llm",
        auto_confirm_structural=True,
    )
    assert semantic.status is EntityStatus.DISCOVERED

    with pytest.raises(ValueError):
        await service.confirm_relationship(
            org.id, semantic.id, status=EntityStatus.AUTO_CONFIRMED
        )
    supported = await service.confirm_relationship(
        org.id, semantic.id, status=EntityStatus.SUPPORTED
    )
    assert supported.status is EntityStatus.SUPPORTED


@pytest.mark.asyncio
async def test_service_explain_and_concept_mappings(org, service) -> None:
    concept = await service.upsert_entity(
        _entity(
            org.id,
            "pending transaction",
            aliases=["pending", "pendiente"],
            source="manual",
            source_ref="admin",
            evidence=(_proof(ProvenanceKind.DOCUMENT),),
            confidence=0.8,
        )
    )
    table = await service.upsert_entity(_entity(org.id, "pxsaudit.a1672", etype="table"))
    field_e = await service.upsert_entity(_entity(org.id, "a1672sto0", etype="field"))
    for target in (table, field_e):
        await service.propose_relationship(
            org.id, concept.id, target.id, "MAPS_TO", source="manual"
        )
    explanation = await service.explain(org.id, concept.id)
    assert explanation["source"] == "manual"
    assert explanation["evidence"][0]["kind"] == "document"
    assert explanation["confidence"] == 0.8

    mappings = await service.concept_mappings(org.id, concept.id)
    assert {r.to_entity_id for r in mappings} == {table.id, field_e.id}


@pytest.mark.asyncio
async def test_learning_graph_reuses_memory_and_learning_entities(org, service) -> None:
    """§16/§17: Memory y Learning se referencian, no se duplican."""
    dataset = await service.upsert_entity(_entity(org.id, "orders", etype="dataset"))
    process = await service.upsert_entity(_entity(org.id, "billing", etype="process"))
    memory = await service.upsert_entity(
        _entity(
            org.id,
            "memory:pattern:sql-orders",
            etype="memory",
            evidence=(_proof(ProvenanceKind.MEMORY),),
        )
    )
    experiment = await service.upsert_entity(
        _entity(
            org.id,
            "experiment:top-k-12",
            etype="experiment",
            evidence=(_proof(ProvenanceKind.EXPERIMENT),),
        )
    )
    finding = await service.upsert_entity(_entity(org.id, "finding:stale-index", etype="finding"))

    for frm, to, rtype in [
        (memory, dataset, "CONCERNS"),
        (memory, process, "IMPROVES"),
        (experiment, memory, "VALIDATES"),
        (finding, dataset, "AFFECTS"),
    ]:
        rel = await service.propose_relationship(
            org.id, frm.id, to.id, rtype, source="learning_engine"
        )
        assert rel.status is EntityStatus.DISCOVERED

    concerns = await service.find_relationships(
        org.id, from_entity_id=memory.id, relationship_types=("CONCERNS",)
    )
    assert [r.to_entity_id for r in concerns] == [dataset.id]
    validated = await service.find_relationships(
        org.id, to_entity_id=memory.id, relationship_types=("VALIDATES",)
    )
    assert [r.from_entity_id for r in validated] == [experiment.id]

    hood = await service.neighbors(org.id, memory.id)
    assert {e.id for e in hood.entities} == {dataset.id, process.id, experiment.id}


@pytest.mark.asyncio
async def test_source_authority_is_per_tenant_and_domain(org) -> None:
    from src.company.service import AuthorityRule

    svc = CompanyAuthorityService()
    await svc.upsert_rule(
        AuthorityRule(
            organization_id=org.id,
            domain="policy",
            concept="refund",
            source_name="official-docs",
            source_type="document",
            authority_level=SourceAuthorityLevel.AUTHORITATIVE,
            priority=1,
        )
    )
    await svc.upsert_rule(
        AuthorityRule(
            organization_id=org.id,
            domain="sales",
            concept="refund",
            source_name="prod-db",
            source_type="database",
            authority_level=SourceAuthorityLevel.AUTHORITATIVE,
            priority=1,
        )
    )
    level = await svc.resolve_authority(
        org.id, domain="policy", concept="refund", source_name="official-docs"
    )
    assert level is SourceAuthorityLevel.AUTHORITATIVE
    other_domain = await svc.resolve_authority(
        org.id, domain="policy", concept="refund", source_name="prod-db"
    )
    assert other_domain is SourceAuthorityLevel.INFORMATIONAL
    sales = await svc.resolve_authority(
        org.id, domain="sales", concept="refund", source_name="prod-db"
    )
    assert sales is SourceAuthorityLevel.AUTHORITATIVE

    stranger_rules = await svc.list_rules(uuid4())
    assert stranger_rules == []
    assert await svc.resolve_authority(
        uuid4(), domain="policy", concept="refund", source_name="official-docs"
    ) is SourceAuthorityLevel.INFORMATIONAL


@pytest.mark.asyncio
async def test_confirmed_vs_discovered_filtering(org, repo) -> None:
    a = await repo.upsert_entity(_entity(org.id, "a"))
    b = await repo.upsert_entity(_entity(org.id, "b"))
    rel = await repo.propose_relationship(
        CompanyRelationship(
            organization_id=org.id,
            from_entity_id=a.id,
            to_entity_id=b.id,
            relationship_type="SUPPORTS",
        )
    )
    flt = RelationshipFilter(
        relationship_types=("SUPPORTS",),
        statuses=(EntityStatus.CONFIRMED,),
        current_only=False,
    )
    assert flt.relationship_types == ("SUPPORTS",)
    assert await repo.find_relationships(
        org.id,
        relationship_types=flt.relationship_types,
        statuses=flt.statuses,
        current_only=flt.current_only,
    ) == []
    await repo.confirm_relationship(org.id, rel.id, status=EntityStatus.CONFIRMED)
    confirmed = await repo.find_relationships(
        org.id,
        relationship_types=("SUPPORTS",),
        statuses=(EntityStatus.CONFIRMED,),
        current_only=False,
    )
    assert [r.id for r in confirmed] == [rel.id]


# ---------------------------------------------------------------------------
# API (tenant scoped, paginada)
# ---------------------------------------------------------------------------


async def _create_org(client, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"cg-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


@pytest.fixture
async def api_client():
    from httpx import ASGITransport, AsyncClient

    from src.api.main import app
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def api_orgs(api_client):
    orgs = []
    for label in ("CG Org A", "CG Org B"):
        org = await _create_org(api_client, label)
        org["session"] = await _owner_session(org["organization_id"])
        orgs.append(org)
    return orgs


@pytest.mark.asyncio
async def test_api_entity_relationship_flow_and_cross_tenant(api_client, api_orgs) -> None:
    org_a, org_b = api_orgs
    created = await api_client.post(
        "/api/v1/company-graph/entities",
        headers=_headers(org_a),
        json={
            "entity_type": "concept",
            "canonical_name": "pending transaction",
            "aliases": ["pendiente"],
            "source": "manual",
            "evidence": [{"kind": "manual", "ref": "admin-1"}],
            "confidence": 0.7,
        },
    )
    assert created.status_code == 201, created.text
    concept = created.json()
    assert concept["aliases"] == ["pendiente"]
    assert concept["status"] == "discovered"

    field_entity = await api_client.post(
        "/api/v1/company-graph/entities",
        headers=_headers(org_a),
        json={"entity_type": "field", "canonical_name": "a1672sto0"},
    )
    assert field_entity.status_code == 201, field_entity.text
    field_id = field_entity.json()["id"]

    rel = await api_client.post(
        "/api/v1/company-graph/relationships",
        headers=_headers(org_a),
        json={
            "from_entity_id": concept["id"],
            "to_entity_id": field_id,
            "relationship_type": "maps_to",
            "source": "manual",
            "auto_confirm_structural": True,
        },
    )
    assert rel.status_code == 201, rel.text
    rel_body = rel.json()
    assert rel_body["relationship_type"] == "MAPS_TO"
    # Semántico: nunca auto-confirmado aunque se pida.
    assert rel_body["status"] == "discovered"

    listed = await api_client.get(
        "/api/v1/company-graph/entities",
        headers=_headers(org_a),
        params={"q": "pending", "limit": 10, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["limit"] == 10 and body["offset"] == 0
    assert [e["id"] for e in body["items"]] == [concept["id"]]

    # Aislamiento: el otro tenant no ve nada del primero.
    other = await api_client.get(
        "/api/v1/company-graph/entities", headers=_headers(org_b)
    )
    assert other.status_code == 200
    assert other.json()["items"] == []
    cross = await api_client.get(
        f"/api/v1/company-graph/entities/{concept['id']}", headers=_headers(org_b)
    )
    assert cross.status_code == 404
    traversal = await api_client.get(
        f"/api/v1/company-graph/entities/{concept['id']}/impact",
        headers=_headers(org_b),
    )
    assert traversal.status_code == 200
    assert traversal.json()["entities"] == []
    assert traversal.json()["root"] is None


@pytest.mark.asyncio
async def test_api_status_transition_and_deprecated_view(api_client, api_orgs) -> None:
    org_a, _ = api_orgs
    async def _entity(name: str, etype: str) -> str:
        response = await api_client.post(
            "/api/v1/company-graph/entities",
            headers=_headers(org_a),
            json={"entity_type": etype, "canonical_name": name},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    table_id = await _entity("pxsaudit.a1672", "table")
    field_id = await _entity("a1672sto0", "field")
    proposed = await api_client.post(
        "/api/v1/company-graph/relationships",
        headers=_headers(org_a),
        json={
            "from_entity_id": table_id,
            "to_entity_id": field_id,
            "relationship_type": "CONTAINS",
            "source": "schema",
            "auto_confirm_structural": True,
        },
    )
    assert proposed.status_code == 201, proposed.text
    rel_id = proposed.json()["id"]
    assert proposed.json()["status"] == "auto_confirmed"

    # AUTO_CONFIRMED no se asigna a mano.
    manual = await api_client.post(
        f"/api/v1/company-graph/relationships/{rel_id}/confirm",
        headers=_headers(org_a),
        json={"status": "auto_confirmed"},
    )
    assert manual.status_code == 400

    deprecated = await api_client.post(
        f"/api/v1/company-graph/relationships/{rel_id}/deprecate",
        headers=_headers(org_a),
    )
    assert deprecated.status_code == 200
    assert deprecated.json()["status"] == "deprecated"

    current = await api_client.get(
        "/api/v1/company-graph/relationships", headers=_headers(org_a)
    )
    assert rel_id not in {r["id"] for r in current.json()["items"]}
    history = await api_client.get(
        f"/api/v1/company-graph/entities/{table_id}/history", headers=_headers(org_a)
    )
    assert rel_id in {r["id"] for r in history.json()["items"]}


@pytest.mark.asyncio
async def test_api_authority_is_tenant_scoped(api_client, api_orgs) -> None:
    org_a, org_b = api_orgs
    created = await api_client.post(
        "/api/v1/company-graph/authority",
        headers=_headers(org_a),
        json={
            "domain": "policy",
            "concept": "refund",
            "source_name": "official-docs",
            "source_type": "document",
            "authority_level": "authoritative",
            "priority": 1,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["authority_level"] == "authoritative"

    own = await api_client.get(
        "/api/v1/company-graph/authority", headers=_headers(org_a)
    )
    assert [r["source_name"] for r in own.json()["items"]] == ["official-docs"]
    other = await api_client.get(
        "/api/v1/company-graph/authority", headers=_headers(org_b)
    )
    assert other.json()["items"] == []
    invalid = await api_client.post(
        "/api/v1/company-graph/authority",
        headers=_headers(org_a),
        json={
            "domain": "policy",
            "concept": "refund",
            "source_name": "x",
            "authority_level": "not-a-level",
        },
    )
    assert invalid.status_code == 400
