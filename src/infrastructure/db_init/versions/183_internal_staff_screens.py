"""Personal interno de Omnio: pantallas, roles y permisos por usuario.

Revision ID: 178
Revises: 177

Aditiva. Modelo de acceso interno de Zent mientras Zitadel queda pendiente:
- `screens`: catálogo de pantallas de plataforma.
- `platform_role_screens`: pantallas de cada rol. Sin filas = sin acceso.
- `user_screen_permissions`: permiso por usuario y pantalla (`read` | `full`).
- `users.is_platform_staff`: personal de Omnio sin organización y sin ser
  necesariamente superadmin.

Ningún rol trae pantallas por defecto: el superadmin las asigna a mano.
Los usuarios mock solo se siembran con `RAG_ENVIRONMENT` en desarrollo/test.
"""
from __future__ import annotations

import os

from alembic import op

revision: str = "183"
down_revision: str = "182"
branch_labels = None
depends_on = None

_SCREENS: list[tuple[str, str, str, str, int]] = [
    ("overview", "Resumen", "Negocio", "/control-center", 10),
    ("tenants", "Organizaciones", "Negocio", "/control-center/tenants", 20),
    ("customers", "Clientes", "Negocio", "/control-center/customers", 30),
    ("subscriptions", "Suscripciones", "Negocio", "/control-center/subscriptions", 40),
    ("revenue", "Ingresos", "Negocio", "/control-center/revenue", 50),
    ("partners", "Socios", "Negocio", "/control-center/partners", 60),
    ("model-gateway", "Gateway de modelos", "Plataforma de IA", "/control-center/model-gateway", 110),
    ("decision-engine", "Motor de decisión", "Plataforma de IA", "/control-center/decision-engine", 120),
    ("ai-runtime", "Runtime de IA", "Plataforma de IA", "/control-center/ai-runtime", 130),
    ("inference-proxy", "Inferencia", "Plataforma de IA", "/control-center/inference-proxy", 140),
    ("evals", "Evaluaciones", "Plataforma de IA", "/control-center/evals", 150),
    ("feedback", "Feedback", "Plataforma de IA", "/control-center/feedback", 160),
    ("workflows", "Flujos de trabajo", "Plataforma de IA", "/control-center/workflows", 170),
    ("copilot", "Copiloto", "Plataforma de IA", "/control-center/copilot", 180),
    ("analytics", "Analítica", "Observabilidad", "/control-center/analytics", 210),
    ("usage", "Uso", "Observabilidad", "/control-center/usage", 220),
    ("traces", "Trazas", "Observabilidad", "/control-center/traces", 230),
    ("chat-insights", "Insights de chat", "Observabilidad", "/control-center/chat-insights", 240),
    ("model-health", "Salud de modelos", "Observabilidad", "/control-center/model-health", 250),
    ("realtime", "Tiempo real", "Observabilidad", "/control-center/realtime", 260),
    ("costs", "Costos de IA", "FinOps", "/control-center/costs", 310),
    ("metering", "Medición", "FinOps", "/control-center/metering", 320),
    ("cost-governance", "Gobierno de costos", "FinOps", "/control-center/cost-governance", 330),
    ("optimizer", "Optimizador", "FinOps", "/control-center/optimizer", 340),
    ("capacity", "Capacidad", "FinOps", "/control-center/capacity", 350),
    ("trust", "Resumen de confianza", "Confianza", "/control-center/trust", 410),
    ("security-center", "Centro de seguridad", "Confianza", "/control-center/security-center", 420),
    ("trust-safety", "Confianza y seguridad", "Confianza", "/control-center/trust-safety", 430),
    ("risk-center", "Centro de riesgos", "Confianza", "/control-center/risk-center", 440),
    ("governance", "Gobierno", "Confianza", "/control-center/governance", 450),
    ("compliance", "Cumplimiento", "Confianza", "/control-center/compliance", 460),
    ("audit", "Auditoría", "Confianza", "/control-center/audit", 470),
    ("audit-intel", "Inteligencia de auditoría", "Confianza", "/control-center/audit-intel", 480),
    ("status", "Estado del sistema", "Operación", "/control-center/status", 510),
    ("ops-center", "Centro de operaciones", "Operación", "/control-center/ops-center", 520),
    ("operations", "Operaciones", "Operación", "/control-center/operations", 530),
    ("regions", "Regiones", "Operación", "/control-center/regions", 540),
    ("dr", "Recuperación ante desastres", "Operación", "/control-center/dr", 550),
    ("migrations", "Migraciones", "Operación", "/control-center/migrations", 560),
    ("releases", "Versiones", "Operación", "/control-center/releases", 570),
    ("data-export", "Exportación de datos", "Operación", "/control-center/data-export", 580),
    ("marketplace", "Marketplace", "Plataforma", "/control-center/marketplace", 610),
    ("marketplace-factory", "Fábrica de marketplace", "Plataforma", "/control-center/marketplace-factory", 620),
    ("ecosystem", "Ecosistema", "Plataforma", "/control-center/ecosystem", 630),
    ("notifications", "Notificaciones", "Plataforma", "/control-center/notifications", 640),
    ("onboarding", "Onboarding", "Plataforma", "/control-center/onboarding", 650),
    ("security", "Seguridad", "Plataforma", "/control-center/security", 660),
    ("staff", "Usuarios y roles", "Plataforma", "/control-center/staff", 670),
    ("settings", "Configuración", "Plataforma", "/control-center/settings", 680),
]

_MOCK_STAFF: list[tuple[str, str, bool]] = [
    ("admin@omnio.pe", "$2b$12$xrRr5k6SkRj6Ur49yjhlseOGCQElJ4NFsfUfUrACzZRZeWRSxGunK", True),
    ("colivera@omnio.pe", "$2b$12$EZNDR8jGp5wI09byoO6FqekfcwWnO7YU/K//59rHAQ6VVPAefUEIO", False),
    ("ppimentel@omnio.pe", "$2b$12$HeWM5w2wjEPHjfTW.uNnX.HskjoTktWCTyvaAg3CZpfAlDl9RGt/m", False),
    ("creyes@omnio.pe", "$2b$12$ITD2ErptnFMuE5Yyn8deM.lH/f8y2ViHjvM/BaRDq5M..jrJwYm6a", False),
    ("mcamacho@omnio.pe", "$2b$12$QX0XWQruY3IJ0OrSXnjOc.64BQtLO/zHLGdcSPPql5hDgyYQ/9KAe", False),
]


def _seed_screens() -> None:
    values = ", ".join(
        f"('{code}', '{name}', '{category}', '{path}', {order})"
        for code, name, category, path, order in _SCREENS
    )
    op.execute(
        "INSERT INTO screens (code, name, category, path, sort_order) VALUES "
        f"{values} ON CONFLICT (code) DO NOTHING"
    )


def _seed_mock_staff() -> None:
    if os.getenv("RAG_ENVIRONMENT", "").lower() not in ("development", "test", "local"):
        return
    for email, password_hash, is_superadmin in _MOCK_STAFF:
        op.execute(
            "INSERT INTO users (organization_id, external_id, email_hash, role, email, "
            "password_hash, is_platform_admin, is_platform_staff) "
            "SELECT NULL, '{email}', encode(sha256('{email}'::bytea), 'hex'), 'staff', "
            "'{email}', '{password_hash}', {is_admin}, true "
            "WHERE NOT EXISTS (SELECT 1 FROM users WHERE lower(email) = '{email}')".format(
                email=email,
                password_hash=password_hash,
                is_admin="true" if is_superadmin else "false",
            )
        )
    op.execute(
        "INSERT INTO user_platform_roles (user_id, role_id) "
        "SELECT u.id, pr.id FROM users u, platform_roles pr "
        "WHERE lower(u.email) = 'admin@omnio.pe' AND pr.name = 'super_admin' "
        "ON CONFLICT DO NOTHING"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "is_platform_staff BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk"
    )
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
            CHECK (
                is_platform_admin = true
                OR is_platform_staff = true
                OR organization_id IS NOT NULL
            )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS screens (
            code VARCHAR(60) PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            category VARCHAR(60) NOT NULL,
            path VARCHAR(200) NOT NULL,
            sort_order INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_role_screens (
            role_id UUID NOT NULL REFERENCES platform_roles(id) ON DELETE CASCADE,
            screen_code VARCHAR(60) NOT NULL REFERENCES screens(code) ON DELETE CASCADE,
            PRIMARY KEY (role_id, screen_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_screen_permissions (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            screen_code VARCHAR(60) NOT NULL REFERENCES screens(code) ON DELETE CASCADE,
            level VARCHAR(10) NOT NULL DEFAULT 'read'
                CHECK (level IN ('read', 'full')),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, screen_code)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_screen_permissions_user "
        "ON user_screen_permissions(user_id)"
    )
    # Sin id fijo: los UUID de `platform_roles` ya están tomados por los roles
    # de sistema (read_only ocupa el ...0007).
    op.execute(
        "INSERT INTO platform_roles (name, description, is_system) VALUES "
        "('admin', 'Acceso a las pantallas que le asigne el superadmin', false), "
        "('operador', 'Acceso operativo a las pantallas que le asigne el superadmin', false) "
        "ON CONFLICT (name) DO NOTHING"
    )
    _seed_screens()
    _seed_mock_staff()


def downgrade() -> None:
    op.execute(
        "DELETE FROM user_platform_roles upr USING users u "
        "WHERE upr.user_id = u.id AND u.is_platform_staff = true"
    )
    op.execute("DELETE FROM users WHERE is_platform_staff = true")
    op.execute("DELETE FROM platform_roles WHERE name IN ('admin', 'operador')")
    op.execute("DROP TABLE IF EXISTS user_screen_permissions")
    op.execute("DROP TABLE IF EXISTS platform_role_screens")
    op.execute("DROP TABLE IF EXISTS screens")
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk"
    )
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
            CHECK (is_platform_admin = true OR organization_id IS NOT NULL)
        """
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_platform_staff")
