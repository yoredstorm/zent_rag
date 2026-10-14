# Batería de seguridad y adversarial (Parte G)

Evidencia: `artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/battery/security.json`
(+ `security.md`, `junit-security.xml`, `pytest-security.log`).

| Dato | Valor |
|---|---|
| SHA | `edeeb61` (sobre `17acf3d`) |
| Fecha | 2026-10-14 |
| Entorno | local, DB scratch `rag_cert_battery` (paridad CI), Redis/Qdrant reales, providers reales |
| Comando | `python -m src.scripts.certification_battery --suite security` |
| Resultado | **22/22 escenarios PASS · 350 tests · 0 fail · 0 error · 0 skip** |
| Duración | 1250,7 s (~21 min) |

El modelo **nunca es autoridad de seguridad**: cada escenario se verifica en el
boundary de código/política/runtime (no en el texto que devuelve el LLM).

## 1. Mapa escenario → test

| # | Escenario | Estado | Tests |
|---|---|---|---|
| G01 | prompt injection del usuario | PASS | 3 |
| G02 | prompt injection en documento recuperado | PASS | 2 |
| G03 | prompt injection en tool observation | PASS | 2 |
| G04 | fake system instruction en knowledge | PASS | 4 |
| G05 | cross-tenant retrieval | PASS | 13 |
| G06 | cross-tenant cache key | PASS | 3 |
| G07 | model-proposed `organization_id` | PASS | 11 |
| G08 | model-proposed `user_id` | PASS | 1 |
| G09 | tool no autorizada | PASS | 4 |
| G10 | SQL no autorizado | PASS | 3 |
| G11 | SQL mutación con read-only | PASS | 22 |
| G12 | SSRF a endpoints internos | PASS | 10 |
| G13 | redirect-based SSRF | PASS | 3 |
| G14 | exfiltración de credenciales/headers | PASS | 18 |
| G15 | path traversal en connectors/files | PASS | 2 |
| G16 | payload sobredimensionado | PASS | 1 |
| G17 | tool argument smuggling | PASS | 5 |
| G18 | metadata OpenAPI maliciosa | PASS | 2 |
| G19 | knowledge_scope escape | PASS | 46 |
| G20 | conversation isolation | PASS | 11 |
| G21 | RBAC downgrade | PASS | 9 |
| G22 | workflow privilege escalation | PASS | 30 |

Los nodeids exactos por escenario están en `security.json` (campo `tests` de cada
escenario). G01–G07 y G09–G22 ya existían en la suite; esta fase **agregó** los
escenarios que la matriz de hardening había dejado sin test (G08, G13, G14, G15,
G17, G18) más la salida de tool malformada (chaos F13).

## 2. Hallazgos y fixes (reproducidos antes de corregir)

### H1 — SSRF por redirect en conectores de knowledge (P1, cerrado)

- **Reproducción**: `WebSourceConnector`/`ApiSourceConnector` usaban
  `follow_redirects=True` y no validaban el host contra la política SSRF. Una
  URL pública podía redirigir (302) a `169.254.169.254` o `localhost` y ZENT
  hacía el fetch interno server-side.
- **Fix**: `src/knowledge/connectors/http.py` — `assert_public_url` (allowlist
  por conector vía `ssrf_allowlist`) y `request_with_safe_redirects` (follow
  manual acotado a 5 saltos con revalidación por hop). Los clientes pasan a
  `follow_redirects=False`.
- **Regresión**: `tests/test_certification_security.py::TestKnowledgeSourceSSRF`
  (5 hosts internos, redirect a 169.254/localhost, loop acotado, allowlist).

### H2 — `bool` aceptado como `integer`/`number` (P1, cerrado)

- **Reproducción**: `validate_arguments` usaba `isinstance(value, expected)` y
  en Python `bool` es subclase de `int`: `{"limit": true}` pasaba la validación
  de un argumento entero.
- **Fix**: `src/agents/tools/guards.py` rechaza booleanos salvo que el tipo
  declarado sea `boolean`.
- **Regresión**: `tests/test_certification_security.py::TestToolArgumentSmuggling`.

### Hallazgos sin cambio de código (verificados como mitigación estructural)

- `CallApiTool` no acepta `headers` en su schema y descarta argumentos extra
  (no hay canal para exfiltrar credenciales por argumentos del modelo).
- El importer de OpenAPI trunca metadata hostil (≤300/400 chars) y esa metadata
  entra al prompt como DATO con encabezado `TOOL_OBSERVATION: untrusted…`.
- `resolve_path`/`store_upload` ya bloqueaban traversal; faltaba el test.
- El dispatch de workflows es fail-closed: sin permisos explícitos no se
  ejecuta nada y los callers de sistema deben declararlo.

## 3. Lo que esta batería NO cubre (declarado)

- SSRF en `gdrive` (host fijo del proveedor; P3-3).
- E2E HTTP completo de escalación de privilegios en workflows (la cobertura es
  de contrato: permisos, fail-closed, inventario de callers).
- Pen-test externo / fuzzing de parsers (fuera del alcance de esta fase).
