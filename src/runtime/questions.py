# =============================================================================
# Runtime JEV questions — workflow decisions, tool routing, termination.
# Business UI never shows Choice/Noul/Score labels.
# =============================================================================
from __future__ import annotations


def workflow_route_questions(options: dict[str, str]) -> dict[str, dict]:
    criteria = options or {"continue": "Continue the flow."}
    return {
        "route": {
            "type": "choice",
            "instructions": "Which option should handle `user_request` given `evidence_preview`?",
            "criteria": criteria,
        },
        "confidence_ok": {
            "type": "noul",
            "instructions": "Is the selected route clearly warranted by the state?",
        },
    }


def workflow_yes_no_questions(prompt: str) -> dict[str, dict]:
    statement = (prompt or "The request should continue.").strip()[:500]
    return {
        "yes": {
            "type": "noul",
            "instructions": f"Is the following statement true? {statement}",
        }
    }


def workflow_score_questions(prompt: str, levels: list[str]) -> dict[str, dict]:
    rubric = levels or [
        "Does not apply",
        "Weak / uncertain",
        "Adequate",
        "Strong / clear",
    ]
    return {
        "score": {
            "type": "score",
            "instructions": (prompt or "Rate the state for this decision.").strip()[:500],
            "criteria": rubric[:8],
        }
    }


def tool_routing_questions(tool_criteria: dict[str, str]) -> dict[str, dict]:
    return {
        "needs_tool": {
            "type": "noul",
            "instructions": (
                "Does `user_request` require a tool given `tool_results` "
                "and `available_tools`?"
            ),
        },
        "tool": {
            "type": "choice",
            "instructions": "Which tool, if any, should run next?",
            "criteria": tool_criteria
            or {"none": "No tool. Answer or finish."},
        },
        "needs_more_evidence": {
            "type": "noul",
            "instructions": (
                "Does the current state still lack evidence required to answer "
                "`user_request`?"
            ),
        },
    }


def answer_gate_questions(*, include_presentation: bool = True) -> dict[str, dict]:
    """JEV verifica el borrador del agente contra la evidencia recolectada.

    Con `include_presentation` suma las preguntas de PRESENTACIÓN (§24) en la
    MISMA llamada: claridad, estructura, utilidad y motivo de revisión. No es un
    segundo veredicto: el veredicto (approve/revise/abstain) lo compone el código.
    """
    questions: dict[str, dict] = {
        "answer_grounded": {
            "type": "noul",
            "instructions": (
                "Are the factual claims in `draft_answer` supported by "
                "`evidence`? If the draft says evidence is missing, the answer is yes."
            ),
        },
        "answer_complete": {
            "type": "noul",
            "instructions": (
                "Does `draft_answer` fully address `user_request` without "
                "missing parts?"
            ),
        },
        "answer_quality": {
            "type": "score",
            "instructions": (
                "Quality of `draft_answer` for `user_request` given `evidence`."
            ),
            "criteria": [
                "unsupported or wrong",
                "weak or incomplete",
                "adequate",
                "strong, grounded and complete",
            ],
        },
    }
    if include_presentation:
        questions.update(
            {
                "answer_explains_key_reason": {
                    "type": "noul",
                    "instructions": (
                        "Does `draft_answer` explain the key reason behind the "
                        "conclusion, not only the conclusion itself?"
                    ),
                },
                "answer_is_needlessly_verbose": {
                    "type": "noul",
                    "instructions": (
                        "Is `draft_answer` needlessly verbose: padding, repetition "
                        "or generic filler?"
                    ),
                },
                "important_context_missing": {
                    "type": "noul",
                    "instructions": (
                        "Is an important piece of context missing, without which the "
                        "reader cannot understand or act on `draft_answer`?"
                    ),
                },
                "structure": {
                    "type": "score",
                    "instructions": "How well structured is `draft_answer`?",
                    "criteria": [
                        "hard to follow",
                        "acceptable",
                        "clear",
                        "very clear and scannable",
                    ],
                },
                "usefulness": {
                    "type": "score",
                    "instructions": (
                        "How useful is `draft_answer` for the user's actual case, "
                        "given `evidence`?"
                    ),
                    "criteria": [
                        "does not help",
                        "partially useful",
                        "useful",
                        "directly actionable",
                    ],
                },
                "revision_reason": {
                    "type": "choice",
                    "instructions": (
                        "If `draft_answer` must be revised, the single most important "
                        "reason to do so."
                    ),
                    "criteria": {
                        "unclear": "The answer is hard to understand.",
                        "too_verbose": "It says more than needed.",
                        "too_short": "It omits necessary explanation.",
                        "missing_explanation": "It states the conclusion without the reason.",
                        "missing_example": "An example would make it clear and is absent.",
                        "missing_evidence": "A claim lacks support in the evidence.",
                        "unsupported_claim": "It states something the evidence does not support.",
                        "poor_structure": "The order or sections make it hard to follow.",
                        "does_not_answer_question": "It answers a different question.",
                    },
                },
            }
        )
    return questions


def termination_questions() -> dict[str, dict]:
    return {
        "satisfied": {
            "type": "noul",
            "instructions": (
                "Has `user_request` already been satisfied by `tool_results` "
                "and the last assistant action? If no tools ran, the answer is no."
            ),
        }
    }
