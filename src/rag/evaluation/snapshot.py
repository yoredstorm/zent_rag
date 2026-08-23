# =============================================================================
# Evaluation Snapshot — versión efectiva del sistema bajo evaluación
# =============================================================================
# Captura los componentes versionables (prompt, model, embedding, chunking,
# retriever, reranker) + app info, y deriva un version_id estable (sha256).
# Dos runs con distinto version_id = versiones distintas → comparables.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone

from src.core.config import get_settings
from src.core.domain.entities import Agent, KnowledgeBase, Organization
from src.rag.retrieval.config import resolve_retrieval_config

# Campos que definen la "versión" del sistema (se hashean para version_id).
_VERSION_FIELDS = (
    "prompt",
    "model",
    "embedding",
    "chunking",
    "retriever",
    "reranker",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_commit() -> str | None:
    import shutil

    git_path = shutil.which("git")
    if not git_path:
        return None
    try:
        out = subprocess.run(  # noqa: S603
            [git_path, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _app_info() -> dict:
    settings = get_settings()
    return {
        "git_commit": _git_commit(),
        "environment": settings.ENVIRONMENT,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def compute_version_id(snapshot: dict) -> str:
    """Hash estable de los campos versionables del snapshot."""
    canonical = {
        k: snapshot.get(k)
        for k in _VERSION_FIELDS
        if k in snapshot
    }
    return _sha256(json.dumps(canonical, sort_keys=True, default=str))


def build_rag_snapshot(
    organization: Organization,
    knowledge_base: KnowledgeBase | None = None,
) -> dict:
    """Snapshot de versión para el pipeline RAG (organización + KB opcional)."""
    settings = get_settings()
    org_config = organization.config_json or {}

    prompts = {}
    for key in (
        "system_prompt",
        "system_prompt_admin",
        "system_prompt_customer",
        "custom_instructions",
        "custom_instructions_admin",
        "custom_instructions_customer",
    ):
        value = org_config.get(key)
        if isinstance(value, str) and value.strip():
            prompts[key] = {
                "hash": _sha256(value),
                "length": len(value),
            }

    retrieval = resolve_retrieval_config(organization_config=org_config)

    chunking: dict | None = None
    if knowledge_base is not None:
        chunking = {
            "strategy": knowledge_base.chunking_strategy,
            "chunk_size": knowledge_base.chunk_size,
            "chunk_overlap": knowledge_base.chunk_overlap,
            "embedding_model": knowledge_base.embedding_model,
        }

    snapshot = {
        "target_type": "rag",
        "prompt": prompts,
        "model": organization.llm_model_override or settings.LITELLM_DEFAULT_MODEL,
        "embedding": (
            organization.embedding_model_override or settings.EMBEDDING_MODEL
        ),
        "chunking": chunking,
        "retriever": {
            "strategy": retrieval.strategy,
            "top_k": retrieval.top_k,
            "rerank_top_k": retrieval.rerank_top_k,
            "score_threshold": retrieval.score_threshold,
            "fusion": retrieval.fusion,
            "rrf_k": retrieval.rrf_k,
            "lexical_weight": retrieval.lexical_weight,
        },
        "reranker": {
            "enabled": settings.RAG_RERANK_ENABLED,
            "name": retrieval.reranker or settings.RAG_RERANKER or None,
        },
        "app": _app_info(),
    }
    return snapshot


def build_agent_snapshot(
    agent: Agent,
    org_config: dict | None = None,
) -> dict:
    """Snapshot de versión para el Agent Runtime."""
    settings = get_settings()
    config = agent.config_json or {}
    prompt = agent.system_prompt or ""
    snapshot = {
        "target_type": "agent",
        "prompt": {
            "system_prompt": {
                "hash": _sha256(prompt),
                "length": len(prompt),
            }
        },
        "model": agent.model or settings.RAG_AGENT_MODEL or settings.LITELLM_DEFAULT_MODEL,
        "embedding": settings.EMBEDDING_MODEL,
        "chunking": None,
        "retriever": {"tools": sorted(agent.tools or [])},
        "reranker": {
            "temperature": config.get("temperature"),
            "max_steps": config.get("max_steps"),
            "max_tokens": config.get("max_tokens"),
        },
        "app": _app_info(),
    }
    return snapshot
