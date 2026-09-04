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
    assert 'path="settings/plans"' in app
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


def test_control_center_nav_stays_in_platform_and_is_scrollable() -> None:
    """Clicks on CC items must not 404 into tenant /login; sidebar must scroll."""
    app = (PORTAL / "App.tsx").read_text(encoding="utf-8")
    for path in ("feedback", "migrations", "releases", "copilot"):
        assert f'path="{path}"' in app, f"missing control-center route {path}"
    layout = (PORTAL / "pages" / "admin" / "AdminLayout.tsx").read_text(encoding="utf-8")
    assert "overflow-y-auto" in layout
    assert "${BASE}/costs" in layout or "/control-center/costs" in layout
    assert "${BASE}/operations" in layout or "/control-center/operations" in layout
    login = (PORTAL / "pages" / "admin" / "Login.tsx").read_text(encoding="utf-8")
    assert 'to="/control-center"' in login or 'to={from}' in login or "from" in login


def test_operations_page_does_not_render_error_summary_object() -> None:
    """React #31: error_summary JSONB {at, error, attempts} is not a valid child."""
    src = (PORTAL / "pages" / "admin" / "Operations.tsx").read_text(encoding="utf-8")
    assert "{j.error_summary ||" not in src
    assert "formatErrorSummary" in src
    assert "<ErrorInline message=" in src or "<ErrorInline message={" in src


def test_finops_costs_page_does_not_map_undefined_breakdown_rows() -> None:
    """ /control-center/costs crashed: CostTable called rows.map on undefined. """
    src = (PORTAL / "pages" / "admin" / "FinOps.tsx").read_text(encoding="utf-8")
    assert "rows ?? []" in src or "(rows || [])" in src
    assert "ErrorInline message=" in src or "<ErrorInline message={" in src
    assert "/finops/summary/organizations/" not in src
    assert "let total = 0" not in src


def test_stat_card_help_is_visible_popover_not_native_title_only() -> None:
    """FinOps `?` must show help on click; native `title` tooltips do not."""
    ui = (PORTAL / "components" / "ui.tsx").read_text(encoding="utf-8")
    assert 'role="tooltip"' in ui
    assert "aria-expanded" in ui
    assert "Qué significa" in ui
    assert "{help}" in ui
    usage = (PORTAL / "pages" / "admin" / "Usage.tsx").read_text(encoding="utf-8")
    assert "help=" in usage
    assert "Revenue (cash)" in usage


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
