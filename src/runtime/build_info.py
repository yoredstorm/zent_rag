# =============================================================================
# Build info — qué versión de código y de motores ejecutó el run
# =============================================================================
# Producción corre en contenedores: sin esto no hay forma de comprobar si el
# proceso realmente está en el commit esperado. El SHA se toma de variables de
# build/deploy (RUNTIME_BUILD_GIT_SHA y familia) y, como último recurso, del
# repositorio local. Si no está disponible queda "" (no se inventa).
# =============================================================================
from __future__ import annotations

import subprocess
from functools import lru_cache
from os import environ
from pathlib import Path
from typing import Any

BUILD_INFO_VERSION = "build-info-1"

_SHA_ENV_KEYS = (
    "RUNTIME_BUILD_GIT_SHA",
    "RAG_RUNTIME_BUILD_GIT_SHA",
    "BUILD_GIT_SHA",
    "GIT_SHA",
    "GITHUB_SHA",
    "RENDER_GIT_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
)
_TIMESTAMP_ENV_KEYS = (
    "RUNTIME_BUILD_TIMESTAMP",
    "RAG_RUNTIME_BUILD_TIMESTAMP",
    "BUILD_TIMESTAMP",
)


@lru_cache(maxsize=1)
def _env_first(keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(environ.get(key) or "").strip()
        if value:
            return value[:64]
    return ""


@lru_cache(maxsize=1)
def _git_sha_from_repo() -> str:
    try:
        repo = Path(__file__).resolve().parents[2]
        completed = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()[:64]
    except Exception:  # noqa: BLE001 — sin git no hay SHA, nunca rompe el run
        return ""
    return ""


def git_sha() -> str:
    return _env_first(_SHA_ENV_KEYS) or _git_sha_from_repo()


def build_timestamp() -> str:
    return _env_first(_TIMESTAMP_ENV_KEYS)


@lru_cache(maxsize=1)
def build_info() -> dict[str, Any]:
    """Versiones del código y de la cadena determinista del proceso actual.

    Imports lazy: `src.runtime` no puede acoplarse a la cadena al importar.
    """
    from src.knowledge.rule_compiler import RULE_COMPILER_VERSION
    from src.runtime.decision_envelope import DECISION_ENVELOPE_VERSION
    from src.runtime.derived_guard import DERIVED_GUARD_VERSION
    from src.runtime.deterministic_authority import (
        DETERMINISTIC_AUTHORITY_VERSION,
    )
    from src.runtime.rule_retrieval import RULE_RETRIEVAL_VERSION

    try:
        from src.intelligence.query_semantics import QUERY_SEMANTICS_VERSION
    except Exception:  # noqa: BLE001
        QUERY_SEMANTICS_VERSION = ""
    try:
        from src.intelligence.reasoning.grounded_engine import (
            GROUNDED_ENGINE_VERSION,
        )
    except Exception:  # noqa: BLE001
        GROUNDED_ENGINE_VERSION = ""
    try:
        from src.knowledge.rule_compiler.evaluate import EVALUATION_VERSION

        rule_evaluation_version = EVALUATION_VERSION
    except Exception:  # noqa: BLE001
        rule_evaluation_version = ""
    try:
        from src.runtime.premise_closure import PREMISE_CLOSURE_VERSION

        premise_closure_version = PREMISE_CLOSURE_VERSION
    except Exception:  # noqa: BLE001
        premise_closure_version = ""
    try:
        from src.runtime.query_local_rules import QUERY_LOCAL_RULES_VERSION

        query_local_rules_version = QUERY_LOCAL_RULES_VERSION
    except Exception:  # noqa: BLE001
        query_local_rules_version = ""

    sha = git_sha()
    return {
        "version": BUILD_INFO_VERSION,
        "git_sha": sha,
        # La UI no puede ocultar la ausencia de SHA: string explícito.
        "git_sha_display": sha or "BUILD_SHA_UNAVAILABLE",
        "build_timestamp": build_timestamp(),
        "rule_retrieval_version": RULE_RETRIEVAL_VERSION,
        "rule_compiler_version": RULE_COMPILER_VERSION,
        "grounding_version": GROUNDED_ENGINE_VERSION,
        "decision_envelope_version": DECISION_ENVELOPE_VERSION,
        "derived_guard_version": DERIVED_GUARD_VERSION,
        "deterministic_authority_version": DETERMINISTIC_AUTHORITY_VERSION,
        "query_semantics_version": QUERY_SEMANTICS_VERSION,
        "rule_evaluation_version": rule_evaluation_version,
        "premise_closure_version": premise_closure_version,
        "query_local_rules_version": query_local_rules_version,
    }


__all__ = [
    "BUILD_INFO_VERSION",
    "build_info",
    "build_timestamp",
    "git_sha",
]
