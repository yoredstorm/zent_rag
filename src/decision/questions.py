# =============================================================================
# Atomic System One questions — same state, mixed Choice / Score / Noul.
# =============================================================================
# Official TypeSafe guidance: one snap judgment per question; compose in code.
# Noul has no separate confidence; certainty is distance from 0.5.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import SCORE_COMPLEXITY_LEVELS

CAPABILITY_CRITERIA: dict[str, str] = {
    "knowledge.search": "Search private documents or knowledge bases.",
    "knowledge.retrieve": "Retrieve specific passages already known to exist.",
    "knowledge.answer": "Answer using retrieved private knowledge plus a short generation.",
    "database.query": "Query structured business records with SQL or tabular lookup.",
    "database.schema": "Inspect schema or catalog metadata, not row values.",
    "agent.execute": "Run a multi-step agent with tools.",
    "agent.reason": "Agent reasoning without a specific tool action.",
    "agent.delegate": "Hand the request to another specialized agent.",
    "workflow.start": "Start a known workflow from the beginning.",
    "workflow.execute": "Start a known workflow.",
    "workflow.resume": "Resume a paused workflow.",
    "tool.call_api": "Call an external HTTP API tool.",
    "tool.send_email": "Send an email via an authorized tool.",
    "tool.execute": "Execute a named tool that is not API or email.",
    "document.read": "Read a specific already-identified document.",
    "llm.reason": "Open-ended reasoning that needs a generative LLM.",
    "llm.generate": "Draft or rewrite text without retrieval.",
    "respond_directly": "Answer from the request alone; no retrieval, tools, or SQL.",
}

DOMAIN_CRITERIA: dict[str, str] = {
    "operations": "Business operations, inventory, sales, customers, orders.",
    "policy": "Policies, manuals, definitions, how-to documentation.",
    "engineering": "Technical systems, APIs, incidents, integrations.",
    "general": "Small talk, meta questions, or unclear domain.",
    "other": "None of the listed domains.",
}


def build_routing_questions(
    available_capabilities: tuple[str, ...] | list[str],
) -> dict[str, dict]:
    """One request, many independent questions over the same state."""
    options = {
        cap: CAPABILITY_CRITERIA.get(cap, cap)
        for cap in available_capabilities
        if cap in CAPABILITY_CRITERIA
    }
    if not options:
        options = {
            "knowledge.answer": CAPABILITY_CRITERIA["knowledge.answer"],
            "respond_directly": CAPABILITY_CRITERIA["respond_directly"],
        }
    return {
        "capability": {
            "type": "choice",
            "instructions": (
                "Which capability in `available_capabilities` should handle "
                "`user_request` given `tenant_policy` and `budget`?"
            ),
            "criteria": options,
        },
        "domain": {
            "type": "choice",
            "instructions": "Which domain does `user_request` belong to?",
            "criteria": DOMAIN_CRITERIA,
        },
        "complexity": {
            "type": "score",
            "instructions": "How complex is `user_request`?",
            "criteria": list(SCORE_COMPLEXITY_LEVELS),
        },
        "needs_private_knowledge": {
            "type": "noul",
            "instructions": (
                "Does answering `user_request` require private tenant knowledge "
                "that is not in the request itself?"
            ),
        },
        "needs_complex_reasoning": {
            "type": "noul",
            "instructions": (
                "Does `user_request` require multi-step generative reasoning "
                "beyond a lookup or classification?"
            ),
        },
        "needs_action": {
            "type": "noul",
            "instructions": (
                "Does `user_request` require executing an action "
                "(tool, workflow, email, or API call) rather than only answering?"
            ),
        },
        "retrieved_info_sufficient": {
            "type": "noul",
            "instructions": (
                "If `conversation_state.last_assistant` already contains enough "
                "information to answer `user_request`, is that information sufficient? "
                "If there is no prior retrieved information, the answer is no."
            ),
        },
    }


def noul_certainty(value: float) -> float:
    """Noul has no confidence field. Distance from 0.5 is the certainty proxy."""
    return min(1.0, max(0.0, abs(float(value) - 0.5) * 2.0))


def noul_is_yes(value: float, yes_threshold: float) -> bool:
    return float(value) >= yes_threshold


def noul_is_no(value: float, no_threshold: float) -> bool:
    return float(value) <= no_threshold


def noul_is_uncertain(value: float, yes_threshold: float, no_threshold: float) -> bool:
    return no_threshold < float(value) < yes_threshold


def complexity_from_score(score: float) -> str:
    if score < 0.5:
        return "trivial"
    if score < 1.5:
        return "bounded"
    if score < 2.5:
        return "multi_step"
    return "reasoning"
