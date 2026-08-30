# =============================================================================
# Embed — mint/revoke tokens + public chat (origin allowlist)
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from src.agents.runtime.agent_runtime import AgentRunRequest
from src.api.deps import get_agent_repo, get_agent_runtime
from src.core.ports import AgentRepository
from src.platform.embed.tokens import (
    get_embed_by_public_id,
    get_embed_for_agent,
    mint_embed_token,
    origin_allowed,
    revoke_embed_token,
)

admin_router = APIRouter(prefix="/api/v1/agents", tags=["Embed"])
public_router = APIRouter(prefix="/api/v1/embed", tags=["Embed"])
widget_router = APIRouter(tags=["Embed"])


class MintEmbedBody(BaseModel):
    allowed_origins: list[str] = Field(..., min_length=1, max_length=20)

    def origins(self) -> list[str]:
        cleaned = []
        for item in self.allowed_origins:
            value = item.strip()
            if not value or len(value) > 500:
                continue
            if value.startswith(("http://", "https://")):
                cleaned.append(value.rstrip("/"))
        if not cleaned:
            raise ValueError("allowed_origins must include http(s) origins")
        return cleaned


class EmbedChatBody(BaseModel):
    model_config = {"extra": "ignore"}

    messages: list[dict] | None = None
    message: str | None = Field(default=None, max_length=8000)


def _request_origin(request: Request) -> str:
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin
    referer = (request.headers.get("referer") or "").strip()
    if referer:
        from urllib.parse import urlparse

        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _last_user_message(body: EmbedChatBody) -> str:
    if body.message and body.message.strip():
        return body.message.strip()
    for item in reversed(body.messages or []):
        if not isinstance(item, dict):
            continue
        if item.get("role") == "user" and str(item.get("content") or "").strip():
            return str(item["content"]).strip()[:8000]
    raise HTTPException(status_code=422, detail="messages must include a user turn")


@admin_router.post("/{agent_id}/embed/token", status_code=201)
async def create_embed_token(
    agent_id: UUID,
    body: MintEmbedBody,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.billing.entitlements import EntitlementDenied, check_entitlement
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        await check_entitlement(ctx.organization_id, "embed_widget")
    except EntitlementDenied:
        raise HTTPException(status_code=403, detail="Plan does not include embed_widget")
    agent = await repo.get_agent(ctx.organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        origins = body.origins()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    token, row = await mint_embed_token(ctx.organization_id, agent_id, origins)
    return {
        "token": token,
        "public_id": row.public_id,
        "allowed_origins": row.allowed_origins,
        "token_prefix": row.token_prefix,
    }


@admin_router.get("/{agent_id}/embed")
async def get_embed_snippet(
    agent_id: UUID,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    agent = await repo.get_agent(ctx.organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    row = await get_embed_for_agent(ctx.organization_id, agent_id)
    host = str(request.base_url).rstrip("/")
    if row is None:
        return {
            "public_id": None,
            "script": None,
            "iframe_src": None,
            "allowed_origins": [],
            "revoked": False,
        }
    return {
        "public_id": row.public_id,
        "script": (
            f'<script src="{host}/embed.js" data-embed="{row.public_id}"></script>'
        ),
        "iframe_src": f"{host}/embed/{row.public_id}",
        "allowed_origins": row.allowed_origins,
        "revoked": row.revoked_at is not None,
    }


@admin_router.post("/{agent_id}/embed/revoke")
async def revoke_embed(
    agent_id: UUID,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await repo.get_agent(ctx.organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await revoke_embed_token(ctx.organization_id, agent_id)
    return {"status": "revoked"}


@public_router.post("/{public_id}/chat")
async def embed_chat(
    public_id: str,
    body: EmbedChatBody,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
    runtime=Depends(get_agent_runtime),
):
    row = await get_embed_by_public_id(public_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Embed not found")
    if row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Embed token revoked")
    origin = _request_origin(request)
    self_origin = str(request.base_url).rstrip("/")
    if not (
        origin_allowed(origin, row.allowed_origins)
        or origin_allowed(origin, [self_origin])
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    agent = await repo.get_agent(row.organization_id, row.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")
    message = _last_user_message(body)
    result = await runtime.run(
        AgentRunRequest(
            agent=agent,
            message=message,
            role="customer",
        )
    )
    payload = {"answer": result.answer, "status": result.status}
    response = JSONResponse(payload)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response


@widget_router.get("/embed.js")
async def embed_js() -> Response:
    script = """(function () {
  var current = document.currentScript;
  var id = current && current.getAttribute("data-embed");
  if (!id) return;
    var src = current.src || "";
  var host = src.replace(/\\/embed\\.js.*$/, "");
  var frame = document.createElement("iframe");
  frame.src = host + "/embed/" + encodeURIComponent(id);
  frame.title = "Chat";
  frame.style.cssText = "border:0;width:100%;max-width:380px;height:520px;";
  current.parentNode.insertBefore(frame, current.nextSibling);
})();"""
    return Response(content=script, media_type="application/javascript")


@widget_router.get("/embed/{public_id}")
async def embed_iframe(public_id: str, repo: AgentRepository = Depends(get_agent_repo)):
    from html import escape as html_escape
    row = await get_embed_by_public_id(public_id)
    title = "Asistente"
    if row and row.revoked_at is None:
        agent = await repo.get_agent(row.organization_id, row.agent_id)
        if agent is not None:
            embed_cfg = (agent.config_json or {}).get("embed") or {}
            title = str(embed_cfg.get("title") or agent.name or title)
    safe_title = html_escape(title)
    safe_public_id = html_escape(public_id)
    ancestors = " ".join(row.allowed_origins) if row else "'none'"
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="Content-Security-Policy" content="frame-ancestors {ancestors}"/>
<title>{safe_title}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#eee}}
header{{padding:12px 16px;border-bottom:1px solid #2a2e38;font-weight:600}}
#log{{height:400px;overflow:auto;padding:12px 16px;font-size:14px}}
.msg{{margin:0 0 10px;white-space:pre-wrap}}
form{{display:flex;gap:8px;padding:12px;border-top:1px solid #2a2e38}}
input,button{{min-height:44px;font:inherit}}
input{{flex:1;border-radius:8px;border:1px solid #3a3f4b;background:#1a1d24;color:#eee;padding:0 10px}}
button{{border:0;border-radius:8px;background:#3d7a5a;color:#fff;padding:0 14px}}
</style></head>
<body>
<header>{safe_title}</header>
<div id="log"></div>
<form id="f">
<input id="q" autocomplete="off" placeholder="Escribe tu pregunta"/>
<button type="submit">Enviar</button>
</form>
<script>
const log = document.getElementById("log");
function add(role, text) {{
  const p = document.createElement("p");
  p.className = "msg";
  p.textContent = role + ": " + text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}}
document.getElementById("f").addEventListener("submit", async (e) => {{
  e.preventDefault();
  const input = document.getElementById("q");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  add("Tú", text);
  try {{
    const res = await fetch("/api/v1/embed/{safe_public_id}/chat", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{messages: [{{role: "user", content: text}}]}})
    }});
    const data = await res.json();
    add("Agente", data.answer || data.message || data.detail || "Error");
  }} catch (err) {{
    add("Agente", "No se pudo responder.");
  }}
}});
</script>
</body></html>"""
    return HTMLResponse(html)
