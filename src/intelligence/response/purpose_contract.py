# =============================================================================
# P16 — Agent Purpose v2 contract.
# =============================================================================
# Transport contract only. The user never sees this JSON; the UI renders the
# natural-language purpose and the editable additional instructions.
# =============================================================================
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PurposePersonaV1(BaseModel):
    """Identidad comunicativa propuesta, sin crear una autoridad persistente."""

    model_config = ConfigDict(extra="ignore")

    role: str = Field(default="", max_length=120)
    audience: str = Field(default="", max_length=160)
    voice: str = Field(default="", max_length=240)
    communication_principles: list[str] = Field(default_factory=list, max_length=8)


class PurposeIntentV1(BaseModel):
    """Salida validada del constructor de propósito."""

    model_config = ConfigDict(extra="ignore")

    schema_id: Literal["zent.agent_purpose/v2"] = Field(
        default="zent.agent_purpose/v2", alias="schema"
    )
    intent_summary: str = Field(default="", max_length=600)
    purpose: str = Field(default="", max_length=2000)
    additional_instructions: str = Field(default="", max_length=16000)
    persona: PurposePersonaV1 = Field(default_factory=PurposePersonaV1)
    behavioral_objectives: list[str] = Field(default_factory=list, max_length=10)
    knowledge_boundaries: list[str] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=12)
    generation_source: str = Field(default="model", max_length=40)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_id,
            "intent_summary": self.intent_summary,
            "purpose": self.purpose,
            "additional_instructions": self.additional_instructions,
            "persona": self.persona.model_dump(),
            "behavioral_objectives": list(self.behavioral_objectives),
            "knowledge_boundaries": list(self.knowledge_boundaries),
            "warnings": list(self.warnings),
            "generation_source": self.generation_source,
        }


class PurposeQualityV1(BaseModel):
    """Evaluación independiente del texto propuesto (no del modelo)."""

    model_config = ConfigDict(extra="ignore")

    schema_id: Literal["zent.agent_purpose_quality/v1"] = Field(
        default="zent.agent_purpose_quality/v1", alias="schema"
    )
    passed: bool = False
    score: float = 0.0
    criteria: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list, max_length=20)
    generic_phrases: list[str] = Field(default_factory=list, max_length=10)
    unnecessary_tools: list[str] = Field(default_factory=list, max_length=10)
    repaired: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_id,
            "passed": bool(self.passed),
            "score": round(float(self.score), 4),
            "criteria": dict(self.criteria),
            "issues": list(self.issues),
            "generic_phrases": list(self.generic_phrases),
            "unnecessary_tools": list(self.unnecessary_tools),
            "repaired": bool(self.repaired),
        }


__all__ = ["PurposeIntentV1", "PurposePersonaV1", "PurposeQualityV1"]
