# =============================================================================
# Data Onboarding — constantes de sesión (lenguaje interno)
# =============================================================================
from __future__ import annotations

KINDS = frozenset(
    {"database", "documents", "spreadsheets", "drive", "website", "api"}
)

STATUSES = frozenset(
    {
        "NOT_STARTED",
        "CONNECTING",
        "CONNECTED",
        "DISCOVERING",
        "ANALYZING",
        "REVIEW_REQUIRED",
        "TESTING",
        "READY",
        "NEEDS_ATTENTION",
        "FAILED",
    }
)

STEPS = frozenset(
    {"choose", "connect", "analyze", "review", "confirm", "test", "ready"}
)

SQL_ENGINES = {
    "postgres": 5432,
    "mysql": 3306,
    "mssql": 1433,
    "oracle": 1521,
    "db2": 50000,
}

WRITE_PERMS = ("sources:write", "connectors:write")
READ_PERMS = ("sources:read", "connectors:read", "catalog:read")
