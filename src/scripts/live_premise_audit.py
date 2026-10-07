# =============================================================================
# Live Premise Audit — diagnóstico real (Postgres + Qdrant + retriever reales)
# =============================================================================
# Uso (dentro de la API con deps reales):
#   python -m src.scripts.live_premise_audit \
#       --org <uuid> [--source <uuid>] [--document <uuid>] \
#       --question "..." [--out artifacts/live-premise-audit]
#
# NO usa fixtures, NO usa InMemory*, NO usa FakeVectorStore. Produce un JSON
# con runtime_identity, dependency_health, qdrant, scope, retrieval, lanes,
# compilación query-local, evaluación, claim/envelope y root_cause explícita.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from src.runtime.runtime_identity import build_parity, runtime_identity

DEFAULT_QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)
REGRESSION_NEEDLES = (
    "ampersand",
    "alphanumeric",
    "additional characters may follow",
    "position",
)
TARGET_TERMS = ("ampersand", "alphanumeric", "additional characters")


def _safe_excerpt(text: str, size: int = 160) -> str:
    return " ".join(str(text or "")[:size].split())


def _chunk_meta(chunk: Any) -> dict[str, Any]:
    metadata = getattr(chunk, "metadata", None) or {}
    section_path = metadata.get("section_path") or metadata.get("heading_path") or []
    if isinstance(section_path, str):
        try:
            parsed = json.loads(section_path)
            section_path = parsed if isinstance(parsed, list) else [section_path]
        except (TypeError, ValueError):
            section_path = [section_path]
    return {
        "chunk_id": metadata.get("chunk_id"),
        "document_id": metadata.get("document_id"),
        "source_id": metadata.get("source_id"),
        "workspace_id": metadata.get("workspace_id"),
        "page": metadata.get("page") or metadata.get("page_start"),
        "section_path": list(section_path)[:4],
        "v2_chunk": metadata.get("v2_chunk"),
        "representation_kind": metadata.get("representation_kind")
        or metadata.get("chunk_kind"),
        "parser": metadata.get("parser") or metadata.get("parser_engine"),
        "excerpt": _safe_excerpt(getattr(chunk, "content", "")),
    }


def _dependency_health() -> dict[str, Any]:
    health: dict[str, Any] = {}
    getters = (
        ("get_knowledge_retriever", "get_knowledge_retriever"),
        ("get_vector_store", "get_vector_store"),
        ("get_embedding_provider", "get_embedding_provider"),
    )
    for label, getter_name in getters:
        entry: dict[str, Any] = {"constructed": False}
        try:
            from src.api import deps as deps_module

            instance = getattr(deps_module, getter_name)()
            entry["constructed"] = instance is not None
            entry["class"] = type(instance).__name__
        except Exception as exc:  # noqa: BLE001 — se reporta, no se oculta
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        health[label] = entry
    return health


async def _source_info(org: UUID, source_id: UUID | None, document_id: UUID | None) -> dict[str, Any]:
    info: dict[str, Any] = {"source": None, "documents": []}
    try:
        from src.api.deps import get_source_repo

        sources = get_source_repo()
        if source_id is not None:
            source = await sources.get_source(org, source_id)
            if source is not None:
                info["source"] = {
                    "id": str(source.id),
                    "type": getattr(source, "type", ""),
                    "name": getattr(source, "name", ""),
                    "status": getattr(source, "status", ""),
                    "workspace_id": str(getattr(source, "workspace_id", "") or ""),
                }
    except Exception as exc:  # noqa: BLE001
        info["source_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    if source_id is not None:
        try:
            from src.infrastructure.postgres.structured_documents import (
                PostgresStructuredDocumentRepository,
            )

            repo = PostgresStructuredDocumentRepository()
            documents = await repo.list_documents(org, source_id, limit=20)
            for document in documents:
                metadata = document.get("metadata") or {}
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except (TypeError, ValueError):
                        metadata = {}
                parser = metadata.get("parser") or {}
                info["documents"].append(
                    {
                        "id": str(document.get("id")),
                        "external_id": document.get("external_id"),
                        "title": document.get("title"),
                        "block_count": document.get("block_count"),
                        "table_count": document.get("table_count"),
                        "parser_engine": parser.get("engine")
                        or metadata.get("parser_engine"),
                        "parser_version": parser.get("version")
                        or metadata.get("parser_version"),
                        "parser_mode": parser.get("mode")
                        or metadata.get("parser_mode"),
                        "structure_source": parser.get("structure_source")
                        or metadata.get("structure_source"),
                        "parser_timestamp": parser.get("parser_timestamp")
                        or metadata.get("parser_timestamp"),
                        "java_version": parser.get("java_version"),
                        "opendataloader_version": parser.get("opendataloader_version"),
                        "document_parser": metadata.get("document_parser"),
                        "runtime_identity": metadata.get("runtime_identity"),
                        "updated_at": str(document.get("updated_at") or ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            info["documents_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    if document_id is not None:
        info["document_filter"] = str(document_id)
    return info


def _parser_provenance_status(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """§17: OK / MISSING / INCONSISTENT — sin aceptar parser_engine=null.

    No bloquea el root_cause cognitivo: coexiste y se muestra.
    """
    rows: list[dict[str, Any]] = []
    for document in documents:
        engine = str(document.get("parser_engine") or "")
        version = str(document.get("parser_version") or "")
        mode = str(document.get("parser_mode") or "")
        structure = str(document.get("structure_source") or "")
        status = "OK" if engine and version and mode else "MISSING"
        if status == "OK" and engine not in ("pdfplumber", "opendataloader"):
            status = "INCONSISTENT"
        if status == "OK" and engine == "opendataloader" and mode == "pdfplumber":
            status = "INCONSISTENT"
        rows.append(
            {
                "document_id": document.get("id"),
                "external_id": document.get("external_id"),
                "parser_engine": engine or None,
                "parser_version": version or None,
                "parser_mode": mode or None,
                "structure_source": structure or None,
                "parser_timestamp": document.get("parser_timestamp"),
                "java_version": document.get("java_version"),
                "opendataloader_version": document.get("opendataloader_version"),
                "status": status,
            }
        )
    if not rows:
        overall = "MISSING"
    elif any(row["status"] == "INCONSISTENT" for row in rows):
        overall = "INCONSISTENT"
    elif all(row["status"] == "OK" for row in rows):
        overall = "OK"
    else:
        overall = "MISSING"
    return {"status": overall, "documents": rows}


async def _main_retrieval(org: UUID, workspace_id: UUID | None, question: str) -> dict[str, Any]:
    result: dict[str, Any] = {"items": [], "errors": []}
    try:
        from src.api.deps import get_embedding_provider, get_knowledge_retriever
        from src.rag.retrieval.models import RetrievalQuery
        from src.rag.retrieval.structured import V2RetrievalOptions

        embedded = await get_embedding_provider().embed(question)
        if embedded and isinstance(embedded[0], list):
            embedded = embedded[0]
        assembled = await get_knowledge_retriever().retrieve(
            RetrievalQuery(
                query=question,
                organization_id=org,
                workspace_id=workspace_id,
                top_k=50,
                effective_top_k=50,
                query_embedding=list(embedded) if embedded else None,
            ),
            V2RetrievalOptions(),
        )
        chunks = list(getattr(assembled, "context", None) or [])
        result["items"] = [_chunk_meta(chunk) for chunk in chunks]
        result["count"] = len(chunks)
        result["_chunks"] = chunks
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{type(exc).__name__}: {str(exc)[:200]}")
    return result


async def _premise_queries(
    org: UUID,
    workspace_id: UUID | None,
    question: str,
    retriever_result: Any,
) -> dict[str, Any]:
    report: dict[str, Any] = {"queries": [], "hits": [], "lane_errors": []}
    adapter = getattr(retriever_result, "adapter", None)
    if not getattr(retriever_result, "available", False) or adapter is None:
        report["unavailable"] = True
        return report
    try:
        from src.runtime.premise_closure import (
            PREMISE_LENGTH_POLICY,
            PREMISE_MATCHING_POSITIONAL,
            PREMISE_SYMBOL_PREFIX,
            PremiseClosureRequest,
            PremiseQueryPlanner,
            SourceScope,
        )

        scope = SourceScope(
            organization_id=str(org),
            workspace_id=str(workspace_id or ""),
        )
        request = PremiseClosureRequest(
            original_query=question,
            missing_premises=(
                f"{PREMISE_SYMBOL_PREFIX}&",
                PREMISE_MATCHING_POSITIONAL,
                PREMISE_LENGTH_POLICY,
            ),
            runtime_pattern="&&&F",
            source_scope=scope,
            rounds_left=2,
        )
        planned = PremiseQueryPlanner(
            max_queries_per_premise=3, max_queries_per_round=6
        ).plan(request)
        for planned_query in planned:
            entry = {
                "premise": planned_query.premise,
                "lane": planned_query.lane,
                "query": planned_query.query[:160],
            }
            try:
                hits = await adapter.search(planned_query.query, scope, 6)
                entry["hit_count"] = len(hits)
                entry["evidence_ids"] = [hit.evidence_id for hit in hits[:6]]
                report["hits"].extend(
                    [
                        {
                            "premise": planned_query.premise,
                            "lane": hit.lane,
                            "evidence_id": hit.evidence_id,
                            "document_id": hit.document_id,
                            "source_id": hit.source_id,
                            "excerpt": _safe_excerpt(hit.content),
                        }
                        for hit in hits
                    ]
                )
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            report["queries"].append(entry)
        report["lane_errors"] = list(getattr(adapter, "last_lane_errors", ()))
        report["lanes"] = dict(getattr(adapter, "last_lanes", {}))
    except Exception as exc:  # noqa: BLE001
        report["errors"] = [f"{type(exc).__name__}: {str(exc)[:200]}"]
    return report


async def _qdrant_scan(org: UUID) -> dict[str, Any]:
    report: dict[str, Any] = {"needles": list(REGRESSION_NEEDLES), "hits": [], "errors": []}
    try:
        from src.api.deps import get_vector_store

        store = get_vector_store()
        context = await store.scan_text_literal(org, list(REGRESSION_NEEDLES), limit=10)
        report["hits"] = [_chunk_meta(chunk) for chunk in (context.chunks or [])]
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {str(exc)[:200]}")
    return report


def _scope_audit(main_items: list[dict[str, Any]], source: dict[str, Any] | None) -> dict[str, Any]:
    document_ids = [item.get("document_id") for item in main_items if item.get("document_id")]
    source_ids = [item.get("source_id") for item in main_items if item.get("source_id")]
    audit = {
        "document_ids": list(dict.fromkeys(document_ids))[:12],
        "source_ids": list(dict.fromkeys(source_ids))[:12],
        "workspace_ids": list(
            dict.fromkeys(
                item.get("workspace_id")
                for item in main_items
                if item.get("workspace_id")
            )
        )[:12],
        "origin": "initial_retrieval_metadata",
    }
    source_known = bool(source and source.get("id"))
    audit["source_visible_in_citation"] = source_known
    audit["source_id_missing_in_scope"] = source_known and not audit["source_ids"]
    audit["document_id_missing_in_scope"] = bool(main_items) and not audit["document_ids"]
    return audit


def _collection_info() -> dict[str, Any]:
    info: dict[str, Any] = {"write_collection": "unknown", "read_collection": "unknown"}
    try:
        from src.infrastructure.qdrant.vector_store import RAG_DOCUMENTS_COLLECTION

        info["write_collection"] = RAG_DOCUMENTS_COLLECTION
        info["read_collection"] = RAG_DOCUMENTS_COLLECTION
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    import os

    env_collection = str(os.environ.get("RAG_QDRANT_COLLECTION", "") or "").strip()
    info["env_collection"] = env_collection or None
    info["match"] = (
        not env_collection or env_collection == info["write_collection"]
    )
    return info


def _target_hit(items: list[dict[str, Any]]) -> bool:
    for item in items:
        text = str(item.get("excerpt") or "").lower()
        if any(term in text for term in TARGET_TERMS):
            return True
    return False


def _classify_root_cause(report: dict[str, Any]) -> str:
    parity = report.get("build_parity") or {}
    if parity.get("status") == "BUILD_MISMATCH":
        return "BUILD_MISMATCH"
    premise = report.get("premise_retriever") or {}
    if not premise.get("available"):
        return "PREMISE_RETRIEVER_FACTORY_FAILED"
    collection = report.get("qdrant_collection") or {}
    if collection.get("match") is False:
        return "COLLECTION_MISMATCH"
    scope = report.get("source_scope") or {}
    if scope.get("source_id_missing_in_scope") or scope.get("document_id_missing_in_scope"):
        return "SOURCE_SCOPE_MISMATCH"
    scan = report.get("qdrant_scan") or {}
    scan_hits = list(scan.get("hits") or [])
    if not scan_hits:
        return "EVIDENCE_NOT_INDEXED"
    if any(
        not hit.get("document_id") or not hit.get("source_id") for hit in scan_hits
    ):
        return "QDRANT_METADATA_MISSING"
    main = report.get("main_retrieval") or {}
    premise_queries = report.get("premise_queries") or {}
    premise_hits = list(premise_queries.get("hits") or [])
    if _target_hit(list(main.get("items") or [])) and not premise_hits:
        return "EVIDENCE_SEARCH_MISS"
    raw = report.get("raw_evidence_parity") or {}
    live = report.get("live_prepare") or {}
    if raw.get("executable", 0) > 0 and live.get("query_local_executable", 0) == 0:
        return "QUERY_LOCAL_COMPILATION_MISS"
    if live.get("query_local_executable", 0) > 0 and not live.get("has_authority"):
        return "DERIVATION_MISS"
    if live.get("has_authority"):
        return "PASS"
    return "UNKNOWN"


async def run_audit(
    *,
    org: UUID,
    question: str,
    source_id: UUID | None = None,
    document_id: UUID | None = None,
    worker_sha: str = "",
    worker_timestamp: str = "",
) -> dict[str, Any]:
    identity = runtime_identity()
    worker_identity = (
        {"git_sha": worker_sha, "build_timestamp": worker_timestamp}
        if worker_sha
        else None
    )
    report: dict[str, Any] = {
        "schema": "zent.live_premise_audit.1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "organization_id": str(org),
        "runtime_identity": identity,
        "build_parity": build_parity(identity, worker_identity),
        "dependency_health": _dependency_health(),
        "qdrant_collection": _collection_info(),
    }

    from src.runtime.premise_retriever import build_premise_evidence_search_result

    retriever_result = build_premise_evidence_search_result(org)
    report["premise_retriever"] = retriever_result.to_public_dict()

    report["source"] = await _source_info(org, source_id, document_id)
    report["parser_provenance"] = _parser_provenance_status(
        list(report["source"].get("documents") or [])
    )
    if worker_identity is None:
        documents = (report["source"].get("documents") or [])
        recorded = next(
            (
                document.get("runtime_identity")
                for document in documents
                if document.get("runtime_identity")
            ),
            None,
        )
        if recorded:
            report["build_parity"] = build_parity(identity, recorded)

    report["qdrant_scan"] = await _qdrant_scan(org)
    report["main_retrieval"] = await _main_retrieval(org, None, question)
    main_chunks = list(report["main_retrieval"].pop("_chunks", []))
    report["source_scope"] = _scope_audit(
        list(report["main_retrieval"].get("items") or []),
        report["source"].get("source"),
    )
    report["premise_queries"] = await _premise_queries(
        org, None, question, retriever_result
    )

    # Raw evidence parity: compilar el chunk que el main retrieval ya encontró.
    raw_parity: dict[str, Any] = {}
    try:
        from src.runtime.query_local_rules import compile_query_local_rules

        if main_chunks:
            compilation = compile_query_local_rules(
                main_chunks,
                document_id=str(
                    (getattr(main_chunks[0], "metadata", {}) or {}).get("document_id")
                    or ""
                ),
            )
            raw_parity = {
                "candidates": compilation.candidates,
                "supported": compilation.supported,
                "executable": compilation.executable,
                "conflicts": compilation.conflicts,
                "rules": [
                    {
                        "rule_id": str(rule.rule_id),
                        "state": rule.verification_state,
                        "executable": bool(rule.executable),
                        "missing_premises": list(rule.missing_premises[:6]),
                        "properties": sorted(rule.properties),
                    }
                    for rule in compilation.rules[:12]
                ],
            }
    except Exception as exc:  # noqa: BLE001
        raw_parity = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    report["raw_evidence_parity"] = raw_parity

    # Camino live: el MISMO prepare_derived_authority de producción.
    live: dict[str, Any] = {}
    try:
        from src.runtime.deterministic_authority import prepare_derived_authority

        prep = await prepare_derived_authority(
            organization_id=org,
            question=question,
            evidence_items=main_chunks,
            enable_premise_closure=True,
            premise_evidence_search=(
                retriever_result.adapter.search
                if retriever_result.available and retriever_result.adapter is not None
                else None
            ),
            premise_retriever_status=retriever_result.to_public_dict(),
        )
        closure = prep.premise_closure
        rule_evaluations: list[dict[str, Any]] = []
        try:
            from src.knowledge.rule_compiler.evaluate import evaluate_rule

            for rule in (closure.rules if closure else ()):
                if not getattr(rule, "executable", False):
                    continue
                outcome = evaluate_rule(rule, {"value": "ABCFGEGE", "pattern": "&&&F"})
                rule_evaluations.append(
                    {
                        "rule_id": str(getattr(rule, "rule_id", "")),
                        "status": str(outcome.status),
                        "reason": str(outcome.reason)[:120],
                        "missing_premises": list(outcome.missing_premises[:6]),
                        "symbols": sorted(
                            name
                            for name in (getattr(rule, "properties", {}) or {})
                            if name.startswith("matching.symbol.")
                            and not name.endswith(".alphabet")
                        ),
                        "operator": str(
                            (
                                getattr(rule, "properties", {}).get("matching.operator")
                                or type("X", (), {"value": ""})()
                            ).value
                        ),
                        "statement": _safe_excerpt(getattr(rule, "statement", ""), 120),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            rule_evaluations.append(
                {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
            )
        grounded = prep.grounded_reasoning
        live = {
            "status": prep.status,
            "has_authority": prep.has_authority,
            "error_stage": prep.error_stage,
            "error_code": prep.error_code,
            "error_message": prep.error_message,
            "answer_state": list(prep.answer_state()),
            "missing_premises": list(prep.missing_premises[:12]),
            "query_local_executable": (
                len([rule for rule in (closure.rules if closure else ()) if getattr(rule, "executable", False)])
            ),
            "closure_termination": getattr(closure, "termination", None),
            "closure_evidence_added": len(getattr(closure, "evidence", ()) or ()) if closure else 0,
            "rule_evaluations": rule_evaluations,
            "derived_claims": [
                claim.to_public_dict()
                if hasattr(claim, "to_public_dict")
                else str(claim)
                for claim in (prep.derived_claims or ())
            ][:4],
            "grounded_answerability": str(
                getattr(grounded, "answerability", "") or ""
            ),
            "closure_rules": [
                {
                    "rule_id": str(getattr(rule, "rule_id", "")),
                    "state": str(getattr(rule, "verification_state", "")),
                    "executable": bool(getattr(rule, "executable", False)),
                    "missing_premises": list(getattr(rule, "missing_premises", ()) or ())[:6],
                    "properties": sorted((getattr(rule, "properties", {}) or {}).keys())[:10],
                    "evidence_ids": [
                        str(getattr(evidence, "evidence_id", ""))
                        for evidence in (getattr(rule, "provenance", ()) or ())
                    ][:6],
                }
                for rule in (closure.rules[:12] if closure else ())
            ],
            "envelope": (
                prep.authoritative_envelope.to_public_dict()
                if prep.authoritative_envelope is not None
                and hasattr(prep.authoritative_envelope, "to_public_dict")
                else None
            ),
            "steps": prep.steps,
        }
    except Exception as exc:  # noqa: BLE001
        live = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    report["live_prepare"] = live
    report["root_cause"] = _classify_root_cause(report)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live premise audit (real deps).")
    parser.add_argument("--org", required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--document", default=None)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--worker-sha", default="")
    parser.add_argument("--worker-timestamp", default="")
    parser.add_argument("--out", type=Path, default=Path("artifacts/live-premise-audit"))
    args = parser.parse_args(argv)

    report = asyncio.run(
        run_audit(
            org=UUID(args.org),
            question=args.question,
            source_id=UUID(args.source) if args.source else None,
            document_id=UUID(args.document) if args.document else None,
            worker_sha=args.worker_sha,
            worker_timestamp=args.worker_timestamp,
        )
    )
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = args.out / f"{stamp}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "root_cause": report["root_cause"],
                "parser_provenance": (report.get("parser_provenance") or {}).get(
                    "status"
                ),
                "report": str(path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
