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
    }


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
