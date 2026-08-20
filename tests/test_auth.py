# =============================================================================
# Tests — Portal auth (email/password + AES-256-GCM sessions)
# =============================================================================
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


class TestPortalSessionCrypto:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        from src.platform.auth.session import decrypt_session, encrypt_session

        uid = uuid4()
        tid = uuid4()
        token = encrypt_session(uid, tid, ttl_hours=1)
        assert token.startswith("rag_sess_")
        payload = decrypt_session(token)
        assert payload.user_id == uid
        assert payload.organization_id == tid
        assert payload.typ == "portal"

    def test_tampered_token_rejected(self) -> None:
        from src.platform.auth.session import (
            SessionTokenError,
            decrypt_session,
            encrypt_session,
        )

        token = encrypt_session(uuid4(), uuid4(), ttl_hours=1)
        bad = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        with pytest.raises(SessionTokenError):
            decrypt_session(bad)


class TestAuthSignupLogin:
    @pytest.mark.asyncio
    async def test_signup_login_me(self, async_client: AsyncClient) -> None:
        email = f"user_{uuid4().hex[:10]}@example.com"
        password = "secure-pass-123"

        signup = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "company_name": "Auth Test Co",
                "email": email,
                "password": password,
            },
        )
        assert signup.status_code == 200, signup.text
        data = signup.json()
        assert data["access_token"].startswith("rag_sess_")
        assert data["email"] == email
        assert "organization_id" in data

        me = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["email"] == email
        assert me.json()["auth_type"] == "portal_session"

        login = await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        assert login.json()["access_token"].startswith("rag_sess_")

    @pytest.mark.asyncio
    async def test_bad_password_returns_401(self, async_client: AsyncClient) -> None:
        email = f"bad_{uuid4().hex[:10]}@example.com"
        await async_client.post(
            "/api/v1/auth/signup",
            json={
                "company_name": "Bad Pass Co",
                "email": email,
                "password": "correct-password",
            },
        )
        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_portal_session_works_on_billing(
        self, async_client: AsyncClient
    ) -> None:
        email = f"bill_{uuid4().hex[:10]}@example.com"
        signup = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "company_name": "Billing Sess Co",
                "email": email,
                "password": "secure-pass-123",
            },
        )
        token = signup.json()["access_token"]
        usage = await async_client.get(
            "/api/v1/billing/usage",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert usage.status_code == 200, usage.text

    @pytest.mark.asyncio
    async def test_login_rate_limit(self, async_client: AsyncClient) -> None:
        from src.platform.auth.rate_limit import reset_memory_rate_limits

        reset_memory_rate_limits()
        email = f"rl_{uuid4().hex[:10]}@example.com"
        await async_client.post(
            "/api/v1/auth/signup",
            json={
                "company_name": "Rate Limit Co",
                "email": email,
                "password": "secure-pass-123",
            },
        )

        last = None
        for _ in range(6):
            last = await async_client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
            )
        assert last is not None
        assert last.status_code == 429, last.text
