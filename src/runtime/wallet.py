# =============================================================================
# Runtime-owned wallet helpers (credits models cannot mutate).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

_DEFAULT = {
    "trial_credits": 0.0,
    "promo_credits": 0.0,
    "paid_credits": 0.0,
    "used_credits": 0.0,
    "granted": 0.0,
    "remaining": None,
    "remaining_ok": True,
    "prefer_cheap": False,
    "on_limit": "block",
    "currency": "USD",
    "trial_ends_at": None,
    "request_limit": None,
    "token_limit": None,
    "agent_run_limit": None,
    "workflow_run_limit": None,
    "storage_limit_bytes": None,
}


async def snapshot_budget(organization_id: UUID) -> dict:
    """Read-only wallet view for ExecutionState.budget."""
    try:
        session = await get_async_session()
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT)
    try:
        row = (
            await session.execute(
                text(
                    "SELECT trial_credits, promo_credits, paid_credits, used_credits, "
                    "on_limit, trial_ends_at, request_limit, token_limit, "
                    "agent_run_limit, workflow_run_limit, storage_limit_bytes "
                    "FROM tenant_wallets WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT)
    finally:
        await session.close()
    if row is None:
        return dict(_DEFAULT)
    granted = float(row.trial_credits or 0) + float(row.promo_credits or 0) + float(row.paid_credits or 0)
    used = float(row.used_credits or 0)
    remaining = max(0.0, granted - used)
    on_limit = str(row.on_limit or "block")
    depleted = remaining <= 0.0 and granted > 0
    return {
        "trial_credits": float(row.trial_credits or 0),
        "promo_credits": float(row.promo_credits or 0),
        "paid_credits": float(row.paid_credits or 0),
        "used_credits": used,
        "granted": granted,
        "remaining": remaining,
        "remaining_ok": (not depleted) or on_limit in {"overage", "cheap-mode", "read-only"},
        "prefer_cheap": on_limit == "cheap-mode" or (depleted and on_limit != "block"),
        "on_limit": on_limit,
        "currency": "USD",
        "trial_ends_at": row.trial_ends_at.isoformat() if getattr(row, "trial_ends_at", None) else None,
        "request_limit": row.request_limit,
        "token_limit": row.token_limit,
        "agent_run_limit": row.agent_run_limit,
        "workflow_run_limit": row.workflow_run_limit,
        "storage_limit_bytes": row.storage_limit_bytes,
    }


def prefer_cheap_path(budget: dict | None) -> bool:
    if not budget:
        return False
    return bool(budget.get("prefer_cheap"))


def public_wallet(budget: dict) -> dict:
    return {
        "trial_credits": budget.get("trial_credits", 0),
        "promo_credits": budget.get("promo_credits", 0),
        "paid_credits": budget.get("paid_credits", 0),
        "credit_granted": budget.get("granted", 0),
        "used": budget.get("used_credits", 0),
        "remaining": budget.get("remaining"),
        "on_limit": budget.get("on_limit", "block"),
        "trial_ends_at": budget.get("trial_ends_at"),
        "request_limit": budget.get("request_limit"),
        "token_limit": budget.get("token_limit"),
        "agent_run_limit": budget.get("agent_run_limit"),
        "workflow_run_limit": budget.get("workflow_run_limit"),
        "storage_limit_bytes": budget.get("storage_limit_bytes"),
        "currency": budget.get("currency", "USD"),
    }


async def upsert_wallet(organization_id: UUID, payload: dict) -> dict:
    allowed_on_limit = {"block", "cheap-mode", "read-only", "overage"}
    on_limit = str(payload.get("on_limit") or "block")
    if on_limit not in allowed_on_limit:
        on_limit = "block"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO tenant_wallets (
                    organization_id, trial_credits, promo_credits, paid_credits,
                    used_credits, trial_ends_at, request_limit, token_limit,
                    agent_run_limit, workflow_run_limit, storage_limit_bytes,
                    on_limit, updated_at
                ) VALUES (
                    :oid, :trial, :promo, :paid, :used, :ends, :req, :tok,
                    :agent, :wf, :storage, :on_limit, NOW()
                )
                ON CONFLICT (organization_id) DO UPDATE SET
                    trial_credits = EXCLUDED.trial_credits,
                    promo_credits = EXCLUDED.promo_credits,
                    paid_credits = EXCLUDED.paid_credits,
                    used_credits = EXCLUDED.used_credits,
                    trial_ends_at = EXCLUDED.trial_ends_at,
                    request_limit = EXCLUDED.request_limit,
                    token_limit = EXCLUDED.token_limit,
                    agent_run_limit = EXCLUDED.agent_run_limit,
                    workflow_run_limit = EXCLUDED.workflow_run_limit,
                    storage_limit_bytes = EXCLUDED.storage_limit_bytes,
                    on_limit = EXCLUDED.on_limit,
                    updated_at = NOW()
                """
            ),
            {
                "oid": organization_id,
                "trial": float(payload.get("trial_credits") or 0),
                "promo": float(payload.get("promo_credits") or 0),
                "paid": float(payload.get("paid_credits") or 0),
                "used": float(payload.get("used_credits") or 0),
                "ends": payload.get("trial_ends_at"),
                "req": payload.get("request_limit"),
                "tok": payload.get("token_limit"),
                "agent": payload.get("agent_run_limit"),
                "wf": payload.get("workflow_run_limit"),
                "storage": payload.get("storage_limit_bytes"),
                "on_limit": on_limit,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return await snapshot_budget(organization_id)
