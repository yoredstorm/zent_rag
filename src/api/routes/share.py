# =============================================================================
# Share — página pública de agente compartido (GET sin auth)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.platform.marketplace.marketplace import get_agent_by_share_token

router = APIRouter(prefix="/api/v1/share", tags=["share"])


@router.get("/agents/{token}", summary="Ver agente compartido (público)")
async def shared_agent(token: str):
    agent = await get_agent_by_share_token(token)
    if agent is None:
        raise HTTPException(404, "Link inválido, expirado o sin usos disponibles")
    return agent
