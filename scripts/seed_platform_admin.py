#!/usr/bin/env python
# ruff: noqa: T201
"""Seed idempotente de un platform admin del Control Center.

Uso (desde la raíz del repo, con .env cargando RAG_POSTGRES_*):
    python scripts/seed_platform_admin.py --email ppimentel@omnio.pe
    python scripts/seed_platform_admin.py --email x@y.z --password 'secreta'

Sin --password usa RAG_PORTAL_DEV_PASSWORD del entorno/.env. Si el usuario ya
existe y tiene password, no lo pisa (usa --password o --reset-password para
forzarlo). Si el email ya existe como usuario tenant, lo promueve a platform
admin conservando su organización (identidad dual, migración 140); si no
existe, crea la fila is_platform_admin con organization_id NULL. Asigna el rol
de plataforma (default super_admin) y es seguro de re-ejecutar.

En producción el bootstrap automático del API no corre (solo development):
este script es la vía soportada para provisionar el admin.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def seed(email: str, password: str | None, role: str, reset_password: bool) -> int:
    from sqlalchemy import text

    from src.core.config import get_settings
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.infrastructure.postgres.session import (
        close_db_connections,
        get_async_session,
    )
    from src.platform.auth.passwords import hash_password
    from src.platform.rbac.repo import assign_platform_role

    settings = get_settings()
    normalized = email.strip().lower()
    repo = PostgresUserRepository()

    explicit_password = password is not None
    if password is None:
        secret = settings.PORTAL_DEV_PASSWORD
        password = secret.get_secret_value() if secret is not None else None

    try:
        user = await repo.get_by_email(normalized)
        if user is None:
            session = await get_async_session()
            try:
                await session.execute(
                    text(
                        "INSERT INTO users "
                        "(id, organization_id, external_id, email_hash, role, email, "
                        "password_hash, is_platform_admin, created_at) "
                        "VALUES (:id, NULL, 'platform-admin', :email_hash, 'admin', "
                        "CAST(:email AS varchar), NULL, true, now())"
                    ),
                    {
                        "id": str(uuid4()),
                        "email_hash": hashlib.sha256(normalized.encode()).hexdigest(),
                        "email": normalized,
                    },
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
            user = await repo.get_by_email(normalized)
            if user is None:
                print("ERROR: no se pudo crear el usuario.", file=sys.stderr)
                return 1
            print(f"Platform admin creado: {normalized} ({user.id})")
        else:
            org_note = f", org {user.organization_id}" if user.organization_id else ""
            print(f"Usuario existente: {normalized} ({user.id}{org_note})")
            if not user.is_platform_admin:
                session = await get_async_session()
                try:
                    await session.execute(
                        text(
                            "UPDATE users SET is_platform_admin = true "
                            "WHERE id = :uid"
                        ),
                        {"uid": user.id},
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()
                user = await repo.get_by_email(normalized)
                print("Promovido a platform admin (conserva su organización).")

        if password and (explicit_password or reset_password or not user.password_hash):
            await repo.set_password(user.id, hash_password(password))
            print("Password establecido.")
        elif not user.password_hash:
            print(
                "WARN: el usuario no tiene password. Pasa --password o define "
                "RAG_PORTAL_DEV_PASSWORD.",
                file=sys.stderr,
            )

        if user.disabled_at:
            print(
                "WARN: el usuario está suspendido (disabled_at). Reactívalo desde "
                "el Control Center antes de probar.",
                file=sys.stderr,
            )

        changed = await assign_platform_role(user.id, role)
        print(f"Rol de plataforma {'asignado' if changed else 'ya presente'}: {role}")
        print("Listo.")
        return 0
    finally:
        await close_db_connections()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Email del platform admin")
    parser.add_argument(
        "--password", default=None, help="Password explícito (opcional)"
    )
    parser.add_argument(
        "--role",
        default="super_admin",
        help="Rol de plataforma a asignar (default: super_admin)",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Sobrescribe el password existente aunque no pases --password",
    )
    args = parser.parse_args()
    return asyncio.run(seed(args.email, args.password, args.role, args.reset_password))


if __name__ == "__main__":
    raise SystemExit(main())
