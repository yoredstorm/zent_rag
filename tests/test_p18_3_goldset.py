# =============================================================================
# P18.3-01 - Validación del gold set (no certificación humana)
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path

from src.rag.evaluation.goldset_v1 import GOLDSET, validate_goldset


def test_goldset_has_40_grounded_cases_but_stays_draft() -> None:
    result = validate_goldset()
    assert result["status"] == "DRAFT_NOT_APPROVED"
    assert result["errors"] == []
    assert result["cases"] == 40
    assert result["by_family"] == {
        "narrative": 10,
        "technical": 10,
        "policy_contract": 10,
        "tabular": 10,
    }
    assert result["metamorphic_checks"] == 12
    assert result["by_annotation_status"]["draft_not_approved"] == 40


def test_strict_human_mode_blocks_until_two_reviewers_approve() -> None:
    result = validate_goldset(strict_human=True)
    assert result["status"] == "BLOCKED_HUMAN_REVIEW"
    assert any("strict-human" in error for error in result["errors"])


def test_invented_excerpt_is_rejected(tmp_path: Path) -> None:
    cases = [
        json.loads(line)
        for line in GOLDSET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cases[0]["supporting_evidence"][0]["verbatim_excerpt"] = "cita inventada que no existe"
    tampered = tmp_path / "goldset_v1.jsonl"
    tampered.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    result = validate_goldset(tampered)
    assert result["status"] == "FAIL"
    assert any("no aparece literalmente" in error for error in result["errors"])
