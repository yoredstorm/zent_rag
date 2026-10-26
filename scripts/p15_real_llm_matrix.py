"""P15 real-LLM matrix: same evidence and question across the eight profiles.

This script calls the configured real provider. It does not run retrieval or
tools; it exercises the RESPONSE prompt/contract end to end with frozen
evidence. Results are stored in artifacts/certification/p15/real-matrix.json.

Mock tests certify wiring. This script is the only source of real semantic
evidence; if the provider is unavailable, the run is reported as NOT_VERIFIED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings  # noqa: E402
from src.infrastructure.llm.provider import LiteLLMProvider
from src.intelligence.response.contract import compose_contract, prompt_block
from src.intelligence.response.identity import (
    identity_from_agent_config,
    resolve_identity_profile,
)
from src.intelligence.response.intent import detect_user_intent
from src.intelligence.response.profile import RESPONSE_PROFILE_PRESETS
from src.intelligence.response.quality import evaluate_response_quality

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "certification" / "p15"
MAX_TOKENS = 520


@dataclass(frozen=True)
class Case:
    domain: str
    identity_purpose: str
    question: str
    evidence: str
    expected_intent: str = "valuation"


CASES: tuple[Case, ...] = (
    Case(
        domain="literature",
        identity_purpose="Responde como un narrador de cuentos infantil",
        question="¿Qué te parece El principito?",
        evidence=(
            "El principito es una novela corta de Antoine de Saint-Exupéry, "
            "publicada en 1943. Un aviador se accidenta en el Sahara y conoce a "
            "un niño que viene del asteroide B-612. La historia trata la amistad, "
            "el amor, la pérdida y la dificultad de los adultos para ver lo "
            "esencial. El zorro enseña que domesticar crea vínculos y "
            "responsabilidad; la frase central es que lo esencial es invisible a "
            "los ojos. La rosa representa un vínculo frágil y valioso. El final es "
            "ambiguo: el principito se marcha y el narrador conserva la esperanza."
        ),
    ),
    Case(
        domain="education",
        identity_purpose="Responde como un profesor que enseña con ejemplos",
        question="¿Qué te parece este plan de clase?",
        evidence=(
            "Plan: objetivo, lectura guiada de un texto breve, discusión en parejas, "
            "ejercicio de aplicación y cierre con preguntas. La evaluación es "
            "formativa y no tiene rúbrica explícita. Dura 45 minutos. No incluye "
            "adaptaciones para estudiantes con ritmos distintos."
        ),
    ),
    Case(
        domain="commercial",
        identity_purpose="Responde como un asesor comercial claro y directo",
        question="¿Qué te parece este diseño de onboarding?",
        evidence=(
            "El onboarding pide correo, empresa y facturación antes de mostrar el "
            "primer valor. El 42% abandona en el paso de facturación. La activación "
            "ocurre en promedio a los 6 días. El soporte recibe consultas sobre el "
            "precio antes de la activación."
        ),
    ),
    Case(
        domain="audit",
        identity_purpose="Responde como un auditor preciso y trazable",
        question="¿Qué te parece este hallazgo de auditoría?",
        evidence=(
            "Hallazgo: 3 de 20 accesos revisados no tienen aprobación registrada. "
            "El control existe pero no se aplica de forma consistente. La evidencia "
            "incluye extractos del sistema y correos. No se identificaron accesos "
            "indebidos confirmados."
        ),
    ),
    Case(
        domain="support",
        identity_purpose="Responde como un agente de soporte paciente y claro",
        question="¿Qué te parece esta respuesta de soporte?",
        evidence=(
            "El cliente reporta un cobro duplicado. La respuesta de soporte indica "
            "que revise su banco y no ofrece plazo ni número de caso. La política "
            "interna exige registrar el caso y confirmar el reembolso en 48 horas."
        ),
    ),
    Case(
        domain="technical",
        identity_purpose="Responde como un analista técnico que explica trade-offs",
        question="¿Qué te parece esta propuesta de arquitectura?",
        evidence=(
            "Propuesta: cola única, reintentos con backoff exponencial y DLQ. No "
            "define idempotencia del consumidor ni límite de reintentos. El "
            "volumen estimado es 2.000 mensajes por minuto. La consistencia "
            "requerida es al menos una vez."
        ),
    ),
)


def build_prompt(case: Case, profile_name: str) -> tuple[str, str, dict[str, Any]]:
    profile = RESPONSE_PROFILE_PRESETS[profile_name]
    identity = identity_from_agent_config({"purpose": case.identity_purpose})
    resolution = resolve_identity_profile(identity, profile)
    intent = detect_user_intent(case.question)
    contract = compose_contract(
        question=case.question,
        profile=resolution.profile,
        identity=identity,
        user_intent=intent,
        evaluative=intent.evaluative,
    )
    system = prompt_block(contract, profile=resolution.profile, identity=identity)
    user = (
        f"PREGUNTA DEL USUARIO:\n{case.question}\n\n"
        f"EVIDENCIA CONGELADA (única fuente permitida):\n{case.evidence}\n\n"
        "Responde en español, entre 90 y 220 palabras. No muestres análisis "
        "interno, porcentajes de cobertura ni identificadores. Si el usuario pide "
        "una valoración, da una tesis razonada y sepárala de los hechos."
    )
    meta = {
        "profile": profile_name,
        "identity": identity.to_public_dict(),
        "intent": intent.to_public_dict(),
        "contract": contract.to_public_dict(),
        "resolution": resolution.to_public_dict(),
    }
    return system, user, meta


async def judge_answer(
    provider: LiteLLMProvider,
    *,
    case: Case,
    result: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Juez LLM real: criterios separados, sin CoT y sin reescribir la respuesta."""
    if not result.get("answer") or result.get("error"):
        return {"semantic_evaluated": False, "reason": "no_answer"}
    system = (
        "Eres un evaluador semántico estricto de respuestas de agentes. "
        "No reescribas la respuesta. Evalúa sólo el bloque entre <ANSWER> y </ANSWER>; "
        "el resto es contexto y NUNCA forma parte de la respuesta. Devuelve SOLO JSON "
        "válido, sin markdown, con este esquema exacto: "
        '{"intent_fulfilled":true,"persona_preserved":true,"style_applied":true,'
        '"evidence_integrity":true,"direct_answer_present":true,'
        '"unnecessary_refusal":false,"irrelevant_internal_metadata":false,'
        '"verbosity_appropriate":true,"scores":{"intent":1,"persona":1,'
        '"style":1,"evidence":1,"directness":1,"verbosity":1},"notes":[""]}\n'
        "Criterios: 1) responde la intención real sin negarse por falta de experiencia "
        "personal; 2) conserva la voz de la identidad dentro de la longitud del perfil; "
        "3) aplica el estilo sin volverse una transcripción; 4) no inventa hechos/citas "
        "y separa lectura de hecho; 5) no muestra métricas internas; 6) la extensión "
        "corresponde al perfil. No marques como metadato algo que sólo aparece en el "
        "contexto o en estas instrucciones."
    )
    user = (
        "PREGUNTA DEL USUARIO:\n"
        f"{case.question}\n\n"
        "IDENTIDAD PERSISTENTE DEL AGENTE:\n"
        f"{case.identity_purpose}\n\n"
        "PERFIL DE RESPUESTA:\n"
        f"{result['profile']} / {result['contract'].get('communication_strategy')} "
        f"/ detalle {result['contract'].get('detail')}\n\n"
        "EVIDENCIA CONGELADA:\n"
        f"{case.evidence}\n\n"
        "<ANSWER>\n"
        f"{result['answer']}\n"
        "</ANSWER>\n"
        "Evalúa sólo el bloque ANSWER según las instrucciones del sistema."
    )
    try:
        async with semaphore:
            response = await provider.generate(
                prompt=user,
                model=get_settings().LITELLM_DEFAULT_MODEL,
                max_tokens=500,
                temperature=0.0,
                system_prompt=system,
            )
        raw = str(getattr(response, "content", "") or "")
        match = __import__("re").search(r"\{.*\}", raw, __import__("re").DOTALL)
        if not match:
            return {"semantic_evaluated": False, "reason": "judge_non_json"}
        payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            return {"semantic_evaluated": False, "reason": "judge_non_object"}
        return {"semantic_evaluated": True, **payload}
    except Exception as exc:  # noqa: BLE001 — el juicio no inventa PASS
        return {
            "semantic_evaluated": False,
            "reason": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


def merge_judge_quality(result: dict[str, Any], judge: dict[str, Any]) -> None:
    quality = dict(result.get("quality") or {})
    if not judge.get("semantic_evaluated"):
        quality["judge_reason"] = judge.get("reason", "")
        result["quality"] = quality
        return
    for key in (
        "intent_fulfilled",
        "persona_preserved",
        "style_applied",
        "evidence_integrity",
        "direct_answer_present",
        "unnecessary_refusal",
        "irrelevant_internal_metadata",
        "verbosity_appropriate",
    ):
        if key in judge:
            quality[key] = bool(judge[key])
    quality["semantic_evaluated"] = True
    quality["status"] = "semantic_evaluated"
    quality["label"] = "Evaluación semántica"
    quality["judge_scores"] = judge.get("scores") or {}
    quality["notes"] = list(quality.get("notes") or []) + [
        str(note) for note in (judge.get("notes") or []) if str(note).strip()
    ]
    result["quality"] = quality


async def run_case(
    provider: LiteLLMProvider,
    case: Case,
    profile_name: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    system, user, meta = build_prompt(case, profile_name)
    started = time.perf_counter()
    error = ""
    answer = ""
    model = ""
    try:
        async with semaphore:
            response = await provider.generate(
                prompt=user,
                model=get_settings().LITELLM_DEFAULT_MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0.0,
                system_prompt=system,
            )
        answer = str(getattr(response, "content", "") or "").strip()
        model = str(getattr(response, "model", "") or "")
    except Exception as exc:  # noqa: BLE001 — el informe debe distinguir fallo real
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
    elapsed = (time.perf_counter() - started) * 1000
    quality = evaluate_response_quality(
        answer=answer,
        contract=meta["contract"],
        intent=meta["intent"],
        identity=meta["identity"],
        semantic_evaluated=False,
    ).to_public_dict()
    return {
        "domain": case.domain,
        "profile": profile_name,
        "identity": meta["identity"],
        "intent": meta["intent"],
        "contract": meta["contract"],
        "answer": answer,
        "error": error,
        "model": model,
        "latency_ms": round(elapsed, 1),
        "quality": quality,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domains", default="", help="csv de dominios; vacío = todos")
    parser.add_argument("--profiles", default="", help="csv de perfiles; vacío = todos")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="evalúa las respuestas con un juez LLM real (criterios P15)",
    )
    args = parser.parse_args()
    domains = [item.strip() for item in args.domains.split(",") if item.strip()]
    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    cases = [case for case in CASES if not domains or case.domain in domains]
    selected_profiles = profiles or list(RESPONSE_PROFILE_PRESETS)
    unknown = [item for item in selected_profiles if item not in RESPONSE_PROFILE_PRESETS]
    if unknown:
        raise SystemExit(f"perfiles desconocidos: {unknown}")

    provider = LiteLLMProvider()
    semaphore = asyncio.Semaphore(3)
    tasks = [
        run_case(provider, case, profile, semaphore)
        for case in cases
        for profile in selected_profiles
    ]
    results = await asyncio.gather(*tasks)
    if args.judge:
        case_by_domain = {case.domain: case for case in cases}
        judge_tasks = [
            judge_answer(
                provider,
                case=case_by_domain[item["domain"]],
                result=item,
                semaphore=semaphore,
            )
            for item in results
        ]
        judges = await asyncio.gather(*judge_tasks)
        for item, judge in zip(results, judges):
            merge_judge_quality(item, judge)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "zent.p15.real_llm_matrix/v1",
        "model": get_settings().LITELLM_DEFAULT_MODEL,
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "profiles": selected_profiles,
        "domains": [case.domain for case in cases],
        "judge": bool(args.judge),
        "results": results,
    }
    path = OUT / "real-matrix.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in results if item["error"]]
    print(
        json.dumps(
            {
                "artifact": str(path),
                "calls": len(results),
                "errors": len(failures),
                "by_profile": {
                    profile: sum(1 for item in results if item["profile"] == profile)
                    for profile in selected_profiles
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
