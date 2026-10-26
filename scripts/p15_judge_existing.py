"""Evalúa con LLM real las respuestas ya generadas de un dominio P15.

No vuelve a generar respuestas. Lee real-matrix.json, juzga las variantes del
dominio pedido y escribe real-matrix-judged.json. Si el proveedor falla, el
resultado queda semantic_evaluated=false y NO se convierte en PASS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core.config import get_settings  # noqa: E402
from src.infrastructure.llm.provider import LiteLLMProvider  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts" / "certification" / "p15"
MATRIX = ART / "real-matrix.json"
OUT = ART / "real-matrix-judged.json"

JUDGE_SYSTEM = (
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


def judge_prompt(question: str, identity: str, profile: str, contract: dict, evidence: str, answer: str) -> str:
    return (
        "PREGUNTA DEL USUARIO:\n"
        f"{question}\n\n"
        "IDENTIDAD PERSISTENTE DEL AGENTE:\n"
        f"{identity}\n\n"
        "PERFIL DE RESPUESTA:\n"
        f"{profile} / {contract.get('communication_strategy')} / detalle {contract.get('detail')}\n\n"
        "EVIDENCIA CONGELADA:\n"
        f"{evidence}\n\n"
        "<ANSWER>\n"
        f"{answer}\n"
        "</ANSWER>\n"
        "Evalúa sólo el bloque ANSWER según las instrucciones del sistema."
    )


async def judge_one(
    provider: LiteLLMProvider,
    item: dict[str, Any],
    case: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    if item.get("error") or not item.get("answer"):
        return {"semantic_evaluated": False, "reason": "no_answer"}
    prompt = judge_prompt(
        case["question"],
        case["identity_purpose"],
        item["profile"],
        item.get("contract") or {},
        case["evidence"],
        item["answer"],
    )
    try:
        async with semaphore:
            response = await provider.generate(
                prompt=prompt,
                model=get_settings().LITELLM_DEFAULT_MODEL,
                max_tokens=500,
                temperature=0.0,
                system_prompt=JUDGE_SYSTEM,
            )
        raw = str(getattr(response, "content", "") or "")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"semantic_evaluated": False, "reason": "judge_non_json"}
        payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            return {"semantic_evaluated": False, "reason": "judge_non_object"}
        return {"semantic_evaluated": True, **payload}
    except Exception as exc:  # noqa: BLE001
        return {"semantic_evaluated": False, "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}


def merge_quality(item: dict[str, Any], judge: dict[str, Any]) -> None:
    quality = dict(item.get("quality") or {})
    if not judge.get("semantic_evaluated"):
        quality["judge_reason"] = judge.get("reason", "")
        item["quality"] = quality
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
    item["quality"] = quality


def load_cases() -> dict[str, dict[str, Any]]:
    from p15_real_llm_matrix import CASES

    return {
        case.domain: {
            "question": case.question,
            "identity_purpose": case.identity_purpose,
            "evidence": case.evidence,
        }
        for case in CASES
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="literature")
    args = parser.parse_args()
    if not MATRIX.exists():
        raise SystemExit(f"falta {MATRIX}; ejecutá primero la matriz")
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    case = load_cases().get(args.domain)
    if case is None:
        raise SystemExit(f"dominio desconocido: {args.domain}")
    provider = LiteLLMProvider()
    semaphore = asyncio.Semaphore(2)
    items = [item for item in data["results"] if item["domain"] == args.domain]
    judges = await asyncio.gather(
        *(judge_one(provider, item, case, semaphore) for item in items)
    )
    for item, judge in zip(items, judges):
        merge_quality(item, judge)
        item["judge"] = judge
    data["judged_domain"] = args.domain
    data["judge_model"] = get_settings().LITELLM_DEFAULT_MODEL
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(OUT),
                "domain": args.domain,
                "judged": sum(1 for judge in judges if judge.get("semantic_evaluated")),
                "failed": sum(1 for judge in judges if not judge.get("semantic_evaluated")),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
