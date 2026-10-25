# Evidencia — API keys de desarrollo

| Comando | Resultado |
|---|---|
| `pytest tests/test_sandbox_api_keys.py -q` | **3 passed** |
| `ruff check` archivos afectados | OK |
| Portal `npm run typecheck` | OK |

Cubre:
- prefijo `zent_sk_test_`;
- expiración de 1 día;
- listado con `expires_at`;
- rechazo 401 de una clave vencida;
- bloqueo determinista de key test contra deployment production.

Sin migración. Las claves live siguen sin expiración automática.
