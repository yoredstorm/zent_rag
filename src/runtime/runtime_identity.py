# =============================================================================
# Runtime Identity — SHA/build/host/proceso por API y worker
# =============================================================================
# Sin esto no se puede distinguir "el dato no está" de "el runtime que corre no
# es el esperado". El SHA se toma de env (imagen Docker), luego de git local
# (dev), luego "unknown". Nunca incluye secretos.
# =============================================================================
from __future__ import annotations

import hashlib
import os
import socket
from datetime import datetime, timezone

_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _env(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _in_image() -> bool:
    """Imagen o cluster: sin SHA de build no se lee un git montado o viejo."""
    return bool(_env("RAG_IMAGE_ID", "IMAGE_ID")) or bool(
        os.environ.get("KUBERNETES_SERVICE_HOST")
    )


def _git_sha() -> str:
    """Una sola fuente con build_info: env de imagen → git local → unknown.

    En imagen/cluster sin env de build NO se lee un git montado: un SHA viejo
    es peor que `unknown`.
    """
    try:
        from src.runtime.build_info import git_sha_from_env, git_sha_from_repo

        from_env = git_sha_from_env()
    except Exception:  # noqa: BLE001 — la identidad nunca rompe el proceso
        from_env = ""
    if from_env:
        return from_env[:40]
    if _in_image():
        return "unknown"
    try:
        return (git_sha_from_repo() or "unknown")[:40]
    except Exception:  # noqa: BLE001
        return "unknown"


def _build_timestamp() -> str:
    return _env("RAG_BUILD_TIMESTAMP", "BUILD_TIMESTAMP") or "unknown"


def runtime_identity() -> dict[str, str]:
    """Identidad del proceso actual (API o worker). Sin secretos."""
    return {
        "git_sha": _git_sha(),
        "build_timestamp": _build_timestamp(),
        "image_id": _env("RAG_IMAGE_ID", "IMAGE_ID") or "unknown",
        "service_name": _env("RAG_SERVICE_NAME") or "api",
        "hostname": socket.gethostname(),
        "process_started_at": _PROCESS_STARTED_AT,
        "pid": str(os.getpid()),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
    }


def _same_sha(left: str, right: str) -> bool:
    if not left or not right or left == "unknown" or right == "unknown":
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def build_parity(
    api: dict[str, str],
    worker: dict[str, str] | None,
    *,
    portal: dict[str, str] | None = None,
    expected_sha: str = "",
) -> dict[str, object]:
    """Paridad de builds. Sin metadata no se reutiliza un SHA anterior."""
    api_sha = str((api or {}).get("git_sha") or "unknown")
    worker_sha = str((worker or {}).get("git_sha") or "unknown")
    portal_sha = str((portal or {}).get("git_sha") or "")
    expected = str(expected_sha or _env("RAG_EXPECTED_GIT_SHA") or "")
    if worker is None or worker_sha == "unknown" or api_sha == "unknown":
        status = "UNKNOWN"
    elif _same_sha(api_sha, worker_sha):
        status = "MATCH"
    else:
        status = "MISMATCH"
    if expected and api_sha != "unknown" and not _same_sha(api_sha, expected):
        status = "METADATA_INCONSISTENT"
    elif expected and api_sha == "unknown":
        status = "UNKNOWN"
    return {
        "status": status,
        "api_sha": api_sha,
        "worker_sha": worker_sha,
        "portal_sha": portal_sha or None,
        "expected_sha": expected or None,
        "api_git_sha": api_sha,
        "worker_git_sha": worker_sha,
        "api_build_timestamp": str((api or {}).get("build_timestamp") or "unknown"),
        "worker_build_timestamp": str((worker or {}).get("build_timestamp") or "unknown"),
    }


def query_fingerprint(query: str) -> str:
    """Fingerprint estable de una query para observabilidad (sin exponerla)."""
    return hashlib.sha256(str(query or "")[:200].encode("utf-8")).hexdigest()[:16]


__all__ = [
    "build_parity",
    "query_fingerprint",
    "runtime_identity",
]
