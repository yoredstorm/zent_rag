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
import subprocess
from datetime import datetime, timezone

_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _env(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _git_sha() -> str:
    from_env = _env("RAG_GIT_SHA", "GIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT")
    if from_env:
        return from_env[:40]
    try:
        result = subprocess.run(  # noqa: S603 — comando fijo, sin shell
            ["git", "rev-parse", "HEAD"],  # noqa: S607 — git del PATH en dev
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:40]
    except Exception:  # noqa: BLE001 — sin git no hay SHA local
        pass
    return "unknown"


def _build_timestamp() -> str:
    return _env("RAG_BUILD_TIMESTAMP", "BUILD_TIMESTAMP") or "unknown"


def runtime_identity() -> dict[str, str]:
    """Identidad del proceso actual (API o worker). Sin secretos."""
    return {
        "git_sha": _git_sha(),
        "build_timestamp": _build_timestamp(),
        "image_id": _env("RAG_IMAGE_ID", "IMAGE_ID", "HOSTNAME") or "unknown",
        "hostname": socket.gethostname(),
        "process_started_at": _PROCESS_STARTED_AT,
        "pid": str(os.getpid()),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
    }


def build_parity(api: dict[str, str], worker: dict[str, str] | None) -> dict[str, object]:
    """Paridad API/worker. SHA distinto conocido => BUILD_MISMATCH."""
    api_sha = str((api or {}).get("git_sha") or "unknown")
    worker_sha = str((worker or {}).get("git_sha") or "unknown")
    if worker is None or worker_sha == "unknown":
        status = "UNKNOWN"
    elif api_sha == "unknown":
        status = "UNKNOWN"
    elif api_sha == worker_sha:
        status = "ok"
    else:
        status = "BUILD_MISMATCH"
    return {
        "status": status,
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
