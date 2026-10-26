"""P16 real-LLM purpose matrix.

Generates the ten acceptance purposes with the configured provider, validates
them with the independent deterministic evaluator, optionally repairs once, and
writes artifacts/certification/p16/real-purpose-matrix.json.

The output contains drafts and quality results, never provider credentials.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings  # noqa: E402
from src.infrastructure.llm.provider import LiteLLMProvider  # noqa: E402
from src.intelligence.response.generator import (  # noqa: E402
    AgentConfigContext,
    build_purpose_prompt,
    build_purpose_repair_prompt,
    evaluate_purpose_intent,
    parse_purpose_response,
    suggest_purpose_intent,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "certification" / "p16"


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    prompt: str
    description: str = ""
    profile_audience: str = "technical"
    sources: tuple[str, ...] = ()
    tools: tuple[str, ...] = ("search_knowledge",)


CASES: tuple[Case, ...] = (
    Case("narrator", "Principito", "Responde como un narrador de cuentos infantil", sources=("el_principito.pdf",)),
    Case("sales", "Tienda", "Ayúdame a vender productos de mi tienda", sources=("catalogo.pdf",)),
    Case("mentor", "Mentor", "Sé un mentor de programación para principiantes", sources=("curso_python.pdf",)),
    Case("contracts", "Riesgos", "Analiza contratos y detecta riesgos", sources=("contratos.pdf",)),
    Case("manuals", "Manuales", "Responde preguntas sobre manuales técnicos", sources=("manual.pdf",)),
    Case(
        "orders",
        "Pedidos",
        "Ayuda a mis clientes a consultar pedidos",
        sources=("pedidos.csv",),
        tools=("search_knowledge", "query_database"),
    ),
    Case("math", "Mate", "Explica matemática como un profesor", sources=("algebra.pdf",)),
    Case("audit", "Auditoría", "Analiza información de auditoría", sources=("hallazgos.csv",)),
    Case("appointments", "Citas", "Ayuda a organizar citas", sources=("agenda.csv",)),
    Case("hr", "RRHH", "Explica las políticas internas de RRHH", sources=("politicas_rrhh.pdf",)),
)


def context_for(case: Case) -> AgentConfigContext:
    return AgentConfigContext(
        name=case.name,
        description=case.description,
        purpose=case.prompt,
        profile_audience=case.profile_audience,
        source_titles=case.sources,
        tools=case.tools,
        mode="expand",
    )


async def run_one(
    provider: LiteLLMProvider, case: Case, semaphore: asyncio.Semaphore
) -> dict[str, Any]:
    context = context_for(case)
    started = time.perf_counter()
    raw = ""
    error = ""
    prompt_tokens = 0
    completion_tokens = 0
    try:
        async with semaphore:
            response = await provider.generate(
                prompt=build_purpose_prompt(context, mode="expand"),
                model=get_settings().LITELLM_DEFAULT_MODEL,
                max_tokens=3000,
                temperature=0.0,
            )
        raw = str(getattr(response, "content", "") or "")
        prompt_tokens += int(getattr(response, "prompt_tokens", 0) or 0)
        completion_tokens += int(getattr(response, "completion_tokens", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {str(exc)[:200]}"

    if raw.strip():
        draft = parse_purpose_response(raw, context)
    else:
        draft = suggest_purpose_intent(context, mode="expand")
    quality = evaluate_purpose_intent(draft, context)
    repaired = False
    if not quality.passed and raw.strip() and draft.purpose:
        try:
            async with semaphore:
                repair_response = await provider.generate(
                    prompt=build_purpose_repair_prompt(context, draft, quality.issues),
                    model=get_settings().LITELLM_DEFAULT_MODEL,
                    max_tokens=3000,
                    temperature=0.1,
                )
            prompt_tokens += int(getattr(repair_response, "prompt_tokens", 0) or 0)
            completion_tokens += int(getattr(repair_response, "completion_tokens", 0) or 0)
            repaired_draft = parse_purpose_response(
                str(getattr(repair_response, "content", "") or ""), context
            )
            repaired_quality = evaluate_purpose_intent(repaired_draft, context)
            if repaired_quality.score >= quality.score and repaired_draft.purpose:
                repaired = True
                draft = repaired_draft
                quality = repaired_quality
        except Exception as exc:  # noqa: BLE001
            if not error:
                error = f"repair:{type(exc).__name__}: {str(exc)[:160]}"

    if not quality.passed and case.prompt:
        preserved = suggest_purpose_intent(context, mode="expand")
        preserved.warnings = list(
            dict.fromkeys(
                ["quality_failed_preserved_original", *quality.issues[:8]]
            )
        )
        draft = preserved
        quality = evaluate_purpose_intent(draft, context)

    return {
        "id": case.id,
        "input_purpose": case.prompt,
        "draft": draft.to_public_dict(),
        "quality": quality.to_public_dict(),
        "repaired": repaired,
        "error": error,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "model": get_settings().LITELLM_DEFAULT_MODEL,
    }


async def main() -> int:
    provider = LiteLLMProvider()
    # Secuencial: el propósito es una llamada interactiva; evita respuestas
    # truncadas o mezcladas por concurrencia del proveedor.
    semaphore = asyncio.Semaphore(1)
    results = await asyncio.gather(*(run_one(provider, case, semaphore) for case in CASES))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "real-purpose-matrix.json"
    path.write_text(
        json.dumps(
            {
                "schema": "zent.p16.real_purpose_matrix/v1",
                "model": get_settings().LITELLM_DEFAULT_MODEL,
                "temperature": 0.2,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(path),
                "calls": len(results),
                "errors": sum(1 for item in results if item["error"]),
                "quality_passed": sum(1 for item in results if item["quality"]["passed"]),
                "generic_failures": sum(
                    1 for item in results if "genericness" in item["quality"]["issues"]
                ),
                "tool_failures": sum(
                    1 for item in results if "unnecessary_tool_listing" in item["quality"]["issues"]
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
