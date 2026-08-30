# =============================================================================
# Password reset — no email enumeration, one-time token, expiry
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _signup(client: AsyncClient) -> dict:
    email = f"reset-{uuid4().hex[:8]}@example.com"
    password = "CorrectHorse1"
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": f"Reset Co {uuid4().hex[:6]}",
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    body["email"] = email
    body["password"] = password
    return body


@pytest.mark.asyncio
async def test_forgot_password_same_200_known_and_unknown(
    async_client: AsyncClient,
) -> None:
    user = await _signup(async_client)
    known = await async_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": user["email"]},
    )
    unknown = await async_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"missing-{uuid4().hex[:8]}@example.com"},
    )
    assert known.status_code == 200, known.text
    assert unknown.status_code == 200, unknown.text
    assert known.json()["status"] == unknown.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_reset_password_token_is_single_use(async_client: AsyncClient) -> None:
    user = await _signup(async_client)
    forgot = await async_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": user["email"]},
    )
    assert forgot.status_code == 200, forgot.text
    token = forgot.json().get("dev_reset_token")
    assert token

    first = await async_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "NewPassword9"},
    )
    assert first.status_code == 200, first.text

    second = await async_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "AnotherPass9"},
    )
    assert second.status_code == 400, second.text

    login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "NewPassword9"},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_expired_reset_token_rejected(async_client: AsyncClient) -> None:
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.password_reset import ensure_reset_schema, hash_reset_token

    user = await _signup(async_client)
    await ensure_reset_schema()
    raw = f"expired-{uuid4().hex}"
    session = await get_async_session()
    try:
        owner = (
            await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": user["email"]},
            )
        ).fetchone()
        assert owner is not None
        await session.execute(
            text(
                "INSERT INTO password_reset_tokens "
                "(user_id, token_hash, expires_at) "
                "VALUES (:uid, :thash, :exp)"
            ),
            {
                "uid": owner.id,
                "thash": hash_reset_token(raw),
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
        )
        await session.commit()
    finally:
        await session.close()

    resp = await async_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "password": "TooLatePass1"},
    )
    assert resp.status_code == 400, resp.text
