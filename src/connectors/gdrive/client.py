# =============================================================================
# Google Drive HTTP client — list / download / token (hooks inyectables)
# =============================================================================
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — OAuth endpoint, not a secret
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

HttpGet = Callable[..., Awaitable[tuple[int, Any]]]
HttpPost = Callable[..., Awaitable[dict[str, Any]]]

_http_get: HttpGet | None = None
_http_post: HttpPost | None = None

_GOOGLE_DOC = "application/vnd.google-apps.document"
_MIME_TO_EXT = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
}


def set_gdrive_http(
    *,
    http_get: HttpGet | None = None,
    http_post: HttpPost | None = None,
) -> None:
    """Inyecta HTTP para tests (None = httpx real)."""
    global _http_get, _http_post
    _http_get = http_get
    _http_post = http_post


def _client_credentials() -> tuple[str, str]:
    settings = get_settings()
    client_id = (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
    secret = settings.GOOGLE_OAUTH_CLIENT_SECRET
    client_secret = secret.get_secret_value() if secret is not None else ""
    return client_id, client_secret


async def gdrive_get(
    url: str, *, headers: dict | None = None, params: dict | None = None
) -> tuple[int, Any]:
    if _http_get is not None:
        return await _http_get(url, headers=headers, params=params)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params=params)
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.status_code, response.json()
        return response.status_code, response.content


async def gdrive_post(
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    json: dict | None = None,
) -> dict[str, Any]:
    if _http_post is not None:
        return await _http_post(url, data=data, headers=headers, json=json)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.post(url, data=data, headers=headers, json=json)
        response.raise_for_status()
        return response.json()


async def exchange_authorization_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    client_id, client_secret = _client_credentials()
    return await gdrive_post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def refresh_access_token(refresh_token: str) -> str:
    client_id, client_secret = _client_credentials()
    payload = await gdrive_post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = payload.get("access_token")
    if not token:
        raise ValueError("Google token refresh did not return access_token")
    return str(token)


def extension_for_file(name: str, mime_type: str) -> str | None:
    if mime_type == _GOOGLE_DOC:
        return "txt"
    mapped = _MIME_TO_EXT.get(mime_type)
    if mapped:
        return mapped
    if "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
        if ext in {"pdf", "txt", "md", "markdown", "docx", "html", "htm"}:
            return "md" if ext == "markdown" else ext
    return None


async def list_folder_files(access_token: str, folder_id: str) -> list[dict]:
    query = f"'{folder_id}' in parents and trashed = false"
    status, body = await gdrive_get(
        DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": query,
            "fields": "files(id,name,mimeType,modifiedTime)",
            "pageSize": "100",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    if status >= 400:
        raise ValueError(f"Drive list failed ({status})")
    if not isinstance(body, dict):
        raise ValueError("Drive list returned a non-JSON body")
    return list(body.get("files") or [])


async def download_file(
    access_token: str, file_id: str, mime_type: str
) -> bytes:
    headers = {"Authorization": f"Bearer {access_token}"}
    if mime_type == _GOOGLE_DOC:
        url = f"{DRIVE_FILES_URL}/{quote(file_id, safe='')}/export"
        status, body = await gdrive_get(
            url,
            headers=headers,
            params={"mimeType": "text/plain"},
        )
    else:
        url = f"{DRIVE_FILES_URL}/{quote(file_id, safe='')}"
        status, body = await gdrive_get(
            url,
            headers=headers,
            params={"alt": "media"},
        )
    if status >= 400:
        raise ValueError(f"Drive download failed ({status})")
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    raise ValueError("Drive download returned unexpected body")
