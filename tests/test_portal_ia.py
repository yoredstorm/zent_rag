# =============================================================================
# Portal IA — Knowledge Center routes, redirects, and role-gated nav
# =============================================================================
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "portal" / "src"


def test_portal_knowledge_center_routes_and_redirects() -> None:
    app = (PORTAL / "App.tsx").read_text(encoding="utf-8")
    for path in (
        "/knowledge/sources",
        "/knowledge/collections",
        "/knowledge/documents",
        "/knowledge/sql",
        "/knowledge/jobs",
        "/knowledge/playground",
        "/billing",
        "/settings",
    ):
        assert path in app, f"missing route {path}"
    assert 'path="/ingestion"' in app
    assert 'to="/knowledge/sql"' in app
    assert 'path="/knowledge-bases"' in app
    assert 'to="/knowledge/collections"' in app
    assert "Pregúntale a tus datos" in app or "/chat" in app
    assert "/keys" in app
    assert "/prompts" in app
    assert "/audit" in app
    assert "/agents/new" in app
    login = (PORTAL / "pages" / "Login.tsx").read_text(encoding="utf-8")
    assert "Olvidé mi contraseña" in login
    assert "/api/v1/auth/forgot-password" in login
    assert "/agents/:id" in app
    assert "/evaluation/datasets" in app
    assert "/evaluation/runs" in app
    assert "/evaluation/compare" in app
    assert "eval_ui" in app


def test_portal_agent_builder_has_tabs_and_playground() -> None:
    builder = (PORTAL / "pages" / "AgentBuilder.tsx").read_text(encoding="utf-8")
    for tab in (
        "Instructions",
        "Knowledge",
        "Tools",
        "Model",
        "Security",
        "Limits",
        "Analytics",
        "Playground",
        "Embed",
    ):
        assert tab in builder, f"missing tab {tab}"
    assert "/api/v1/agents/${id}/run/stream" in builder or "/run/stream" in builder
    assert "/api/v1/billing/usage/agents" in builder
    assert "search_knowledge" in builder
    assert "/api/v1/gateway/routes" in builder
    assert "zent-default" in builder
    assert "query_database" in builder

    listing = (PORTAL / "pages" / "Agents.tsx").read_text(encoding="utf-8")
    assert "/agents/new" in listing
    assert "max_agents" in listing


def test_portal_control_center_routes_are_separate_from_customer_nav() -> None:
    app = (PORTAL / "App.tsx").read_text(encoding="utf-8")
    assert 'path="/admin"' in app or 'path="/admin/login"' in app
    assert "/admin/login" in app
    assert 'path="customers"' in app
    assert 'path="plans"' in app
    assert 'path="usage"' in app
    usage = (PORTAL / "pages" / "admin" / "Usage.tsx").read_text(encoding="utf-8")
    assert "/api/v1/platform/finops/summary" in usage
    assert "Economía AI" in usage
    assert "help=" in usage
    customers = (PORTAL / "pages" / "admin" / "Customers.tsx").read_text(encoding="utf-8")
    assert "trialing" in customers
    assert "amount_due_cents" in customers
    layout = (PORTAL / "pages" / "admin" / "AdminLayout.tsx").read_text(encoding="utf-8")
    assert "/api/v1/platform/notifications" in layout
    assert "rag_platform_token" in (PORTAL / "platformAuth.tsx").read_text(encoding="utf-8")


def test_portal_keys_page_splits_production_and_development() -> None:
    keys = (PORTAL / "pages" / "Keys.tsx").read_text(encoding="utf-8")
    assert "Production" in keys
    assert "Development" in keys
    assert "environment" in keys
    assert "zent_sk_test" in keys or 'environment: "test"' in keys
    assert "knowledge:read" in keys
    assert "analytics:read" in keys


def test_portal_nav_hides_users_and_keys_for_viewers() -> None:
    nav = (PORTAL / "App.tsx").read_text(encoding="utf-8") + (
        PORTAL / "auth.tsx"
    ).read_text(encoding="utf-8")
    assert "roles" in nav
    assert "viewer" in nav
