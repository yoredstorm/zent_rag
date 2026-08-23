# =============================================================================
# ZENT Evaluation Engine — CLI
# =============================================================================
# Runner de evaluación end-to-end con persistencia Postgres y comparación
# de versiones (regresión). Requiere el stack docker arriba (API + DB).
#
# Uso (dentro del contenedor api):
#   docker compose exec api python src/scripts/eval_engine.py \
#       import-dataset --golden src/verticals/demo_farmacia/golden/rag_farmacia.json
#
#   docker compose exec api python src/scripts/eval_engine.py \
#       run --dataset-id <uuid> --target rag
#
#   docker compose exec api python src/scripts/eval_engine.py \
#       run --dataset-id <uuid> --target agent --agent-id <uuid>
#
#   docker compose exec api python src/scripts/eval_engine.py \
#       compare --baseline <run-uuid> --current <run-uuid>
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from src.rag.evaluation.store import (
    ensure_eval_engine_tables,
    get_dataset,
    get_eval_run,
    list_datasets,
    list_eval_runs,
    save_dataset,
    save_eval_run,
)

DEFAULT_ORGANIZATION = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_USER = UUID("00000000-0000-0000-0000-000000000002")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


async def _cmd_import(args: argparse.Namespace) -> None:
    from src.rag.evaluation.datasets import dataset_to_payload, load_dataset_file

    await ensure_eval_engine_tables()
    dataset = load_dataset_file(args.golden)
    dataset_id = await save_dataset(
        args.organization,
        args.name or dataset.name,
        dataset_to_payload(dataset),
        schema_version=dataset.schema_version,
        weights=dataset.weights,
        metadata=dataset.metadata,
    )
    _print_json(
        {
            "status": "imported",
            "dataset_id": str(dataset_id),
            "name": args.name or dataset.name,
            "cases": dataset.case_count,
        }
    )


async def _build_rag_target(args, organization_id, user_id):
    from src.api.deps import get_rag_orchestrator
    from src.rag.evaluation.snapshot import build_rag_snapshot, compute_version_id
    from src.rag.evaluation.targets import RAGTarget

    orchestrator = get_rag_orchestrator()
    target = RAGTarget(
        orchestrator,
        organization_id,
        user_id,
        target_id=args.kb_id,
        target_name="rag-pipeline",
    )
    organization = await _get_organization(organization_id)
    knowledge_base = None
    if args.kb_id is not None:
        from src.api.deps import get_kb_repo

        knowledge_base = await get_kb_repo().get_kb(organization_id, args.kb_id)
    snapshot = build_rag_snapshot(organization, knowledge_base)
    return target, snapshot, compute_version_id(snapshot)


async def _get_organization(organization_id: UUID):
    from src.api.deps import get_organization_repo

    organization = await get_organization_repo().get_by_id(organization_id)
    if organization is None:
        raise RuntimeError(f"Organization not found: {organization_id}")
    return organization


async def _build_agent_target(args, organization_id, user_id):
    from src.api.deps import get_agent_repo, get_agent_runtime
    from src.rag.evaluation.snapshot import build_agent_snapshot, compute_version_id
    from src.rag.evaluation.targets import AgentTarget

    if args.agent_id is None:
        raise RuntimeError("--agent-id es obligatorio con --target agent")
    agent = await get_agent_repo().get_agent(organization_id, args.agent_id)
    if agent is None:
        raise RuntimeError(f"Agent not found: {args.agent_id}")
    organization = await _get_organization(organization_id)
    runtime = get_agent_runtime()
    target = AgentTarget(
        runtime,
        agent,
        organization_id,
        user_id,
        org_config=organization.config_json or {},
        permissions=frozenset({"*"}),
    )
    snapshot = build_agent_snapshot(agent, organization.config_json or {})
    return target, snapshot, compute_version_id(snapshot)


async def _cmd_run(args: argparse.Namespace) -> None:
    from src.api.deps import get_llm_provider
    from src.core.config import get_settings
    from src.rag.evaluation.datasets import load_dataset
    from src.rag.evaluation.judge import LLMJudge
    from src.rag.evaluation.runner import EvalRunner

    await ensure_eval_engine_tables()
    dataset_row = await get_dataset(args.organization, args.dataset_id)
    if dataset_row is None:
        raise RuntimeError(f"Dataset not found: {args.dataset_id}")
    dataset = load_dataset(dataset_row["cases"], name=dataset_row["name"])
    dataset.weights = dataset_row.get("weights") or {}

    if args.target == "agent":
        target, snapshot, version_id = await _build_agent_target(
            args, args.organization, args.user_id
        )
    else:
        target, snapshot, version_id = await _build_rag_target(
            args, args.organization, args.user_id
        )

    settings = get_settings()
    judge = LLMJudge(
        get_llm_provider(),
        model=args.judge_model or settings.EVAL_JUDGE_MODEL,
        enabled=not args.no_judge,
    )
    runner = EvalRunner(target, judge)
    summary = await runner.run(
        dataset,
        version_snapshot=snapshot,
        version_id=version_id,
    )
    summary["dataset_id"] = str(args.dataset_id)

    await save_eval_run(args.organization, summary)

    output = {k: v for k, v in summary.items() if k != "cases"}
    output["cases"] = [
        {
            "case_id": c["case_id"],
            "status": c["status"],
            "composite": c["scores"]["composite"],
            "answer_preview": (c["answer"] or "")[:120],
        }
        for c in summary["cases"]
    ]
    _print_json(output)


async def _cmd_list(args: argparse.Namespace) -> None:
    await ensure_eval_engine_tables()
    datasets = await list_datasets(args.organization)
    runs = await list_eval_runs(args.organization, limit=args.limit)
    _print_json({"datasets": datasets, "runs": runs})


async def _cmd_show(args: argparse.Namespace) -> None:
    await ensure_eval_engine_tables()
    run = await get_eval_run(args.organization, args.run_id)
    if run is None:
        raise RuntimeError(f"Run not found: {args.run_id}")
    _print_json(run)


async def _cmd_compare(args: argparse.Namespace) -> None:
    from src.rag.evaluation.regression import compare_runs

    await ensure_eval_engine_tables()
    baseline = await get_eval_run(args.organization, args.baseline)
    current = await get_eval_run(args.organization, args.current)
    if baseline is None:
        raise RuntimeError(f"Baseline run not found: {args.baseline}")
    if current is None:
        raise RuntimeError(f"Current run not found: {args.current}")
    report = compare_runs(current, baseline)
    _print_json(report)
    if report["overall"] == "fail":
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ZENT Evaluation Engine CLI")
    parser.add_argument("--organization", type=UUID, default=DEFAULT_ORGANIZATION)
    parser.add_argument("--user-id", type=UUID, default=DEFAULT_USER)
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import-dataset", help="Importar golden set (schema v2)")
    p_import.add_argument("--golden", required=True)
    p_import.add_argument("--name", default=None)

    p_run = sub.add_parser("run", help="Ejecutar evaluación de un dataset")
    p_run.add_argument("--dataset-id", type=UUID, required=True)
    p_run.add_argument("--target", choices=["rag", "agent"], default="rag")
    p_run.add_argument("--agent-id", type=UUID, default=None)
    p_run.add_argument("--kb-id", type=UUID, default=None)
    p_run.add_argument("--no-judge", action="store_true", help="Desactivar LLM-judge")
    p_run.add_argument("--judge-model", default=None)

    p_list = sub.add_parser("list", help="Listar datasets y runs")
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="Detalle de un run (con casos)")
    p_show.add_argument("--run-id", type=UUID, required=True)

    p_compare = sub.add_parser("compare", help="Comparar runs (regresión)")
    p_compare.add_argument("--baseline", type=UUID, required=True)
    p_compare.add_argument("--current", type=UUID, required=True)

    return parser


def main() -> None:
    args = _parser().parse_args()
    handlers = {
        "import-dataset": _cmd_import,
        "run": _cmd_run,
        "list": _cmd_list,
        "show": _cmd_show,
        "compare": _cmd_compare,
    }
    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main()
