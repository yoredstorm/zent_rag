# =============================================================================
# SCIM 2.0 — provisioning de usuarios y grupos (mapping grupo → rol de tenant)
# Auth: Bearer token SCIM de la organización (X-Organization-Id header).
# =============================================================================
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

router = APIRouter(prefix="/api/v1/scim/v2", tags=["scim"])


class ScimAuthError(Exception):
    pass


async def _resolve_org(request: Request) -> UUID:
    """Bearer token SCIM + X-Organization-Id; 401 si no coincide."""
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    org_header = request.headers.get("X-Organization-Id", "")
    if not token or not org_header:
        raise ScimAuthError("SCIM token y X-Organization-Id requeridos")
    try:
        oid = UUID(org_header)
    except ValueError:
        raise ScimAuthError("X-Organization-Id inválido")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT scim_token_hash FROM organizations "
                    "WHERE id = :oid AND scim_enabled = true"
                ),
                {"oid": oid},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or row.scim_token_hash != token_hash:
        raise ScimAuthError("SCIM token inválido")
    return oid


def _user_resource(user_id: str, email: str, display_name: str, active: bool) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": user_id,
        "userName": email,
        "displayName": display_name,
        "active": active,
        "emails": [{"value": email, "primary": True}],
        "meta": {
            "resourceType": "User",
            "created": datetime.now(timezone.utc).isoformat(),
            "lastModified": datetime.now(timezone.utc).isoformat(),
        },
    }


def _group_resource(g: dict) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "id": str(g["id"]),
        "displayName": g["display_name"],
        "role": g["role_name"],
        "members": g["members"] or [],
        "meta": {
            "resourceType": "Group",
            "created": g["created_at"].isoformat(),
            "lastModified": g["created_at"].isoformat(),
        },
    }


class ScimUserIn(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:User"])
    userName: str
    externalId: str | None = None
    displayName: str | None = None
    active: bool = True
    emails: list[dict] | None = None
    role: str | None = None


class ScimGroupIn(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:Group"])
    displayName: str
    role: str = "member"
    members: list[dict] = Field(default_factory=list)


class ScimGroupPatch(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:Group"])
    displayName: str | None = None
    role: str | None = None
    members: list[dict] | None = None


async def _scim_guard(request: Request):
    try:
        return await _resolve_org(request)
    except ScimAuthError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.get("/ServiceProviderConfig", summary="SCIM: config del proveedor")
async def service_provider_config():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False},
        "filter": {"supported": True, "maxResults": 100},
        "etag": {"supported": False},
        "authenticationSchemes": [{"name": "Bearer", "type": "oauthbearertoken"}],
    }


@router.get("/ResourceTypes", summary="SCIM: tipos de recurso")
async def resource_types():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "totalResults": 2,
        "Resources": [
            {"id": "User", "name": "User", "endpoint": "/Users", "schema": "urn:ietf:params:scim:schemas:core:2.0:User"},  # noqa: E501
            {"id": "Group", "name": "Group", "endpoint": "/Groups", "schema": "urn:ietf:params:scim:schemas:core:2.0:Group"},  # noqa: E501
        ],
    }


@router.get("/Schemas", summary="SCIM: schemas soportados")
async def schemas():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
        "totalResults": 2,
        "Resources": [
            {
                "id": "urn:ietf:params:scim:schemas:core:2.0:User",
                "name": "User",
                "attributes": [
                    {"name": "userName", "type": "string", "required": True},
                    {"name": "displayName", "type": "string"},
                    {"name": "active", "type": "boolean"},
                ],
            },
            {
                "id": "urn:ietf:params:scim:schemas:core:2.0:Group",
                "name": "Group",
                "attributes": [
                    {"name": "displayName", "type": "string", "required": True},
                    {"name": "role", "type": "string"},
                    {"name": "members", "type": "complex", "multiValued": True},
                ],
            },
        ],
    }


@router.post("/Users", status_code=201, summary="SCIM: crear usuario")
async def create_user(body: ScimUserIn, request: Request):
    oid = await _scim_guard(request)
    from src.infrastructure.postgres.relational_db import (
        PostgresMembershipRepository,
        PostgresUserRepository,
    )

    email = (body.userName or "").strip().lower()
    if not email:
        raise HTTPException(400, "userName (email) requerido")
    ext = body.externalId or f"scim:{uuid4().hex}"
    user_repo = PostgresUserRepository()
    existing = await user_repo.get_by_email(email)
    if existing is not None and str(existing.organization_id) == str(oid):
        raise HTTPException(409, "Usuario ya existe")
    user_id = await user_repo.create_sso_user(oid, email, external_id=ext[:255])
    await PostgresMembershipRepository().assign_role(
        oid, user_id, body.role or "member"
    )
    return _user_resource(
        str(user_id), email, body.displayName or email, bool(body.active)
    )


@router.get("/Users", summary="SCIM: listar/filtrar usuarios")
async def list_users(request: Request, filter: str | None = None):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        sql = (
            "SELECT u.id, u.email, u.external_id, r.name AS role_name "
            "FROM users u LEFT JOIN memberships m ON m.user_id = u.id "
            "AND m.organization_id = u.organization_id "
            "LEFT JOIN roles r ON r.id = m.role_id "
            "WHERE u.organization_id = :oid "
        )
        params: dict = {"oid": oid}
        if filter:
            lowered = filter.lower()
            if "username eq" in lowered:
                email = filter.split("eq")[-1].strip().strip('"').lower()
                sql += " AND lower(u.email) = :email "
                params["email"] = email
            elif "externalid eq" in lowered:
                ext = filter.split("eq")[-1].strip().strip('"')
                sql += " AND u.external_id = :ext "
                params["ext"] = ext
        sql += " ORDER BY u.created_at DESC"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ListResponse"],
        "totalResults": len(rows),
        "Resources": [
            _user_resource(str(r.id), r.email or r.external_id, r.email or r.external_id, True)
            for r in rows
        ],
    }


@router.get("/Users/{user_id}", summary="SCIM: obtener usuario")
async def get_user(user_id: str, request: Request):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, email, external_id FROM users "
                    "WHERE id = :uid AND organization_id = :oid"
                ),
                {"uid": user_id, "oid": oid},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "User not found")
    return _user_resource(str(row.id), row.email or row.external_id, row.email or row.external_id, True)


@router.put("/Users/{user_id}", summary="SCIM: actualizar usuario")
async def put_user(user_id: str, body: ScimUserIn, request: Request):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT id, email FROM users WHERE id = :uid AND organization_id = :oid"),
                {"uid": user_id, "oid": oid},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(404, "User not found")
        new_email = (body.userName or row.email or "").strip().lower()
        await session.execute(
            text("UPDATE users SET email = :email WHERE id = :uid"),
            {"email": new_email, "uid": row.id},
        )
        await session.commit()
    finally:
        await session.close()
    if body.role:
        from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

        try:
            await PostgresMembershipRepository().assign_role(oid, row.id, body.role)
        except ValueError:
            raise HTTPException(400, f"Rol '{body.role}' no existe")
    return _user_resource(str(row.id), new_email, body.displayName or new_email, True)


@router.patch("/Users/{user_id}", summary="SCIM: actualizar parcial (active/role)")
async def patch_user(user_id: str, request: Request):
    oid = await _scim_guard(request)
    body = await request.json()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT id, email FROM users WHERE id = :uid AND organization_id = :oid"),
                {"uid": user_id, "oid": oid},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(404, "User not found")
        role = None
        for op in body.get("Operations", []):
            path = (op.get("path") or "").lower()
            value = op.get("value")
            if path == "active" or (path == "" and isinstance(value, bool)):
                pass  # SCIM activo→desactivado = quitar membresías
                if isinstance(value, bool) and value is False:
                    await session.execute(
                        text(
                            "DELETE FROM memberships WHERE user_id = :uid "
                            "AND organization_id = :oid"
                        ),
                        {"uid": row.id, "oid": oid},
                    )
            elif path in ("displayname", "display_name"):
                pass
            elif path == "role":
                role = value
        if role:
            from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

            try:
                await PostgresMembershipRepository().assign_role(oid, row.id, role)
            except ValueError:
                raise HTTPException(400, f"Rol '{role}' no existe")
        await session.commit()
    finally:
        await session.close()
    return _user_resource(str(row.id), row.email, row.email, True)


@router.delete("/Users/{user_id}", status_code=204, summary="SCIM: desactivar usuario")
async def delete_user(user_id: str, request: Request):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT id FROM users WHERE id = :uid AND organization_id = :oid"),
                {"uid": user_id, "oid": oid},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(404, "User not found")
        await session.execute(
            text("DELETE FROM memberships WHERE user_id = :uid AND organization_id = :oid"),
            {"uid": row.id, "oid": oid},
        )
        await session.commit()
    finally:
        await session.close()
    return None


@router.get("/Groups", summary="SCIM: listar grupos")
async def list_groups(request: Request):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, display_name, role_name, members, created_at "
                    "FROM scim_groups WHERE organization_id = :oid ORDER BY display_name"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ListResponse"],
        "totalResults": len(rows),
        "Resources": [_group_resource(r) for r in rows],
    }


@router.post("/Groups", status_code=201, summary="SCIM: crear grupo (mapping a rol)")
async def create_group(body: ScimGroupIn, request: Request):
    oid = await _scim_guard(request)
    members = [m.get("value") for m in body.members if m.get("value")]
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "INSERT INTO scim_groups (id, organization_id, display_name, role_name, members) "
                "VALUES (gen_random_uuid(), :oid, :name, :role, :members) "
                "ON CONFLICT (organization_id, display_name) DO NOTHING RETURNING id"
            ),
            {
                "oid": oid,
                "name": body.displayName,
                "role": body.role,
                "members": __import__("json").dumps(members),
            },
        )
        gid = result.scalar()
        await session.commit()
    finally:
        await session.close()
    if gid is None:
        raise HTTPException(409, "Grupo ya existe")
    # Asignar rol a los miembros existentes.
    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

    session = await get_async_session()
    try:
        user_rows = (
            await session.execute(
                text(
                    "SELECT id FROM users WHERE organization_id = :oid "
                    "AND external_id = ANY(:exts)"
                ),
                {"oid": oid, "exts": members},
            )
        ).fetchall()
    finally:
        await session.close()
    for u in user_rows:
        try:
            await PostgresMembershipRepository().assign_role(oid, u.id, body.role)
        except ValueError:
            pass
    return _group_resource(
        {
            "id": gid,
            "display_name": body.displayName,
            "role_name": body.role,
            "members": members,
            "created_at": datetime.now(timezone.utc),
        }
    )


@router.patch("/Groups/{group_id}", summary="SCIM: actualizar grupo (members/role)")
async def patch_group(group_id: str, request: Request):
    oid = await _scim_guard(request)
    body = await request.json()
    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

    session = await get_async_session()
    try:
        group = (
            await session.execute(
                text(
                    "SELECT id, display_name, role_name, members, created_at "
                    "FROM scim_groups "
                    "WHERE id = :gid AND organization_id = :oid"
                ),
                {"gid": group_id, "oid": oid},
            )
        ).fetchone()
        if group is None:
            raise HTTPException(404, "Group not found")
        members = list(group.members or [])
        new_role = group.role_name
        for op in body.get("Operations", []):
            path = (op.get("path") or "").lower()
            if path == "members":
                values = [m.get("value") for m in (op.get("value") or []) if m.get("value")]
                if (op.get("op") or "").lower() == "add":
                    members = list(dict.fromkeys(members + values))
                elif (op.get("op") or "").lower() == "remove":
                    members = [m for m in members if m not in set(values)]
            elif path == "role":
                new_role = op.get("value") or new_role
            elif path == "displayname":
                pass
        await session.execute(
            text(
                "UPDATE scim_groups SET members = :members, role_name = :role "
                "WHERE id = :gid"
            ),
            {
                "members": __import__("json").dumps(members),
                "role": new_role,
                "gid": group.id,
            },
        )
        # Re-sincronizar roles de los miembros.
        user_rows = (
            await session.execute(
                text(
                    "SELECT id, external_id FROM users WHERE organization_id = :oid"
                ),
                {"oid": oid},
            )
        ).fetchall()
        await session.commit()
    finally:
        await session.close()
    for u in user_rows:
        if u.external_id in members:
            try:
                await PostgresMembershipRepository().assign_role(oid, u.id, new_role)
            except ValueError:
                pass
    return _group_resource(
        {
            "id": group.id,
            "display_name": group.display_name,
            "role_name": new_role,
            "members": members,
            "created_at": group.created_at,
        }
    )


@router.delete("/Groups/{group_id}", status_code=204, summary="SCIM: eliminar grupo")
async def delete_group(group_id: str, request: Request):
    oid = await _scim_guard(request)
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM scim_groups WHERE id = :gid AND organization_id = :oid"),
            {"gid": group_id, "oid": oid},
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Group not found")
    finally:
        await session.close()
    return None
