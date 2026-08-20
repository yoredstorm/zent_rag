# =============================================================================
# Agents Policies — Políticas de seguridad del agente (puras, sin transporte)
# =============================================================================
# Funciones puras para:
# - Detección de patrones de prompt injection (log/auditoría)
# - Autorización de roles (organization admin vs platform admin)
# =============================================================================
from __future__ import annotations

import re

# -----------------------------------------------------------------------------
# Prompt Injection Detection
# -----------------------------------------------------------------------------
PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"disregard\s+(prior|previous|all)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"forget\s+everything", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"<<\s*SYS\s*>>", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|an?\s+unfiltered)", re.IGNORECASE),
    re.compile(r"\[INST\].*\[/INST\]", re.IGNORECASE),  # Llama/Mistral jailbreak
]


def has_injection_indicators(text: str) -> bool:
    """True si el texto contiene patrones conocidos de prompt injection."""
    return any(p.search(text) for p in PROMPT_INJECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Authorization (RBAC puro sobre el contexto autenticado)
# -----------------------------------------------------------------------------
def is_organization_admin(ctx) -> bool:
    """Admin de la organización: sesión portal con rol owner/admin o token admin:*."""
    if hasattr(ctx, "is_organization_admin"):
        return bool(ctx.is_organization_admin())
    return ctx.auth_type == "portal_session" or "admin:*" in (ctx.scopes or [])


def is_platform_admin(ctx) -> bool:
    """Admin de plataforma: solo tokens con scope admin:* (nunca sesión portal)."""
    if hasattr(ctx, "is_platform_admin"):
        return bool(ctx.is_platform_admin())
    return "admin:*" in (ctx.scopes or [])
