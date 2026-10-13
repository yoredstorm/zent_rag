# =============================================================================
# Contrato OpenAPI: una sola registración por router.
#
# Regresión: 10 routers estaban incluidos dos veces en el mismo app (mismos
# paths registrados de nuevo), lo que producía 143 warnings de FastAPI
# "Duplicate Operation ID" y un esquema con operaciones pisadas.
# =============================================================================
from __future__ import annotations

import warnings


def test_openapi_sin_operation_ids_duplicados() -> None:
    from src.api.main import app

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema = app.openapi()

    duplicados = [
        str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)
    ]
    assert duplicados == [], f"operation ids duplicados: {duplicados[:3]}"

    ids: list[str] = []
    for _path, methods in schema.get("paths", {}).items():
        for _method, operation in methods.items():
            if isinstance(operation, dict) and operation.get("operationId"):
                ids.append(operation["operationId"])
    assert len(ids) == len(set(ids)), "operation ids repetidos en el esquema"
