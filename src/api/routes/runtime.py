# =============================================================================
# Zent AI Runtime Control Center APIs.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.platform.billing.pricing import list_price_history, list_prices, upsert_price
from src.platform.rbac.authorization import require_platform_permission
from src.platform.rbac.policy import require_platform_admin
from src.runtime.dashboard import (
    list_capabilities,
    load_efficiency_weights,
    profitability_snapshot,
    runtime_dashboard,
    save_efficiency_weights,
    tenant_usage_breakdown,
)
from src.runtime.wallet import public_wallet, snapshot_budget, upsert_wallet

router = APIRouter(prefix="/api/v1/platform/runtime", tags=["Zent AI Runtime"])


class ProviderCostIn(BaseModel):
    provider: str = Field(..., min_length=1, max_length=60)
    model: str = Field(..., min_length=1, max_length=120)
    input_cost_per_1k: float = Field(0, ge=0, le=100)
    output_cost_per_1k: float = Field(0, ge=0, le=100)
    embedding_cost_per_1k: float = Field(0, ge=0, le=100)
    request_cost: float = Field(0, ge=0, le=100)
    cost_kind: str = Field("provider", max_length=20)
    currency: str = Field("USD", max_length=3)


class WalletIn(BaseModel):
    trial_credits: float = Field(0, ge=0)
    promo_credits: float = Field(0, ge=0)
    paid_credits: float = Field(0, ge=0)
    used_credits: float = Field(0, ge=0)
    trial_ends_at: str | None = None
    request_limit: int | None = Field(None, ge=0)
    token_limit: int | None = Field(None, ge=0)
    agent_run_limit: int | None = Field(None, ge=0)
    workflow_run_limit: int | None = Field(None, ge=0)
    storage_limit_bytes: int | None = Field(None, ge=0)
    on_limit: str = Field("block", max_length=20)


class EfficiencyIn(BaseModel):
    quality: float = Field(0.40, ge=0, le=1)
    cost: float = Field(0.25, ge=0, le=1)
    latency: float = Field(0.20, ge=0, le=1)
    fallback: float = Field(0.15, ge=0, le=1)


class ExperimentCase(BaseModel):
    request: str
    expected_capability: str = ""
    sql_enabled: bool = True
    knowledge_enabled: bool = True


class ExperimentIn(BaseModel):
    cases: list[ExperimentCase] = Field(default_factory=list)


@router.get("/dashboard", summary="AI Runtime dashboard")
async def runtime_dashboard_endpoint(request: Request) -> dict:
    require_platform_permission(request, "analytics.read")
    return await runtime_dashboard()


@router.get("/capabilities", summary="Capability registry")
async def runtime_capabilities(request: Request) -> dict:
    require_platform_permission(request, "operations.read")
    return {"items": list_capabilities()}


@router.get("/providers", summary="Provider cost registry")
async def runtime_providers(request: Request) -> dict:
    require_platform_permission(request, "billing.read")
    return {"prices": await list_prices()}


@router.put("/providers", summary="Update provider cost")
async def runtime_providers_put(body: ProviderCostIn, request: Request) -> dict:
    require_platform_permission(request, "billing.manage")
    await upsert_price(
        provider=body.provider,
        model=body.model,
        input_cost_per_1k=body.input_cost_per_1k,
        output_cost_per_1k=body.output_cost_per_1k,
        embedding_cost_per_1k=body.embedding_cost_per_1k,
        currency=body.currency,
        request_cost=body.request_cost,
        cost_kind=body.cost_kind,
    )
    return {"status": "updated", "provider": body.provider, "model": body.model}


@router.get("/providers/history", summary="Historical provider costs")
async def runtime_providers_history(
    request: Request,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    require_platform_permission(request, "billing.read")
    return {"items": await list_price_history(provider, model)}


@router.get("/wallets/{org_id}", summary="Tenant wallet")
async def runtime_wallet_get(org_id: str, request: Request) -> dict:
    require_platform_permission(request, "billing.read")
    try:
        oid = UUID(org_id)
    except ValueError as exc:
        raise HTTPException(404, "Organization not found") from exc
    usage = await tenant_usage_breakdown(oid)
    wallet = public_wallet(await snapshot_budget(oid))
    return {"organization_id": str(oid), "wallet": wallet, "usage": usage}


@router.put("/wallets/{org_id}", summary="Update tenant wallet / trial")
async def runtime_wallet_put(org_id: str, body: WalletIn, request: Request) -> dict:
    require_platform_permission(request, "billing.manage")
    try:
        oid = UUID(org_id)
    except ValueError as exc:
        raise HTTPException(404, "Organization not found") from exc
    wallet = await upsert_wallet(oid, body.model_dump())
    return {"organization_id": str(oid), "wallet": public_wallet(wallet)}


@router.get("/efficiency", summary="AI Efficiency Score weights")
async def runtime_efficiency_get(request: Request) -> dict:
    require_platform_permission(request, "analytics.read")
    weights = await load_efficiency_weights()
    return {"weights": weights, "components": ["quality", "cost", "latency", "fallback"]}


@router.put("/efficiency", summary="Configure efficiency weights")
async def runtime_efficiency_put(body: EfficiencyIn, request: Request) -> dict:
    require_platform_admin(request)
    weights = await save_efficiency_weights(body.model_dump())
    return {"weights": weights}


@router.get("/profitability", summary="Internal margin (Super Admin)")
async def runtime_profitability(request: Request) -> dict:
    require_platform_admin(request)
    return await profitability_snapshot()


@router.post("/experiments", summary="Compare Rules / JEV / LLM on a dataset")
async def runtime_experiments(body: ExperimentIn, request: Request) -> dict:
    require_platform_permission(request, "operations.read")
    from src.decision.service import get_decision_engine
    from src.runtime.experiments import run_comparison, summarize

    engine = get_decision_engine()
    provider = engine.provider
    cases: list[dict[str, Any]] = [c.model_dump() for c in body.cases[:200]]
    report = await run_comparison(
        cases,
        rules=getattr(provider, "rules", None) or provider,
        jev=getattr(provider, "jev", None),
        small_llm=getattr(provider, "llm", None),
        reasoning=getattr(provider, "reasoning", None),
        settings=engine.settings,
    )
    return {"report": report, "summary": summarize(report)}
