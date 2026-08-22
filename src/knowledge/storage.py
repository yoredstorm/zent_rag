# =============================================================================
# Upload storage — resolución segura de rutas bajo UPLOAD_DIR
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from src.core.config import get_settings


def upload_root() -> Path:
    root = Path(get_settings().UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_path(organization_id: UUID, object_key: str) -> Path:
    """Resuelve una ruta segura dentro de UPLOAD_DIR/{org}.

    Rechaza path traversal (.., rutas absolutas, caracteres raros).
    """
    key = object_key.replace("\\", "/").strip().lstrip("/")
    if not key or ".." in key.split("/"):
        raise ValueError("Invalid object_key (path traversal)")
    root = upload_root()
    target = (root / str(organization_id) / key).resolve()
    org_root = (root / str(organization_id)).resolve()
    if not str(target).startswith(str(org_root)):
        raise ValueError("Invalid object_key (outside organization directory)")
    return target


def store_upload(organization_id: UUID, filename: str, data: bytes) -> str:
    """Guarda bytes bajo UPLOAD_DIR/{org}/{uuid}_{filename} y retorna object_key."""
    import re
    import uuid

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120] or "upload.bin"
    key = f"{uuid.uuid4().hex}_{safe_name}"
    target = resolve_path(organization_id, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key
