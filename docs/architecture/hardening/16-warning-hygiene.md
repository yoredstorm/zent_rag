# Warning hygiene — clasificación y ratchet

Estado: implementado. Los warnings de la suite se clasifican en tres grupos; el
grupo aceptado está acotado y documentado acá.

## 1. Bug / riesgo (corregidos)

| Warning | Causa raíz | Fix |
|---|---|---|
| `SAWarning: non-checked-in connection` | Sesiones reutilizadas después del cierre o sin cierre (`run_anomaly_checks`, `_classify_source_ids`, `_check_promotion_gate`, `evals.trigger_run`) | try/finally de dueño único + NullPool en development |
| `Event loop is closed` / pool cerrando desde otro loop | Engine recreado por loop disponiendo conexiones del loop viejo | Recreación sin dispose cross-loop + teardown de sesión que posee el engine |
| `Duplicate Operation ID` (143) | 10 routers registrados dos veces en el mismo app | Registración única + `test_openapi_contract.py` |
| `DeprecationWarning: deprecated` en cada request | Acceso al campo deprecado `RAGQueryRequest.role` | Lectura vía dump (mismo comportamiento) |

## 2. Deprecation real (corregidos)

| Warning | Fix |
|---|---|
| `Call to deprecated setex` (redis) | `set(key, value, ex=ttl)` + filtro `error` (ratchet: si vuelve, falla) |
| `asyncio_default_fixture_loop_scope is unset` | Declarado explícito en `pyproject.toml` |

## 3. Ruido de entorno de test (aceptado, acotado)

| Warning | Por qué es aceptable | Alcance |
|---|---|---|
| `Api key is used with an insecure connection` (qdrant) | Qdrant local/CI corre HTTP sin TLS con api key de desarrollo por diseño; producción usa TLS y no dispara el aviso | `filterwarnings` por mensaje exacto en `pyproject.toml` |
| `SECURITY: POSTGRES_PASSWORD/PORTAL_SESSION_KEY default` (Settings) | Es una guía para developers. En CI ya no aparece (password de CI propio, session key explícita). En local queda visible a propósito; no se filtra para no ocultar una config insegura | Sin filtro |

## 4. Ratchet

- `setex`: filtro `error` en `pyproject.toml`.
- OpenAPI: `tests/test_openapi_contract.py` (en los invariantes requeridos).
- Lifecycle async: `tests/test_db_lifecycle.py` (en los invariantes requeridos).
- Contabilidad: `tests/test_run_accounting_rag.py` (guard anti doble billing y
  `unknown != 0`) en los invariantes requeridos.
