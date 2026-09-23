# =============================================================================
# Company Intelligence Graph — Postgres adapter (backend inicial)
# =============================================================================
# SQL crudo + sqlalchemy.text(), como el resto del proyecto. Scoping estricto
# por organization_id en TODA query, incluido el traversal recursivo (el CTE
# filtra por tenant desde la semilla y en cada salto). Límites siempre:
# max_depth / max_nodes / max_edges. Sin consultas sin límite.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    ProvenanceRef,
    SourceAuthorityLevel,
    assert_status_transition,
    is_valid_at,
    normalize_entity_type,
    normalize_relationship_type,
)
from src.core.ports.company_graph import (
    CompanyGraphRepository,
    GraphNeighborhood,
    GraphPath,
    GraphTraversalLimits,
    ImpactResult,
    RelationshipFilter,
)
from src.infrastructure.postgres.session import get_async_session

_ENTITY_COLUMNS = (
    "id, organization_id, workspace_id, entity_type, canonical_name, "
    "display_name, description, domain, aliases, status, confidence, "
    "authority_level, source, source_ref, evidence, metadata, valid_from, "
    "valid_to, first_observed_at, last_observed_at, created_at, updated_at"
)

_REL_COLUMNS = (
    "id, organization_id, from_entity_id, to_entity_id, relationship_type, "
    "status, confidence, source, source_ref, evidence_refs, metadata, "
    "valid_from, valid_to, first_observed_at, last_observed_at, "
    "created_at, updated_at"
)

_NON_CURRENT = ("deprecated", "rejected")
_VALID_DIRECTIONS = frozenset({"out", "in", "both"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _filters_to_sql(
    flt: RelationshipFilter | None, alias: str = "r"
) -> tuple[str, dict]:
    """Fragmento WHERE reutilizable para filtrar aristas."""
    flt = flt or RelationshipFilter()
    clauses = [f"{alias}.organization_id = :oid"]
    params: dict = {}
    if flt.relationship_types:
        types = [normalize_relationship_type(t) for t in flt.relationship_types]
        clauses.append(f"{alias}.relationship_type = ANY(:rtypes)")
        params["rtypes"] = types
    statuses = tuple(flt.statuses)
    if flt.current_only and not statuses:
        clauses.append(f"NOT ({alias}.status = ANY(:non_current))")
        params["non_current"] = tuple(_NON_CURRENT)
    elif statuses:
        clauses.append(f"{alias}.status = ANY(:statuses)")
        params["statuses"] = tuple(s.value for s in statuses)
    if flt.min_confidence is not None:
        clauses.append(
            f"({alias}.confidence IS NULL OR {alias}.confidence >= :min_conf)"
        )
        params["min_conf"] = flt.min_confidence
    as_of = flt.as_of
    if as_of is not None:
        clauses.append(f"({alias}.valid_from IS NULL OR {alias}.valid_from <= :as_of)")
        clauses.append(f"({alias}.valid_to IS NULL OR {alias}.valid_to > :as_of)")
        params["as_of"] = as_of
    return " AND ".join(clauses), params


def _row_to_entity(row) -> CompanyEntity:
    aliases = tuple(row.aliases) if isinstance(row.aliases, list) else ()
    evidence = (
        tuple(ProvenanceRef.from_dict(p) for p in row.evidence)
        if isinstance(row.evidence, list)
        else ()
    )
    return CompanyEntity(
        organization_id=row.organization_id,
        entity_type=row.entity_type,
        canonical_name=row.canonical_name,
        display_name=row.display_name or "",
        description=row.description or "",
        domain=row.domain or "general",
        aliases=aliases,
        status=EntityStatus(row.status),
        confidence=row.confidence,
        authority_level=(
            SourceAuthorityLevel(row.authority_level)
            if row.authority_level
            else None
        ),
        source=row.source or "",
        source_ref=row.source_ref or "",
        evidence=evidence,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        workspace_id=row.workspace_id,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_relationship(row) -> CompanyRelationship:
    evidence = (
        tuple(ProvenanceRef.from_dict(p) for p in row.evidence_refs)
        if isinstance(row.evidence_refs, list)
        else ()
    )
    return CompanyRelationship(
        organization_id=row.organization_id,
        from_entity_id=row.from_entity_id,
        to_entity_id=row.to_entity_id,
        relationship_type=row.relationship_type,
        status=EntityStatus(row.status),
        confidence=row.confidence,
        source=row.source or "",
        source_ref=row.source_ref or "",
        evidence_refs=evidence,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        id=row.id,
    )


def _validate_direction(direction: str) -> str:
    direction = direction.strip().lower()
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of out/in/both (got {direction!r})")
    return direction


class PostgresCompanyGraphRepository(CompanyGraphRepository):
    """Backend Postgres inicial del grafo de compañía."""

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    async def get_entity(
        self, organization_id: UUID, entity_id: UUID
    ) -> CompanyEntity | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_ENTITY_COLUMNS} FROM company_entities "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(entity_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_entity(row) if row is not None else None
        finally:
            await session.close()

    async def find_entities(
        self,
        organization_id: UUID,
        *,
        entity_type: str | None = None,
        query: str | None = None,
        statuses: tuple[EntityStatus, ...] = (),
        current_only: bool = True,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyEntity]:
        clauses = ["organization_id = :oid"]
        params: dict = {"oid": str(organization_id)}
        if entity_type:
            clauses.append("entity_type = :etype")
            params["etype"] = normalize_entity_type(entity_type)
        if query:
            clauses.append(
                "(canonical_name ILIKE :q OR display_name ILIKE :q)"
            )
            params["q"] = f"%{query.strip()}%"
        if statuses:
            clauses.append("status = ANY(:statuses)")
            params["statuses"] = tuple(s.value for s in statuses)
        elif current_only:
            clauses.append("NOT (status = ANY(:non_current))")
            params["non_current"] = tuple(_NON_CURRENT)
        if as_of is not None:
            clauses.append("(valid_from IS NULL OR valid_from <= :as_of)")
            clauses.append("(valid_to IS NULL OR valid_to > :as_of)")
            params["as_of"] = as_of
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_ENTITY_COLUMNS} FROM company_entities "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY canonical_name LIMIT :limit OFFSET :offset"
                ),
                {**params, "limit": limit, "offset": offset},
            )
            return [_row_to_entity(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def find_relationships(
        self,
        organization_id: UUID,
        *,
        from_entity_id: UUID | None = None,
        to_entity_id: UUID | None = None,
        relationship_types: tuple[str, ...] = (),
        statuses: tuple[EntityStatus, ...] = (),
        current_only: bool = True,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyRelationship]:
        where, params = _filters_to_sql(
            RelationshipFilter(
                relationship_types=relationship_types,
                statuses=statuses,
                current_only=current_only,
                as_of=as_of,
            )
        )
        extra: dict = {}
        if from_entity_id is not None:
            where += " AND r.from_entity_id = :from_id"
            extra["from_id"] = str(from_entity_id)
        if to_entity_id is not None:
            where += " AND r.to_entity_id = :to_id"
            extra["to_id"] = str(to_entity_id)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {', '.join('r.' + c for c in _REL_COLUMNS.split(', '))} "
                    "FROM company_relationships r "
                    f"WHERE {where} "
                    "ORDER BY r.created_at DESC, r.id "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"oid": str(organization_id), **params, **extra,
                 "limit": limit, "offset": offset},
            )
            return [_row_to_relationship(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def neighbors(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        direction = _validate_direction(direction)
        limits = limits or GraphTraversalLimits()
        where, params = _filters_to_sql(relationship_filter)
        hop = self._hop_clause("r", ":eid", direction)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {', '.join('r.' + c for c in _REL_COLUMNS.split(', '))} "
                    "FROM company_relationships r "
                    f"WHERE {where} AND ({hop}) "
                    "ORDER BY r.created_at DESC, r.id "
                    "LIMIT :max_edges"
                ),
                {
                    "oid": str(organization_id),
                    **params,
                    "eid": str(entity_id),
                    "max_edges": limits.max_edges,
                },
            )
            rel_rows = result.fetchall()
            rels = [_row_to_relationship(row) for row in rel_rows]
            truncated = len(rels) >= limits.max_edges
            neighbor_ids = {r.from_entity_id for r in rels} | {
                r.to_entity_id for r in rels
            }
            neighbor_ids.discard(entity_id)
            entities = await self._fetch_entities(
                session, organization_id, sorted(neighbor_ids)[: limits.max_nodes]
            )
            return GraphNeighborhood(
                entities=tuple(entities),
                relationships=tuple(rels),
                truncated=truncated or len(neighbor_ids) > limits.max_nodes,
            )
        finally:
            await session.close()

    async def traverse(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        direction = _validate_direction(direction)
        limits = limits or GraphTraversalLimits()
        where, params = _filters_to_sql(relationship_filter, alias="e")
        hop_out = self._hop_clause("e", "v.node_id", "out")
        hop_in = self._hop_clause("e", "v.node_id", "in")
        if direction == "out":
            hop_union = hop_out
        elif direction == "in":
            hop_union = hop_in
        else:
            hop_union = f"({hop_out}) OR ({hop_in})"
        fanout = max(1, min(limits.max_edges, 200))
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    WITH RECURSIVE walk(node_id, depth, path) AS (
                        SELECT CAST(:eid AS uuid), 0, ARRAY[CAST(:eid AS uuid)]
                        UNION
                        SELECT hop.next_id, v.depth + 1, v.path || hop.next_id
                        FROM walk v
                        CROSS JOIN LATERAL (
                            SELECT DISTINCT
                                CASE
                                    WHEN e.from_entity_id = v.node_id
                                        THEN e.to_entity_id
                                    ELSE e.from_entity_id
                                END AS next_id
                            FROM company_relationships e
                            WHERE {where}
                              AND ({hop_union})
                            LIMIT :fanout
                        ) hop
                        WHERE v.depth < :max_depth
                          AND NOT (hop.next_id = ANY(v.path))
                    )
                    SELECT node_id, MIN(depth) AS depth FROM walk
                    GROUP BY node_id
                    ORDER BY MIN(depth), node_id
                    LIMIT :max_nodes
                    """
                ),
                {
                    "oid": str(organization_id),
                    **params,
                    "eid": str(entity_id),
                    "max_depth": limits.max_depth,
                    "max_nodes": limits.max_nodes + 1,
                    "fanout": fanout,
                },
            )
            rows = result.fetchall()
            truncated = len(rows) > limits.max_nodes
            node_ids = [r.node_id for r in rows[: limits.max_nodes]]
            rel_ids = await self._collect_walk_edges(
                session, organization_id, node_ids, relationship_filter
            )
            entities = await self._fetch_entities(session, organization_id, node_ids)
            rels = await self._fetch_relationships(session, organization_id, rel_ids[: limits.max_edges])
            return GraphNeighborhood(
                entities=tuple(entities),
                relationships=tuple(rels),
                truncated=truncated or len(rel_ids) > limits.max_edges,
            )
        finally:
            await session.close()

    async def find_path(
        self,
        organization_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
        *,
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphPath | None:
        if from_entity_id == to_entity_id:
            entity = await self.get_entity(organization_id, from_entity_id)
            if entity is None:
                return None
            return GraphPath(entities=(entity,), relationships=())
        limits = limits or GraphTraversalLimits()
        hood = await self.traverse(
            organization_id,
            from_entity_id,
            direction="both",
            relationship_filter=relationship_filter,
            limits=limits,
        )
        if not any(e.id == to_entity_id for e in hood.entities):
            return None
        by_id = {e.id: e for e in hood.entities}
        root = await self.get_entity(organization_id, from_entity_id)
        if root is not None:
            by_id[root.id] = root
        adj: dict[str, list[tuple[str, CompanyRelationship]]] = {}
        for rel in hood.relationships:
            a, b = str(rel.from_entity_id), str(rel.to_entity_id)
            adj.setdefault(a, []).append((b, rel))
            adj.setdefault(b, []).append((a, rel))
        start, target = str(from_entity_id), str(to_entity_id)
        prev: dict[str, tuple[str, CompanyRelationship]] = {}
        seen = {start}
        queue = [start]
        while queue:
            current = queue.pop(0)
            if current == target:
                break
            for nxt, rel in adj.get(current, []):
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = (current, rel)
                    queue.append(nxt)
        if target not in prev:
            return None
        rel_chain: list[CompanyRelationship] = []
        node_chain = [target]
        cursor = target
        while cursor != start:
            parent, rel = prev[cursor]
            rel_chain.append(rel)
            node_chain.append(parent)
            cursor = parent
        rel_chain.reverse()
        node_chain.reverse()
        entities = tuple(by_id[UUID(n)] for n in node_chain if UUID(n) in by_id)
        return GraphPath(entities=entities, relationships=tuple(rel_chain))

    async def impact_analysis(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> ImpactResult:
        direction = _validate_direction(direction)
        limits = limits or GraphTraversalLimits()
        hood = await self.traverse(
            organization_id,
            entity_id,
            direction=direction,
            relationship_filter=relationship_filter,
            limits=limits,
        )
        root = await self.get_entity(organization_id, entity_id)
        by_type: dict[str, int] = {}
        for entity in hood.entities:
            by_type[entity.entity_type] = by_type.get(entity.entity_type, 0) + 1
        return ImpactResult(
            root=root,
            entities=hood.entities,
            relationships=hood.relationships,
            by_type=by_type,
            truncated=hood.truncated,
        )

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    async def upsert_entity(self, entity: CompanyEntity) -> CompanyEntity:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO company_entities ({_ENTITY_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :entity_type,
                        :canonical_name, :display_name, :description, :domain,
                        CAST(:aliases AS jsonb), :status, :confidence,
                        :authority_level, :source, :source_ref,
                        CAST(:evidence AS jsonb), CAST(:metadata AS jsonb),
                        :valid_from, :valid_to, :first_observed_at,
                        :last_observed_at, now(), now()
                    )
                    ON CONFLICT (id)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        domain = EXCLUDED.domain,
                        aliases = EXCLUDED.aliases,
                        status = EXCLUDED.status,
                        confidence = EXCLUDED.confidence,
                        authority_level = EXCLUDED.authority_level,
                        source = EXCLUDED.source,
                        source_ref = EXCLUDED.source_ref,
                        evidence = EXCLUDED.evidence,
                        metadata = EXCLUDED.metadata,
                        valid_from = EXCLUDED.valid_from,
                        valid_to = EXCLUDED.valid_to,
                        last_observed_at = EXCLUDED.last_observed_at,
                        updated_at = now()
                    RETURNING {_ENTITY_COLUMNS}
                    """
                ),
                {
                    "id": str(entity.id),
                    "organization_id": str(entity.organization_id),
                    "workspace_id": _uuid_or_none(entity.workspace_id),
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "display_name": entity.display_name,
                    "description": entity.description,
                    "domain": entity.domain,
                    "aliases": json.dumps(list(entity.aliases), default=str),
                    "status": entity.status.value,
                    "confidence": entity.confidence,
                    "authority_level": (
                        entity.authority_level.value
                        if entity.authority_level
                        else None
                    ),
                    "source": entity.source,
                    "source_ref": entity.source_ref,
                    "evidence": json.dumps(
                        [p.to_dict() for p in entity.evidence], default=str
                    ),
                    "metadata": json.dumps(entity.metadata, default=str),
                    "valid_from": entity.valid_from,
                    "valid_to": entity.valid_to,
                    "first_observed_at": entity.first_observed_at,
                    "last_observed_at": entity.last_observed_at,
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_entity(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def propose_relationship(
        self, relationship: CompanyRelationship
    ) -> CompanyRelationship:
        session = await get_async_session()
        try:
            owner = await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM company_entities "
                    "WHERE organization_id = :oid AND id = ANY(:ids)"
                ),
                {
                    "oid": str(relationship.organization_id),
                    "ids": [
                        str(relationship.from_entity_id),
                        str(relationship.to_entity_id),
                    ],
                },
            )
            if (owner.fetchone().n or 0) != 2:
                raise ValueError(
                    "both relationship endpoints must belong to the organization"
                )
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO company_relationships ({_REL_COLUMNS})
                    VALUES (
                        :id, :organization_id, :from_entity_id, :to_entity_id,
                        :relationship_type, :status, :confidence, :source,
                        :source_ref, CAST(:evidence_refs AS jsonb),
                        CAST(:metadata AS jsonb), :valid_from, :valid_to,
                        :first_observed_at, :last_observed_at, now(), now()
                    )
                    RETURNING {_REL_COLUMNS}
                    """
                ),
                {
                    "id": str(relationship.id),
                    "organization_id": str(relationship.organization_id),
                    "from_entity_id": str(relationship.from_entity_id),
                    "to_entity_id": str(relationship.to_entity_id),
                    "relationship_type": relationship.relationship_type,
                    "status": relationship.status.value,
                    "confidence": relationship.confidence,
                    "source": relationship.source,
                    "source_ref": relationship.source_ref,
                    "evidence_refs": json.dumps(
                        [p.to_dict() for p in relationship.evidence_refs],
                        default=str,
                    ),
                    "metadata": json.dumps(relationship.metadata, default=str),
                    "valid_from": relationship.valid_from,
                    "valid_to": relationship.valid_to,
                    "first_observed_at": relationship.first_observed_at,
                    "last_observed_at": relationship.last_observed_at,
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_relationship(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def confirm_relationship(
        self,
        organization_id: UUID,
        relationship_id: UUID,
        *,
        status: EntityStatus,
    ) -> CompanyRelationship:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_REL_COLUMNS} FROM company_relationships "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(relationship_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            if row is None:
                raise ValueError("relationship not found for this organization")
            current = _row_to_relationship(row)
            assert_status_transition(current.status, status)
            updated = await session.execute(
                text(
                    f"UPDATE company_relationships SET status = :status, "
                    "last_observed_at = now(), updated_at = now() "
                    "WHERE id = :id AND organization_id = :oid "
                    f"RETURNING {_REL_COLUMNS}"
                ),
                {
                    "id": str(relationship_id),
                    "oid": str(organization_id),
                    "status": status.value,
                },
            )
            fresh = updated.fetchone()
            await session.commit()
            return _row_to_relationship(fresh)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def deprecate_relationship(
        self, organization_id: UUID, relationship_id: UUID
    ) -> CompanyRelationship:
        return await self.confirm_relationship(
            organization_id, relationship_id, status=EntityStatus.DEPRECATED
        )

    async def entity_history(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyRelationship]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {', '.join('r.' + c for c in _REL_COLUMNS.split(', '))} "
                    "FROM company_relationships r "
                    "WHERE r.organization_id = :oid "
                    "AND (r.from_entity_id = :eid OR r.to_entity_id = :eid) "
                    "ORDER BY r.created_at DESC, r.id "
                    "LIMIT :limit OFFSET :offset"
                ),
                {
                    "oid": str(organization_id),
                    "eid": str(entity_id),
                    "limit": limit,
                    "offset": offset,
                },
            )
            return [_row_to_relationship(row) for row in result.fetchall()]
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------
    @staticmethod
    def _hop_clause(alias: str, node_param: str, direction: str) -> str:
        if direction == "out":
            return f"{alias}.from_entity_id = {node_param}"
        if direction == "in":
            return f"{alias}.to_entity_id = {node_param}"
        return (
            f"({alias}.from_entity_id = {node_param} "
            f"OR {alias}.to_entity_id = {node_param})"
        )

    async def _fetch_entities(
        self, session, organization_id: UUID, entity_ids: list
    ) -> list[CompanyEntity]:
        if not entity_ids:
            return []
        result = await session.execute(
            text(
                f"SELECT {_ENTITY_COLUMNS} FROM company_entities "
                "WHERE organization_id = :oid AND id = ANY(:ids)"
            ),
            {"oid": str(organization_id), "ids": [str(i) for i in entity_ids]},
        )
        rows = {str(r.id): r for r in result.fetchall()}
        ordered = [rows[str(i)] for i in entity_ids if str(i) in rows]
        return [_row_to_entity(row) for row in ordered]

    async def _fetch_relationships(
        self, session, organization_id: UUID, rel_ids: list
    ) -> list[CompanyRelationship]:
        if not rel_ids:
            return []
        result = await session.execute(
            text(
                f"SELECT {_REL_COLUMNS} FROM company_relationships "
                "WHERE organization_id = :oid AND id = ANY(:ids)"
            ),
            {"oid": str(organization_id), "ids": [str(i) for i in rel_ids]},
        )
        return [_row_to_relationship(row) for row in result.fetchall()]

    async def _collect_walk_edges(
        self,
        session,
        organization_id: UUID,
        node_ids: list,
        flt: RelationshipFilter | None,
    ) -> list:
        if len(node_ids) < 2:
            return []
        where, params = _filters_to_sql(flt)
        result = await session.execute(
            text(
                "SELECT id FROM company_relationships r "
                f"WHERE {where} "
                "AND r.from_entity_id = ANY(:nodes) "
                "AND r.to_entity_id = ANY(:nodes)"
            ),
            {
                "oid": str(organization_id),
                **params,
                "nodes": [str(n) for n in node_ids],
            },
        )
        return [r.id for r in result.fetchall()]


def filter_current_relationships(
    relationships: list[CompanyRelationship],
    as_of: datetime | None = None,
) -> list[CompanyRelationship]:
    """Vista current en memoria (para tests y capas sin DB)."""
    moment = as_of or _utcnow()
    return [
        r
        for r in relationships
        if r.status.value not in _NON_CURRENT
        and is_valid_at(r.valid_from, r.valid_to, moment)
    ]
