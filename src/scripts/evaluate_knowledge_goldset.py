#!/usr/bin/env python
# =============================================================================
# P18.3-02 - Harness de evaluación del chat acotado por corpus
# =============================================================================
# Ejecuta el gold set contra el endpoint real:
#   POST /api/v1/knowledge/workspaces/{corpus_id}/chat
# con autenticación, workspace y corpus explícitos. No crea un segundo
# evaluador: mide la respuesta, citas, claims y candidatos que devuelve la API.
#
# Uso:
#   set ZENT_EVAL_TOKEN=...            (nunca se imprime)
#   set ZENT_EVAL_ORG=...
#   set ZENT_EVAL_WORKSPACE=...
#   python -m src.scripts.evaluate_knowledge_goldset run \
#       --corpus-id <uuid> --split dev --label baseline
#
#   python -m src.scripts.evaluate_knowledge_goldset compare \
#       --baseline artifacts/certification/p18-3/eval/baseline/metrics.json \
#       --candidate artifacts/certification/p18-3/eval/candidate/metrics.json
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.rag.evaluation.goldset_v1 import GOLDSET, validate_goldset

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "artifacts" / "certification" / "p18-3" / "eval"
_ABSTAIN_MARKERS = (
    "no tengo suficiente informacion",
    "no hay informacion suficiente",
    "no se puede responder",
    "no se puede determinar",
    "no esta en el contexto",
    "no aparece en el contexto",
    "no se menciona",
    "no menciona",
    "no contiene",
    "no hay evidencia",
    "no encuentro",
    "insufficient",
    "no dispongo de",
)
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "y", "o", "que", "en", "por", "para", "con", "sin", "es", "son", "se",
    "su", "sus", "lo", "como", "más", "mas", "no", "sí", "si", "the", "of",
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9áéíóúüñ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in _norm(value).split()
        if token and token not in _STOPWORDS and len(token) > 1
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _is_abstention(answer: str) -> bool:
    normalized = _norm(answer)
    return any(marker in normalized for marker in _ABSTAIN_MARKERS)


def _answer_matches(answer: str, case: dict[str, Any]) -> bool:
    if case.get("expected_behavior") == "abstain":
        return _is_abstention(answer)
    normalized = _norm(answer)
    candidates = [case.get("gold_answer") or "", *(case.get("accepted_variants") or [])]
    for candidate in candidates:
        target = _norm(candidate)
        if target and (target == normalized or target in normalized):
            return True
    # Para tabulares, comparar el número exacto evita aceptar una respuesta
    # larga que menciona el número equivocado.
    if case.get("expected_claim_type") == "tabular_calculation":
        target_numbers = re.findall(r"\d+(?:[.,]\d+)?", _norm(case.get("gold_answer") or ""))
        answer_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", normalized))
        if target_numbers and all(number in answer_numbers for number in target_numbers):
            return True
    return False


def _behavior_correct(answer: str, case: dict[str, Any]) -> bool:
    behavior = case.get("expected_behavior")
    abstained = _is_abstention(answer)
    if behavior == "abstain":
        return abstained
    if behavior == "contradiction":
        return not abstained and bool(_tokens(answer) & _tokens(case.get("gold_answer")))
    return not abstained and _answer_matches(answer, case)


def _citation_supports(citation: dict[str, Any], evidence: dict[str, Any]) -> bool:
    expected_page = evidence.get("page")
    cited_page = citation.get("page")
    if expected_page and cited_page and int(expected_page) != int(cited_page):
        return False
    expected_excerpt = _norm(evidence.get("verbatim_excerpt"))
    cited_excerpt = _norm(citation.get("excerpt"))
    if not expected_excerpt or not cited_excerpt:
        return False
    if expected_excerpt in cited_excerpt or cited_excerpt in expected_excerpt:
        return True
    expected_tokens = _tokens(expected_excerpt)
    cited_tokens = _tokens(cited_excerpt)
    if not expected_tokens:
        return False
    return len(expected_tokens & cited_tokens) / len(expected_tokens) >= 0.5


def _retrieval_matches(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    return _citation_supports(candidate, evidence)


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    result: dict[str, Any] = {}
    for name, items in sorted(groups.items()):
        result[name] = {
            "cases": len(items),
            "answer_accuracy": _ratio(items, "answer_correct"),
            "behavior_accuracy": _ratio(items, "behavior_correct"),
            "citation_precision": _ratio(items, "citation_precision"),
            "grounded_claim_precision": _ratio(items, "grounded_claim_precision"),
            "retrieval_recall_at_k": _ratio(items, "retrieval_recall_at_k"),
            "abstention_correctness": _ratio(
                [item for item in items if item.get("expected_behavior") == "abstain"],
                "behavior_correct",
            ),
            "provider_errors": sum(1 for item in items if item.get("status") != "COMPLETED"),
        }
    return result


def _ratio(items: list[dict[str, Any]], field: str) -> float | None:
    values = [item.get(field) for item in items if isinstance(item.get(field), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _case_metrics(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    grounded = response.get("grounded") or {}
    answer = str(grounded.get("answer") or "")
    citations = list(grounded.get("citations") or [])
    claims = list(grounded.get("claims") or [])
    candidates = list((response.get("retrieval_debug") or {}).get("candidates") or [])
    expected_evidence = list(case.get("supporting_evidence") or [])
    supported_citations = sum(
        1
        for citation in citations
        if any(_citation_supports(citation, evidence) for evidence in expected_evidence)
    )
    expected_matches = sum(
        1
        for evidence in expected_evidence
        if any(_retrieval_matches(candidate, evidence) for candidate in candidates)
    )
    supported_claims = sum(
        1 for claim in claims if str(claim.get("status") or "").lower() == "supported"
    )
    locators = [
        citation
        for citation in citations
        if citation.get("locator") and citation.get("page") and citation.get("document_id")
    ]
    has_debug = bool(response.get("retrieval_debug"))
    return {
        "case_id": case.get("case_id"),
        "family": case.get("family"),
        "difficulty": case.get("difficulty"),
        "split": case.get("split"),
        "status": "COMPLETED",
        "answer": answer,
        "expected_behavior": case.get("expected_behavior"),
        "observed_abstention": _is_abstention(answer),
        "answer_correct": _answer_matches(answer, case) if case.get("expected_behavior") != "abstain" else None,
        "behavior_correct": _behavior_correct(answer, case),
        "citation_count": len(citations),
        "citation_locator_count": len(locators),
        "citation_precision": (
            round(supported_citations / len(citations), 4) if citations else None
        ),
        "grounded_claim_precision": (
            round(supported_claims / len(claims), 4) if claims else None
        ),
        "retrieval_recall_at_k": (
            round(expected_matches / len(expected_evidence), 4)
            if expected_evidence and has_debug
            else None
        ),
        "retrieval_candidates_available": has_debug,
        "citations": citations,
        "claims": claims,
        "evidence_ids": grounded.get("evidence_ids") or [],
        "telemetry": response.get("telemetry") or {},
        "retrieval_scope": response.get("retrieval_scope") or {},
        "candidates": candidates,
        "error": None,
    }


def _failure_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row.get("case_id"),
        "family": row.get("family"),
        "status": row.get("status"),
        "behavior_correct": row.get("behavior_correct"),
        "answer_correct": row.get("answer_correct"),
        "citation_precision": row.get("citation_precision"),
        "answer": (row.get("answer") or "")[:220],
        "error": row.get("error"),
    }


def _write_failure_catalog(path: Path, failures: list[dict[str, Any]]) -> None:
    lines = [
        "# P18.3 failure catalog",
        "",
        "Generado por `evaluate_knowledge_goldset`; no sustituye revisión humana.",
        "",
        "| case_id | family | status | behavior | answer | citation_precision | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for failure in failures:
        lines.append(
            "| {case_id} | {family} | {status} | {behavior} | {answer} | {citation_precision} | {error} |".format(
                case_id=failure.get("case_id"),
                family=failure.get("family"),
                status=failure.get("status"),
                behavior=failure.get("behavior_correct"),
                answer=str(failure.get("answer") or "").replace("|", "/")[:160],
                citation_precision=failure.get("citation_precision"),
                error=str(failure.get("error") or "").replace("|", "/")[:160],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run_case(
    client: httpx.AsyncClient,
    *,
    corpus_id: str,
    case: dict[str, Any],
    source_map: dict[str, str],
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    source_id = source_map.get(str(case.get("source_ref") or ""))
    body: dict[str, Any] = {"query": case.get("question"), "debug": True}
    if source_id:
        body["source_ids"] = [source_id]
    last_error: str | None = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = await client.post(
                f"/api/v1/knowledge/workspaces/{corpus_id}/chat",
                json=body,
                timeout=timeout,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}: {response.text[:240]}"
                if response.status_code in (429, 502, 503, 504):
                    return {
                        **_case_metrics(case, {"grounded": {"answer": ""}}),
                        "status": "BLOCKED_PROVIDER",
                        "error": last_error,
                        "http_status": response.status_code,
                        "elapsed_ms": elapsed_ms,
                    }
                return {
                    **_case_metrics(case, {"grounded": {"answer": ""}}),
                    "status": "ERROR",
                    "error": last_error,
                    "http_status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                }
            payload = response.json()
            metrics = _case_metrics(case, payload)
            metrics["elapsed_ms"] = elapsed_ms
            metrics["http_status"] = response.status_code
            return metrics
        except Exception as exc:  # noqa: BLE001 - el harness registra, no oculta
            last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
        await asyncio.sleep(min(2**attempt, 8))
    return {
        **_case_metrics(case, {"grounded": {"answer": ""}}),
        "status": "BLOCKED_PROVIDER",
        "error": last_error,
    }


async def run_eval(args: argparse.Namespace) -> int:
    validation = validate_goldset(Path(args.goldset))
    if validation["status"] == "FAIL":
        print(json.dumps(validation, indent=2, ensure_ascii=False))  # noqa: T201
        return 1
    token = os.environ.get(args.token_env, "").strip()
    organization_id = args.organization_id or os.environ.get("ZENT_EVAL_ORG", "").strip()
    workspace_id = args.workspace_id or os.environ.get("ZENT_EVAL_WORKSPACE", "").strip()
    if not token or not organization_id or not workspace_id or not args.corpus_id:
        print(  # noqa: T201
            json.dumps(
                {
                    "status": "NOT_RUN",
                    "reason": "faltan token/organization/workspace/corpus",
                    "token_env": args.token_env,
                },
                indent=2,
            )
        )
        return 2
    cases = _load_jsonl(Path(args.goldset))
    if args.split != "all":
        cases = [case for case in cases if case.get("split") == args.split]
    if args.max_cases:
        cases = cases[: args.max_cases]
    source_map: dict[str, str] = {}
    if args.source_map:
        source_map = json.loads(Path(args.source_map).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": organization_id,
        "X-Workspace-Id": workspace_id,
        "Accept": "application/json",
    }
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.api_base.rstrip("/"), headers=headers) as client:
        for case in cases:
            row = await _run_case(
                client,
                corpus_id=args.corpus_id,
                case=case,
                source_map=source_map,
                timeout=args.timeout,
                retries=args.retries,
            )
            rows.append(row)
            print(  # noqa: T201
                f"[{row['case_id']}] {row['status']} behavior={row.get('behavior_correct')} "
                f"citations={row.get('citation_count')} error={row.get('error')}"
            )
    per_case = out_dir / "per_case.jsonl"
    per_case.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n",
        encoding="utf-8",
    )
    provider_errors = sum(1 for row in rows if row.get("status") != "COMPLETED")
    invariants = {
        "cross_tenant_or_out_of_scope": sum(
            1
            for row in rows
            for candidate in row.get("candidates") or []
            if candidate.get("source_id")
            and source_map
            and candidate["source_id"] not in set(source_map.values())
        ),
        "citations_without_locator": sum(
            1
            for row in rows
            for citation in row.get("citations") or []
            if not citation.get("locator") or not citation.get("document_id") or not citation.get("page")
        ),
        "answers_without_citation_when_expected": sum(
            1
            for row in rows
            if row.get("expected_behavior") != "abstain"
            and row.get("behavior_correct")
            and row.get("citation_count") == 0
        ),
        "fabricated_citation_flags": 0,
    }
    metrics = {
        "status": (
            "COMPLETED" if provider_errors == 0 else ("BLOCKED_PROVIDER" if provider_errors == len(rows) else "PARTIAL")
        ),
        "label": args.label,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_base": args.api_base,
        "corpus_id": args.corpus_id,
        "split": args.split,
        "cases_total": len(cases),
        "cases_executed": len(rows),
        "provider_errors": provider_errors,
        "goldset_sha256": validation["goldset_sha256"],
        "fixtures_sha256": validation["fixtures_sha256"],
        "overall": {
            "answer_accuracy": _ratio(rows, "answer_correct"),
            "behavior_accuracy": _ratio(rows, "behavior_correct"),
            "citation_precision": _ratio(rows, "citation_precision"),
            "grounded_claim_precision": _ratio(rows, "grounded_claim_precision"),
            "retrieval_recall_at_k": _ratio(rows, "retrieval_recall_at_k"),
        },
        "by_family": _aggregate(rows, "family"),
        "by_difficulty": _aggregate(rows, "difficulty"),
        "invariants": invariants,
        "notes": [
            "retrieval_recall_at_k usa candidatos de retrieval_debug; no sustituye un gold set de chunks.",
            "citation_precision es heurística de solapamiento página/extracto.",
            "No se declara PASS humano: goldset en draft_not_approved.",
        ],
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    failures = [
        _failure_row(row)
        for row in rows
        if row.get("status") != "COMPLETED" or not row.get("behavior_correct")
    ]
    _write_failure_catalog(out_dir / "failure_catalog.md", failures)
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git está en PATH del repo
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        git_sha = "unknown"
    manifest = {
        "contract": "p18.3-eval-run/v1",
        "git_sha": git_sha,
        "label": args.label,
        "started_at": started_at,
        "finished_at": metrics["finished_at"],
        "api_base": args.api_base,
        "corpus_id": args.corpus_id,
        "workspace_id": workspace_id,
        "organization_id": organization_id,
        "token_env": args.token_env,
        "goldset": str(args.goldset),
        "goldset_sha256": validation["goldset_sha256"],
        "split": args.split,
        "cases": len(rows),
        "provider_errors": provider_errors,
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in metrics.items() if k != "by_family"}, indent=2, ensure_ascii=False))  # noqa: T201
    return 0 if provider_errors == 0 else 3


def compare_runs(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    keys = (
        "answer_accuracy",
        "behavior_accuracy",
        "citation_precision",
        "grounded_claim_precision",
        "retrieval_recall_at_k",
    )
    deltas: dict[str, Any] = {}
    regressions: list[str] = []
    for key in keys:
        before = (baseline.get("overall") or {}).get(key)
        after = (candidate.get("overall") or {}).get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = round(after - before, 4)
            deltas[key] = {"baseline": before, "candidate": after, "delta": delta}
            if delta < -0.02:
                regressions.append(key)
    return {
        "status": "REGRESSION" if regressions else "OK",
        "regressions": regressions,
        "deltas": deltas,
        "baseline_label": baseline.get("label"),
        "candidate_label": candidate.get("label"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P18.3 knowledge goldset harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--goldset", default=str(GOLDSET))
    run.add_argument("--api-base", default="http://127.0.0.1:8000")
    run.add_argument("--token-env", default="ZENT_EVAL_TOKEN")
    run.add_argument("--organization-id", default=None)
    run.add_argument("--workspace-id", default=None)
    run.add_argument("--corpus-id", required=True)
    run.add_argument("--source-map", default=None, help="JSON {source_ref: source_uuid}")
    run.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    run.add_argument("--max-cases", type=int, default=0)
    run.add_argument("--retries", type=int, default=0)
    run.add_argument("--timeout", type=float, default=180.0)
    run.add_argument("--label", default="baseline")
    run.add_argument("--out-dir", default=str(DEFAULT_OUT / "baseline"))
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return asyncio.run(run_eval(args))
    if args.command == "compare":
        result = compare_runs(Path(args.baseline), Path(args.candidate))
        print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201
        return 1 if result["status"] == "REGRESSION" else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
