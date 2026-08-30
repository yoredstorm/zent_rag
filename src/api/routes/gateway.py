# =============================================================================
# AI Gateway — catalog of virtual model routes (no provider secrets)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Request

from src.platform.gateway.router import list_route_catalog

router = APIRouter(prefix="/api/v1/gateway", tags=["Gateway"])


@router.get("/routes", summary="Rutas virtuales del AI Gateway")
async def gateway_routes(request: Request):
    from src.api.security import resolve_organization

    resolve_organization(request)
    return {"routes": list_route_catalog()}
