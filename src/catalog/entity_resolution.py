# =============================================================================
# Entity Resolution Engine — match gobernado (Phase 27C)
# =============================================================================
# Exact ids + nombres normalizados + fuzzy. suggest_match NUNCA auto-aprueba.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from src.core.domain.entity_resolution import (
    EnterpriseEntity,
    EntityAlias,
    EntityMatch,
    EntityMatchStatus,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = _NON_ALNUM.sub("", text)
    # common legal suffixes noise
    for suffix in ("sac", "sa", "srl", "inc", "llc", "ltd"):
        if text.endswith(suffix) and len(text) > len(suffix) + 2:
            text = text[: -len(suffix)]
    return text


class EntityResolutionEngine:
    """Motor de resolución de entidades empresariales."""

    def __init__(self, *, fuzzy_threshold: float = 0.82) -> None:
        self.fuzzy_threshold = fuzzy_threshold

    def score_match(
        self,
        left: dict[str, Any] | EnterpriseEntity | EntityAlias,
        right: dict[str, Any] | EnterpriseEntity | EntityAlias,
    ) -> dict[str, Any]:
        """Score determinista: exact ids, normalized names, fuzzy."""
        l = self._as_record(left)
        r = self._as_record(right)
        signals: dict[str, float] = {
            "exact_id": 0.0,
            "normalized_name": 0.0,
            "fuzzy": 0.0,
        }

        lid = (l.get("identifier_value") or "").strip().lower()
        rid = (r.get("identifier_value") or "").strip().lower()
        if lid and rid and lid == rid:
            signals["exact_id"] = 1.0

        ln = normalize_name(l.get("display_name") or l.get("canonical_name") or "")
        rn = normalize_name(r.get("display_name") or r.get("canonical_name") or "")
        if ln and rn and ln == rn:
            signals["normalized_name"] = 1.0
            signals["fuzzy"] = 1.0
        elif ln and rn:
            fuzzy = SequenceMatcher(None, ln, rn).ratio()
            signals["fuzzy"] = round(fuzzy, 4)
            if fuzzy >= self.fuzzy_threshold:
                signals["normalized_name"] = max(signals["normalized_name"], 0.85)

        score = (
            0.55 * signals["exact_id"]
            + 0.30 * signals["normalized_name"]
            + 0.15 * signals["fuzzy"]
        )
        # Name-only strong matches should still clear suggestion floor
        if signals["exact_id"] == 0.0 and signals["normalized_name"] >= 0.85:
            score = max(score, 0.55)
        return {
            "score": round(min(score, 1.0), 4),
            "signals": signals,
            "left": l,
            "right": r,
        }

    def suggest_match(
        self,
        left: dict[str, Any] | EnterpriseEntity | EntityAlias,
        right: dict[str, Any] | EnterpriseEntity | EntityAlias,
        *,
        min_score: float = 0.5,
    ) -> EntityMatch | None:
        """Sugiere match; status siempre SUGGESTED_MATCH (nunca auto-approve)."""
        result = self.score_match(left, right)
        if result["score"] < min_score:
            return None
        l = result["left"]
        r = result["right"]
        return EntityMatch(
            left_entity_id=str(l.get("entity_id") or l.get("identifier_value") or ""),
            right_entity_id=str(r.get("entity_id") or r.get("identifier_value") or ""),
            status=EntityMatchStatus.SUGGESTED_MATCH,
            score=result["score"],
            signals=result["signals"],
            reason="suggested by EntityResolutionEngine",
            auto_approved=False,
        )

    @staticmethod
    def _as_record(
        obj: dict[str, Any] | EnterpriseEntity | EntityAlias,
    ) -> dict[str, Any]:
        if isinstance(obj, EntityAlias):
            return {
                "entity_id": obj.identifier_value,
                "identifier_value": obj.identifier_value,
                "display_name": obj.display_name or "",
                "canonical_name": obj.display_name or "",
                "source_system": obj.source_system,
            }
        if isinstance(obj, EnterpriseEntity):
            primary = obj.aliases[0] if obj.aliases else None
            return {
                "entity_id": str(obj.id),
                "identifier_value": primary.identifier_value if primary else "",
                "display_name": obj.canonical_name,
                "canonical_name": obj.canonical_name,
                "source_system": primary.source_system if primary else "",
            }
        return {
            "entity_id": str(obj.get("entity_id") or obj.get("id") or ""),
            "identifier_value": str(obj.get("identifier_value") or obj.get("id") or ""),
            "display_name": str(
                obj.get("display_name") or obj.get("name") or obj.get("canonical_name") or ""
            ),
            "canonical_name": str(obj.get("canonical_name") or obj.get("name") or ""),
            "source_system": str(obj.get("source_system") or ""),
        }
