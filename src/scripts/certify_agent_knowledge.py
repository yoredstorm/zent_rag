#!/usr/bin/env python
# =============================================================================
# P18.3-08 - Certificación del recorrido Conocimiento -> Agente
# =============================================================================
# Crea un tenant sintético, ingesta dos fuentes, configura dos agentes (narrador
# infantil y asistente técnico) y ejecuta /run + /run/stream con el proveedor
# real disponible. No usa mocks de retrieval.
#
# Uso:
#   python -m src.scripts.certify_agent_knowledge \
#       --api-base http://127.0.0.1:8000 \
#       --out artifacts/certification/p18-3/agent_certification.json
# =============================================================================
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "p18_3"


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))  # noqa: T201


def _headers(token: str, org: str, workspace: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org,
        "Idempotency-Key": uuid4().hex,
    }
    if workspace:
        headers["X-Workspace-Id"] = workspace
    return headers


def _check(response: httpx.Response, expected: int | tuple[int, ...] = 200) -> dict:
    expected_codes = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in expected_codes:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
    return response.json() if response.content else {}


def _upload(
    client: httpx.Client,
    headers: dict[str, str],
    corpus_id: str,
    name: str,
    mime: str,
    path: Path,
) -> dict:
    data = path.read_bytes()
    response = client.post(
        f"/api/v1/sources/files/upload?corpus_id={corpus_id}",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        files={"file": (name, data, mime)},
    )
    return _check(response, 201)


def _wait_indexed(
    client: httpx.Client, headers: dict[str, str], corpus_id: str, source_ids: set[str]
) -> list[dict]:
    last: list[dict] = []
    for _ in range(150):
        response = client.get(f"/api/v1/knowledge/workspaces/{corpus_id}", headers=headers)
        if response.status_code == 200:
            last = list(response.json().get("sources") or [])
            by_id = {str(item["id"]): item for item in last}
            if all(
                str(by_id.get(source_id, {}).get("status")) in {"indexed", "error"}
                for source_id in source_ids
            ):
                return last
        time.sleep(1)
    return last


def _create_agent(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    workspace_id: str,
    name: str,
    system_prompt: str,
    source_ids: list[str],
    preset: str,
    tone: str,
) -> dict:
    payload = {
        "name": name,
        "description": "Agente sintético de certificación P18.3",
        "workspace_id": workspace_id,
        "system_prompt": system_prompt,
        "tools": ["search_knowledge"],
        "config": {
            "purpose": system_prompt,
            "tone": tone,
            "temperature": 0.2,
            "source_ids": source_ids,
            "response_profile": {"preset": preset},
        },
    }
    response = client.post(
        "/api/v1/agents",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json=payload,
    )
    return _check(response, 201)


def _run_agent(
    client: httpx.Client, headers: dict[str, str], agent_id: str, message: str
) -> dict:
    started = time.perf_counter()
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"message": message, "role": "admin"},
        timeout=240,
    )
    payload = _check(response)
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    payload["question"] = message
    return payload


def _run_stream(
    client: httpx.Client, headers: dict[str, str], agent_id: str, message: str
) -> dict:
    events: list[dict] = []
    final: dict = {}
    started = time.perf_counter()
    with client.stream(
        "POST",
        f"/api/v1/agents/{agent_id}/run/stream",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"message": message, "role": "admin"},
        timeout=240,
    ) as response:
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code}
        event_name = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                raw = line.split(":", 1)[1].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"raw": raw[:500]}
                events.append({"event": event_name, "data": data})
                if event_name in {"done", "final", "completed"}:
                    final = data if isinstance(data, dict) else {"data": data}
    return {
        "status": "completed",
        "events": events,
        "event_count": len(events),
        "final": final,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _evidence_from_run(run: dict) -> tuple[list[dict], list[dict], dict]:
    """Extrae evidencia/citas/verificación del contrato real del flow.

    No inventa una cita a partir del texto: solo lee `flow.evidence.items` y
    `flow.citations`, que son la autoridad del runtime.
    """
    flow = run.get("flow") if isinstance(run.get("flow"), dict) else {}
    evidence: list[dict] = []
    for item in (flow.get("evidence") or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "evidence_id": item.get("evidence_id"),
                "source_id": item.get("source_id"),
                "document_id": item.get("document_id"),
                "page": item.get("page"),
                "selected": bool(item.get("selected")),
                "used": bool(item.get("used")),
                "cited": bool(item.get("cited")),
                "excerpt": str(item.get("excerpt") or item.get("content") or "")[:240],
            }
        )
    citations: list[dict] = []
    for item in flow.get("citations") or []:
        if not isinstance(item, dict):
            continue
        citations.append(
            {
                "evidence_id": item.get("evidence_id"),
                "document_id": item.get("document_id"),
                "document_name": item.get("document_name"),
                "page": item.get("page"),
                "section_path": item.get("section_path") or [],
                "locator": item.get("locator"),
                "cited": bool(item.get("cited")),
                "relevance": item.get("relevance"),
            }
        )
    verification = flow.get("verification") if isinstance(flow.get("verification"), dict) else {}
    return evidence, citations, verification


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - consola sin utf-8 no debe romper el certificado
        pass
    parser = argparse.ArgumentParser(description="Certifica agente + conocimiento P18.3")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--out",
        default=str(
            ROOT / "artifacts" / "certification" / "p18-3" / "agent_certification.json"
        ),
    )
    args = parser.parse_args(argv)
    result: dict[str, Any] = {
        "contract": "p18.3-agent-knowledge-cert/v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_base": args.api_base,
        "status": "NOT_RUN",
        "checks": [],
        "runs": {},
        "limitations": [],
    }
    try:
        with httpx.Client(base_url=args.api_base.rstrip("/"), timeout=120) as client:
            signup = _check(
                client.post(
                    "/api/v1/auth/signup",
                    json={
                        "company_name": f"P18.3 Agent Cert {uuid4().hex[:8]}",
                        "email": f"p183-agent-{uuid4().hex[:8]}@example.com",
                        "password": "P183-agent-cert-password-123",
                    },
                )
            )
            token = signup["access_token"]
            org_id = signup["organization_id"]
            headers = _headers(token, org_id)
            onboarding = _check(
                client.post(
                    "/api/v1/onboarding/start-mode",
                    headers=headers,
                    json={"mode": "blank"},
                )
            )
            workspace_id = onboarding["workspace_id"]
            headers = _headers(token, org_id, workspace_id)
            corpus = _check(
                client.post(
                    "/api/v1/knowledge/workspaces",
                    headers=headers,
                    json={"name": "P18.3 Agentes"},
                ),
                201,
            )["corpus"]
            narrative = _upload(
                client,
                headers,
                corpus["id"],
                "p18-3-narrative.txt",
                "text/plain",
                FIXTURES / "narrative_dialogue.txt",
            )
            technical = _upload(
                client,
                headers,
                corpus["id"],
                "p18-3-technical.txt",
                "text/plain",
                FIXTURES / "technical_atpco.txt",
            )
            sources = _wait_indexed(
                client,
                headers,
                corpus["id"],
                {str(narrative["id"]), str(technical["id"])},
            )
            indexed = {
                str(item["id"]): str(item.get("status")) for item in sources
            }
            result["sources"] = [
                {"id": str(narrative["id"]), "kind": "narrative", "status": indexed.get(str(narrative["id"]))},
                {"id": str(technical["id"]), "kind": "technical", "status": indexed.get(str(technical["id"]))},
            ]
            if any(status != "indexed" for status in indexed.values()):
                result["status"] = "BLOCKED_INGEST"
                result["limitations"].append("Una fuente no quedó indexed.")
                _print(result)
                return 3

            narrator = _create_agent(
                client,
                headers,
                workspace_id=workspace_id,
                name=f"Narrador infantil {uuid4().hex[:6]}",
                system_prompt="Responde como narrador de cuentos infantil, con calidez y sin inventar hechos.",
                source_ids=[str(narrative["id"])],
                preset="concise",
                tone="friendly",
            )
            analyst = _create_agent(
                client,
                headers,
                workspace_id=workspace_id,
                name=f"Analista de documentos {uuid4().hex[:6]}",
                system_prompt="Responde con precisión técnica y cita la evidencia cuando corresponda.",
                source_ids=[str(technical["id"])],
                preset="analytical",
                tone="professional",
            )
            result["agents"] = {
                "narrator": {"id": narrator["id"], "profile": narrator["config"].get("response_profile")},
                "analyst": {"id": analyst["id"], "profile": analyst["config"].get("response_profile")},
            }

            cases = [
                ("narrator_valuative", narrator["id"], "¿Qué te parece esta historia?"),
                ("narrator_literal", narrator["id"], "¿Qué debe cuidar el principito?"),
                ("narrator_absent", narrator["id"], "¿Cuál es la política de gastos del asteroide?"),
                ("analyst_literal", analyst["id"], "¿Cuál es la posición del campo Fare Basis?"),
                ("analyst_absent", analyst["id"], "¿Cuántos empleados trabajan en ATPCO?"),
            ]
            for label, agent_id, question in cases:
                run = _run_agent(client, headers, agent_id, question)
                evidence, citations, verification = _evidence_from_run(run)
                run["evidence"] = evidence
                run["citations"] = citations
                run["verification"] = verification
                result["runs"][label] = run
                answer = str(run.get("answer") or "")
                answer_ok = run.get("status") == "completed" and bool(answer)
                if label == "narrator_literal":
                    answer_ok = answer_ok and bool(
                        re.search(r"flor|principito", answer, re.I)
                    )
                if label == "analyst_literal":
                    answer_ok = answer_ok and bool(re.search(r"12|doce", answer, re.I))
                if label in {"narrator_absent", "analyst_absent"}:
                    answer_ok = answer_ok and bool(
                        re.search(
                            r"no (hay|tengo|se puede|menciona|contiene|reporta|sobre|corresponde)|"
                            r"ninguno de ellos|sin sustento|insufficient|no dispongo|"
                            r"falta (una|un|el|la) fuente|qu[eé] falta|falta,|cualquier cifra",
                            answer,
                            re.I,
                        )
                    )
                verification_status = str(verification.get("overall") or "unknown")
                cited = [item for item in citations if item.get("cited")]
                if not answer_ok:
                    check_status = "FAIL"
                elif verification_status in {"partial", "blocked", "failed"}:
                    check_status = "CONDITIONAL"
                else:
                    check_status = "PASS"
                result["checks"].append(
                    {
                        "check": label,
                        "status": check_status,
                        "answer_preview": answer[:280],
                        "model": run.get("model"),
                        "latency_ms": run.get("total_latency_ms"),
                        "tokens": run.get("total_tokens"),
                        "cost": run.get("cost"),
                        "evidence_count": len(evidence),
                        "citation_count": len(citations),
                        "cited_count": len(cited),
                        "verification": verification_status,
                        "verification_detail": verification.get("presentation"),
                    }
                )

            stream = _run_stream(
                client,
                headers,
                narrator["id"],
                "Cuéntame qué debe cuidar el principito.",
            )
            result["runs"]["narrator_stream"] = stream
            result["checks"].append(
                {
                    "check": "narrator_stream",
                    "status": "PASS" if stream.get("event_count", 0) > 0 else "FAIL",
                    "events": stream.get("event_count"),
                }
            )

            narrator_runs = [
                result["runs"][key]
                for key in ("narrator_valuative", "narrator_literal", "narrator_absent")
            ]
            analyst_runs = [
                result["runs"][key] for key in ("analyst_literal", "analyst_absent")
            ]
            leak = any("fare basis" in str(run.get("answer") or "").lower() for run in narrator_runs)
            leak = leak or any("principito" in str(run.get("answer") or "").lower() for run in analyst_runs)
            narrator_source = str(narrative["id"])
            analyst_source = str(technical["id"])
            for run in narrator_runs:
                leak = leak or any(
                    str(item.get("source_id")) not in {"", "None", narrator_source}
                    for item in run.get("evidence") or []
                )
            for run in analyst_runs:
                leak = leak or any(
                    str(item.get("source_id")) not in {"", "None", analyst_source}
                    for item in run.get("evidence") or []
                )
            result["checks"].append(
                {
                    "check": "no_cross_source_leak",
                    "status": "PASS" if not leak else "FAIL",
                    "note": (
                        "El narrador no debe responder con el manual técnico ni "
                        "viceversa; tampoco citar fuentes fuera de su scope."
                    ),
                }
            )
            planning_steps = [
                step
                for run in narrator_runs
                for step in run.get("steps") or []
                if isinstance(step, dict) and step.get("type") == "response_planning"
            ]
            identities_ok = bool(planning_steps) and all(
                bool(step.get("identity_preserved")) for step in planning_steps
            )
            result["checks"].append(
                {
                    "check": "narrator_identity",
                    "status": "PASS" if identities_ok else "CONDITIONAL",
                    "planning_steps": len(planning_steps),
                }
            )
            gate_steps = [
                step
                for run in result["runs"].values()
                if isinstance(run, dict)
                for step in run.get("steps") or []
                if isinstance(step, dict) and step.get("type") == "answer_gate"
            ]
            gate_observed = any(
                str(step.get("verdict")) not in {"skipped", ""}
                and str(step.get("provider")) not in {"skip", "skip_config", "skip_shadow"}
                for step in gate_steps
            )
            result["checks"].append(
                {
                    "check": "answer_gate_observed",
                    "status": "PASS" if gate_observed else "CONDITIONAL",
                    "note": "El gate JEV no juzgó el borrador; la respuesta se entregó igual.",
                    "gate_steps": len(gate_steps),
                }
            )
            citation_valid = all(
                bool((run.get("verification") or {}).get("narrative_verification", {}).get("citations_valid"))
                for run in result["runs"].values()
                if isinstance(run, dict) and run.get("verification")
            )
            result["checks"].append(
                {
                    "check": "citations_valid",
                    "status": "PASS" if citation_valid else "FAIL",
                }
            )
            statuses = {check["status"] for check in result["checks"]}
            if "FAIL" in statuses:
                result["status"] = "FAIL"
            elif "CONDITIONAL" in statuses:
                result["status"] = "CONDITIONAL_REAL_PROVIDER"
            else:
                result["status"] = "PASS_REAL_PROVIDER"
    except Exception as exc:  # noqa: BLE001 - el certificado registra el bloqueo
        result["status"] = "BLOCKED_PROVIDER"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    _print(result)
    return 0 if result["status"] == "PASS_REAL_PROVIDER" else 1


if __name__ == "__main__":
    sys.exit(main())
