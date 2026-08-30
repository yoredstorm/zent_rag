# =============================================================================
# Architecture Guard Tests — dependencias permitidas/prohibidas por capa
# =============================================================================
# Ejecuta análisis AST sobre src/ para garantizar que el refactor no se
# revierta por accidente:
#   A) core/ no importa nada fuera de src.core (sin frameworks ni adaptadores).
#   B) infrastructure/ no importa api/rag/agents/platform/connectors/verticals.
#   C) core/rag/agents/platform no contienen strings de negocio vertical.
#   D) rag/ y agents/ no importan infrastructure (adaptadores) directamente.
# =============================================================================
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Excepciones puntuales y documentadas:
# - logging/métricas son concerns ambientales permitidos en cualquier capa.
_AMBIENT_MODULES = {
    "src.infrastructure.observability.logging_config",
    "src.infrastructure.observability.metrics",
    "src.infrastructure.observability.tracing",
}
# - Fábrica de sesión de datos: las capas superiores acceden SOLO a la
#   fábrica (session.py); los repositorios concretos viven en relational_db.
#   (Paso intermedio hasta inyectar sesiones por DI.)
_DATA_ACCESS_FACTORIES = {
    "src.infrastructure.postgres.session",
    # Pool read-only del SQL Expert (mismo rol de fábrica de sesión).
    "src.infrastructure.postgres.readonly_session",
}


def _py_files(layer: str) -> list[Path]:
    return sorted((SRC / layer).rglob("*.py"))


def _is_shim(path: Path) -> bool:
    """Los shims de migración (DEPRECATED SHIM) quedan fuera de las guardas."""
    try:
        first_lines = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
    except OSError:
        return False
    return "DEPRECATED SHIM" in first_lines


def _imports_of(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def test_core_imports_only_core() -> None:
    """core/ es una isla: nada de api/platform/rag/agents/connectors/infra."""
    violations: list[str] = []
    for path in _py_files("core"):
        if _is_shim(path):
            continue
        for mod in _imports_of(path):
            if mod.startswith("src.") and not mod.startswith("src.core"):
                violations.append(f"{path.relative_to(ROOT)}: imports {mod}")
    assert not violations, "core/ importa fuera de core:\n" + "\n".join(violations)


def test_infrastructure_imports_no_upper_layers() -> None:
    """infrastructure/ solo implementa puertos; no conoce capas superiores."""
    forbidden = ("src.api", "src.rag", "src.agents", "src.platform", "src.connectors", "src.verticals")
    # Pre-existing (Fase 04 Stripe apply + Qdrant tenant filter). Do not add more.
    allowed_infra_platform = {
        "src/infrastructure/billing/stripe_provider.py": (
            "src.platform.billing.entitlements",
        ),
        "src/infrastructure/qdrant/vector_store.py": (
            "src.platform.tenants.context",
        ),
    }
    violations: list[str] = []
    for path in _py_files("infrastructure"):
        if _is_shim(path):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        allowed = allowed_infra_platform.get(rel, ())
        for mod in _imports_of(path):
            if mod.startswith(forbidden) and not any(
                mod == a or mod.startswith(a + ".") for a in allowed
            ):
                violations.append(f"{rel}: imports {mod}")
    assert not violations, "infrastructure/ importa capas superiores:\n" + "\n".join(violations)


def test_rag_and_agents_do_not_import_adapters() -> None:
    """rag/ y agents/ dependen solo de puertos (DI); nunca de adaptadores.

    Excepciones: módulos ambientales (logging/métricas/tracing), la fábrica
    de sesión de datos, y los shims deprecados.
    """
    allowed = _AMBIENT_MODULES | _DATA_ACCESS_FACTORIES
    violations: list[str] = []
    for layer in ("rag", "agents"):
        for path in _py_files(layer):
            if _is_shim(path):
                continue
            for mod in _imports_of(path):
                if (
                    mod.startswith("src.infrastructure")
                    and mod not in allowed
                ):
                    violations.append(f"{path.relative_to(ROOT)}: imports {mod}")
    assert not violations, "rag/agents importan adaptadores:\n" + "\n".join(violations)


def test_no_vertical_business_terms_in_generic_layers() -> None:
    """core/rag/agents/platform no contienen lógica de negocio vertical."""
    terms = ("farmacia", "zentfarmacia", "product_images", "order_status", "rag_farmacia")
    violations: list[str] = []
    for layer in ("core", "rag", "agents", "platform"):
        for path in _py_files(layer):
            content = path.read_text(encoding="utf-8").lower()
            for term in terms:
                if term in content:
                    violations.append(f"{path.relative_to(ROOT)}: contiene '{term}'")
    assert not violations, "Strings verticales en capas genéricas:\n" + "\n".join(violations)


def test_production_rejects_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RAG_ENVIRONMENT", "production")
    monkeypatch.setenv("RAG_CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv(
        "RAG_PORTAL_SESSION_KEY",
        "aa" * 32,
    )
    monkeypatch.setenv("RAG_POSTGRES_PASSWORD", "prod-pg-password-not-default")
    monkeypatch.setenv("RAG_LITELLM_API_KEY", "sk-prod-not-empty")
    monkeypatch.setenv("RAG_RAG_ADMIN_ENABLED", "false")
    monkeypatch.setenv("RAG_ADMIN_ENABLED", "false")
    monkeypatch.setenv("RAG_PORTAL_DEV_PASSWORD", "not-the-dev-default")
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings()
    get_settings.cache_clear()
