# =============================================================================
# P18.3-04 - Backfill de fuentes históricas sin corpus (Postgres real)
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.core.domain.knowledge_v2 import KnowledgeCorpus, KnowledgeObjectStatus
from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
from src.infrastructure.postgres.relational_db import (
    PostgresKnowledgeBaseRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.scripts.legacy_source_corpus_backfill import (
    apply_plan,
    build_plan,
    load_plan,
    plan_checksum,
    rollback_plan,
    write_plan,
)


async def _context(label: str):
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.3 Legacy {label} {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(
        org.id, f"Workspace {label}", f"ws-{uuid4().hex[:8]}"
    )
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name=f"Corpus {label}",
        slug=f"corpus-{uuid4().hex[:8]}",
        status=KnowledgeObjectStatus.DRAFT,
    )
    await PostgresKnowledgeCorpusRepository().create_corpus(corpus)
    kb = await PostgresKnowledgeBaseRepository().create_kb(
        org.id, f"KB {label} {uuid4().hex[:6]}", workspace_id=workspace.id
    )
    return org, workspace, corpus, kb


async def _source(org, workspace, *, kb=None, config=None, with_workspace=True):
    return await PostgresSourceRepository().create_source(
        org.id,
        f"legacy-{uuid4().hex[:8]}.pdf",
        "file",
        knowledge_base_id=kb.id if kb else None,
        config_json=config or {},
        workspace_id=workspace.id if with_workspace else None,
    )


async def _link_kb(kb_id: UUID, corpus_id: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE knowledge_bases SET corpus_id = :cid, updated_at = now() "
                "WHERE id = :kid"
            ),
            {"cid": str(corpus_id), "kid": str(kb_id)},
        )
        await session.commit()
    finally:
        await session.close()


async def _corpus_of(source_id: UUID) -> UUID | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT corpus_id FROM kb_sources WHERE id = :sid"),
                {"sid": str(source_id)},
            )
        ).fetchone()
        return UUID(str(row.corpus_id)) if row and row.corpus_id else None
    finally:
        await session.close()


async def _cleanup(org_id: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM legacy_source_corpus_journal WHERE organization_id = :oid"),
            {"oid": str(org_id)},
        )
        await session.execute(
            text("DELETE FROM organizations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_determinate_source_is_applied_idempotently_and_rolled_back() -> None:
    org, workspace, corpus, kb = await _context("determinate")
    try:
        await _link_kb(kb.id, corpus.id)
        source = await _source(org, workspace, kb=kb)
        plan = await build_plan(organization_id=org.id, include_names=False)
        row = next(item for item in plan["rows"] if item["source_id"] == str(source.id))
        assert row["classification"] == "determinate"
        assert row["candidate_corpus_id"] == str(corpus.id)
        assert row["decision"] == "proposed"

        first = await apply_plan(
            rows=plan["rows"], plan_id=plan["plan_id"], actor="test-operator"
        )
        assert first["applied"] == 1
        assert await _corpus_of(source.id) == corpus.id

        second = await apply_plan(
            rows=plan["rows"], plan_id=plan["plan_id"], actor="test-operator"
        )
        assert second["applied"] == 0
        assert second["skipped"] == 1
        assert await _corpus_of(source.id) == corpus.id

        rolled = await rollback_plan(plan_id=plan["plan_id"], actor="test-operator")
        assert rolled["rolled_back"] == 1
        assert rolled["conflicts"] == 0
        assert await _corpus_of(source.id) is None
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_single_workspace_corpus_is_not_assigned_blindly() -> None:
    org, workspace, _corpus, _kb = await _context("single-candidate")
    try:
        source = await _source(org, workspace)
        plan = await build_plan(organization_id=org.id)
        row = next(item for item in plan["rows"] if item["source_id"] == str(source.id))
        assert row["classification"] == "needs_resolution"
        assert row["reason"] == "no_explicit_link"
        assert row["decision"] == "blocked"
        assert row["candidate_corpus_id"] is None
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_operator_selector_is_the_only_way_to_resolve_ambiguous_link() -> None:
    org, workspace, corpus, kb = await _context("ambiguous")
    try:
        other = KnowledgeCorpus(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Otro corpus",
            slug=f"otro-{uuid4().hex[:8]}",
            status=KnowledgeObjectStatus.DRAFT,
        )
        await PostgresKnowledgeCorpusRepository().create_corpus(other)
        await _link_kb(kb.id, corpus.id)
        source = await _source(
            org, workspace, kb=kb, config={"corpus_id": str(other.id)}
        )
        plan = await build_plan(organization_id=org.id)
        row = next(item for item in plan["rows"] if item["source_id"] == str(source.id))
        assert row["classification"] == "ambiguous"
        assert {item["corpus_id"] for item in row["candidates"]} == {
            str(corpus.id),
            str(other.id),
        }

        selected = await build_plan(
            organization_id=org.id,
            resolutions={source.id: corpus.id},
        )
        selected_row = next(
            item for item in selected["rows"] if item["source_id"] == str(source.id)
        )
        assert selected_row["classification"] == "determinate"
        assert selected_row["reason"] == "operator_selected"
        assert selected_row["candidate_corpus_id"] == str(corpus.id)
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_orphan_and_cross_scope_are_blocked() -> None:
    org, workspace, _corpus, kb = await _context("scope")
    foreign_org, _foreign_workspace, foreign_corpus, _foreign_kb = await _context("foreign")
    try:
        orphan = await _source(org, workspace, with_workspace=False)
        await _link_kb(kb.id, foreign_corpus.id)
        cross = await _source(org, workspace, kb=kb)
        plan = await build_plan(organization_id=org.id)
        rows = {item["source_id"]: item for item in plan["rows"]}
        assert rows[str(orphan.id)]["classification"] == "orphan"
        assert rows[str(orphan.id)]["reason"] == "workspace_missing"
        assert rows[str(cross.id)]["classification"] == "cross_scope_conflict"
        assert rows[str(cross.id)]["reason"] in {
            "kb_corpus_missing",
            "kb_corpus_other_workspace",
            "kb_corpus_other_organization",
        }
        assert rows[str(cross.id)]["decision"] == "blocked"
    finally:
        await _cleanup(org.id)
        await _cleanup(foreign_org.id)


@pytest.mark.asyncio
async def test_apply_cas_rejects_source_changed_after_plan() -> None:
    org, workspace, corpus, kb = await _context("cas")
    try:
        await _link_kb(kb.id, corpus.id)
        source = await _source(org, workspace, kb=kb)
        plan = await build_plan(organization_id=org.id)
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE kb_sources SET workspace_id = NULL WHERE id = :sid"),
                {"sid": str(source.id)},
            )
            await session.commit()
        finally:
            await session.close()

        result = await apply_plan(
            rows=plan["rows"], plan_id=plan["plan_id"], actor="test-operator"
        )
        assert result["applied"] == 0
        assert result["conflicts"] == 1
        assert await _corpus_of(source.id) is None
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_rollback_refuses_to_overwrite_concurrent_change() -> None:
    org, workspace, corpus, kb = await _context("rollback-conflict")
    try:
        await _link_kb(kb.id, corpus.id)
        source = await _source(org, workspace, kb=kb)
        plan = await build_plan(organization_id=org.id)
        await apply_plan(rows=plan["rows"], plan_id=plan["plan_id"], actor="test")
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE kb_sources SET corpus_id = NULL WHERE id = :sid"),
                {"sid": str(source.id)},
            )
            await session.commit()
        finally:
            await session.close()

        result = await rollback_plan(plan_id=plan["plan_id"], actor="test")
        assert result["rolled_back"] == 0
        assert result["conflicts"] == 1
    finally:
        await _cleanup(org.id)


def test_plan_checksum_changes_when_a_decision_changes(tmp_path: Path) -> None:
    rows = [
        {
            "plan_id": "p",
            "organization_id": "o",
            "source_id": "s",
            "classification": "determinate",
            "decision": "proposed",
        }
    ]
    baseline = plan_checksum(rows)
    rows[0]["decision"] = "blocked"
    assert plan_checksum(rows) != baseline

    path = tmp_path / "plan.jsonl"
    checksum = write_plan(path, rows)
    loaded = load_plan(path)
    assert plan_checksum(loaded) == checksum
    assert json.loads(path.read_text().splitlines()[0])["decision"] == "blocked"
