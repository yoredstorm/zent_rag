# =============================================================================
# P18.3-01 - Validación del gold set humano (schema + fuentes)
# =============================================================================
# Valida estructura y grounding mínimo. NO convierte anotaciones draft en
# "human certified": `--strict-human` falla si falta revisión real.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "p18_3"
GOLDSET = FIXTURE_DIR / "goldset_v1.jsonl"
METAMORPHIC = FIXTURE_DIR / "metamorphic_v1.json"
RUBRIC_VERSION = "p18.3-rubric-v1"
FAMILIES = ("narrative", "technical", "policy_contract", "tabular")
BEHAVIORS = {"answer", "abstain", "contradiction"}
CLAIM_TYPES = {
    "textual_fact",
    "supported_inference",
    "literary_interpretation",
    "normative_rule",
    "tabular_calculation",
    "unsupported",
}
ANNOTATION_STATES = {"draft_not_approved", "in_review", "approved"}
REQUIRED = {
    "case_id",
    "family",
    "source_fixture",
    "document_version",
    "document_hash",
    "workspace_ref",
    "corpus_ref",
    "source_ref",
    "question",
    "intent",
    "expected_behavior",
    "gold_answer",
    "accepted_variants",
    "supporting_evidence",
    "must_not_claim",
    "expected_claim_type",
    "required_permissions",
    "difficulty",
    "annotation_status",
    "reviewer_ids",
    "rubric_version",
    "split",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, Any]:
    path = FIXTURE_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fixture_text(case: dict[str, Any], errors: list[str]) -> str | None:
    value = str(case.get("source_fixture") or "").replace("\\", "/")
    path = Path(value)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    try:
        path.relative_to((ROOT / "tests" / "fixtures" / "p18_3").resolve())
    except ValueError:
        errors.append(f"{case.get('case_id')}: fixture fuera de tests/fixtures/p18_3")
        return None
    if not path.exists():
        errors.append(f"{case.get('case_id')}: fixture inexistente {path}")
        return None
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def validate_goldset(
    goldset: Path = GOLDSET,
    metamorphic: Path = METAMORPHIC,
    *,
    strict_human: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not goldset.exists():
        return {"status": "FAIL", "errors": [f"goldset inexistente: {goldset}"]}
    manifest = _manifest()
    files = manifest.get("files") or {}
    cases = _load_jsonl(goldset)
    if len(cases) != 40:
        errors.append(f"se esperaban 40 casos, hay {len(cases)}")

    by_family = {family: 0 for family in FAMILIES}
    by_split = {"dev": 0, "holdout": 0}
    by_status: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for case in cases:
        cid = str(case.get("case_id") or "")
        missing = REQUIRED - set(case)
        if missing:
            errors.append(f"{cid or '?'}: faltan campos {sorted(missing)}")
        if not cid:
            errors.append("caso sin case_id")
        elif cid in seen_ids:
            errors.append(f"{cid}: case_id duplicado")
        seen_ids.add(cid)
        question = str(case.get("question") or "").strip()
        if question in seen_questions:
            errors.append(f"{cid}: pregunta duplicada")
        seen_questions.add(question)
        family = str(case.get("family") or "")
        if family not in FAMILIES:
            errors.append(f"{cid}: familia inválida {family!r}")
        else:
            by_family[family] += 1
        behavior = str(case.get("expected_behavior") or "")
        if behavior not in BEHAVIORS:
            errors.append(f"{cid}: expected_behavior inválido {behavior!r}")
        claim_type = str(case.get("expected_claim_type") or "")
        if claim_type not in CLAIM_TYPES:
            errors.append(f"{cid}: expected_claim_type inválido {claim_type!r}")
        if claim_type == "unsupported" and behavior != "abstain":
            errors.append(f"{cid}: unsupported exige abstain")
        status = str(case.get("annotation_status") or "")
        by_status[status] = by_status.get(status, 0) + 1
        if status not in ANNOTATION_STATES:
            errors.append(f"{cid}: annotation_status inválido {status!r}")
        reviewers = case.get("reviewer_ids")
        if not isinstance(reviewers, list):
            errors.append(f"{cid}: reviewer_ids debe ser lista")
            reviewers = []
        if status == "approved" and len(set(map(str, reviewers))) < 2:
            errors.append(f"{cid}: approved exige >=2 revisores")
        if status == "draft_not_approved" and reviewers:
            errors.append(f"{cid}: draft no puede declarar revisores")
        if strict_human and status != "approved":
            errors.append(f"{cid}: strict-human exige annotation_status=approved")
        if str(case.get("rubric_version") or "") != RUBRIC_VERSION:
            errors.append(f"{cid}: rubric_version distinta de {RUBRIC_VERSION}")
        split = str(case.get("split") or "")
        if split not in by_split:
            errors.append(f"{cid}: split inválido {split!r}")
        else:
            by_split[split] += 1
        gold = case.get("gold_answer")
        if behavior in {"answer", "contradiction"} and not str(gold or "").strip():
            errors.append(f"{cid}: respuesta esperada sin gold_answer")
        if behavior == "abstain" and str(gold or "").strip():
            errors.append(f"{cid}: abstain no debe declarar gold_answer")
        variants = case.get("accepted_variants")
        if not isinstance(variants, list):
            errors.append(f"{cid}: accepted_variants debe ser lista")
        elif behavior in {"answer", "contradiction"} and not variants:
            errors.append(f"{cid}: respuesta esperada sin variantes aceptadas")
        must_not = case.get("must_not_claim")
        if not isinstance(must_not, list) or not must_not:
            errors.append(f"{cid}: must_not_claim vacío")
        evidence = case.get("supporting_evidence")
        if not isinstance(evidence, list):
            errors.append(f"{cid}: supporting_evidence debe ser lista")
            evidence = []
        if behavior in {"answer", "contradiction"} and not evidence:
            errors.append(f"{cid}: respuesta/contradicción sin evidencia")
        text = _fixture_text(case, errors)
        fixture_name = Path(str(case.get("source_fixture") or "")).name
        expected_hash = (files.get(fixture_name) or {}).get("sha256")
        if expected_hash and case.get("document_hash") != expected_hash:
            errors.append(f"{cid}: document_hash no coincide con el manifiesto")
        if text is not None:
            body = text
            for index, item in enumerate(evidence):
                if not isinstance(item, dict):
                    errors.append(f"{cid}: evidencia {index} no es objeto")
                    continue
                excerpt = str(item.get("verbatim_excerpt") or "")
                if not excerpt.strip():
                    errors.append(f"{cid}: evidencia {index} sin extracto")
                elif excerpt not in body:
                    errors.append(
                        f"{cid}: extracto {index} no aparece literalmente en {fixture_name}"
                    )
                if not item.get("page"):
                    errors.append(f"{cid}: evidencia {index} sin página")
        if int(case.get("difficulty") or 0) not in range(1, 6):
            errors.append(f"{cid}: difficulty debe ser 1..5")

    if any(count != 10 for count in by_family.values()):
        errors.append(f"distribución por familia inválida: {by_family}")
    if by_split["dev"] == 0 or by_split["holdout"] == 0:
        errors.append("se requieren casos dev y holdout")

    meta_count = 0
    if metamorphic.exists():
        payload = json.loads(metamorphic.read_text(encoding="utf-8"))
        checks = payload.get("checks") or []
        per_family = {family: 0 for family in FAMILIES}
        for check in checks:
            family = str(check.get("family") or "")
            if family not in per_family:
                errors.append(f"metamorphic: familia inválida {family!r}")
                continue
            per_family[family] += 1
            if str(check.get("case_id")) not in seen_ids:
                errors.append(f"metamorphic: case_id inexistente {check.get('case_id')}")
        for family, count in per_family.items():
            if count < 3:
                errors.append(f"metamorphic: {family} tiene {count} checks (<3)")
        meta_count = len(checks)
    else:
        warnings.append("metamorphic_v1.json ausente")

    status = "FAIL" if errors else (
        "DRAFT_NOT_APPROVED"
        if any(case.get("annotation_status") != "approved" for case in cases)
        else "PASS_HUMAN_REVIEWED"
    )
    if strict_human and status != "PASS_HUMAN_REVIEWED":
        status = "BLOCKED_HUMAN_REVIEW"
    return {
        "status": status,
        "cases": len(cases),
        "by_family": by_family,
        "by_split": by_split,
        "by_annotation_status": by_status,
        "metamorphic_checks": meta_count,
        "goldset_sha256": _sha256(goldset),
        "fixtures_sha256": _sha256(FIXTURE_DIR / "manifest.json"),
        "errors": errors,
        "warnings": warnings,
    }
