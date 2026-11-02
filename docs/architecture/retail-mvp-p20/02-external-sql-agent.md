# P20-02 — Agente conversacional sobre la BD externa

- **Estado:** DONE para consulta NL→SQL sobre una fuente externa declarada.
  No es el agente vendedor completo (P20-05..12 siguen pendientes).
- **Base:** `620d241` + este corte.
- **Fuente de prueba:** `ERP externo P19`, tipo `sql`, `source_mode=schema_only`,
  `connector_id=f5b941b7-74dc-4e42-80e3-a539820deae1`.

## Qué se implementó

1. `PostgresSqlExpert.execute_external()` resuelve el conector externo por
   `connector_id`, valida org/workspace, descubre el esquema real con
   `PostgresPlugin.deep_discover()` y reutiliza el generador/validador SQL
   existente. No usa la Managed DB ni el esquema interno de ZENT.
2. `_run_query()` y `_explain_validate()` usan la sesión externa validada
   (`_query_session_override`) y **fallan cerrado** con
   `DATABASE_NOT_CONFIGURED` si no hay una BD autorizada. Se eliminó el
   fallback silencioso a `get_readonly_session()` (BD interna de ZENT).
3. `QueryDatabaseTool` detecta la fuente DB declarada por el agente
   (`source_ids` efectivos → `kb_sources.config_json.connector_id`), valida
   workspace y enruta a `execute_external()`. El resultado incluye
   `source_id`, `connector_id` y `source_mode` en `ToolResult.meta`.
4. Un agente conectado solo a una BD ya no recibe `search_knowledge`: el
   runtime filtra esa tool (`no_knowledge_sources`). Si el agente tiene
   fuentes documentales además de la BD, conserva ambas.
5. Las preguntas de estructura (`¿Qué tablas tienes?`) se responden con el
   discovery real, sin LLM: schema, tabla, tipo y filas aproximadas.
6. Para preguntas de catálogo/precio/stock se prioriza la vista comercial
   `bodega.product_catalog_v` cuando existe; así el LLM no elige una tabla de
   precios paralela o histórica.

## Evidencia ejecutada (local, datos sintéticos)

| Caso | Entrada | Resultado |
|---|---|---|
| Precio real | `¿Cuánto cuesta el arroz?` | `BD-ARROZ-01 = 4.80 PEN`, `BD-ARROZ-05 = 22.50 PEN` desde `bodega.product_catalog_v` |
| Estructura | `¿Qué tablas tienes?` | 10 objetos: `bodega`, `catalog`, `loyalty`, `sales`; incluye la vista `product_catalog_v` |
| Stock | `¿Cuánto stock hay de arroz de 1 kg?` | `BD-ARROZ-01 available = 53` |
| Contexto multi-turno | `¿Cuánto cuesta el arroz?` → `¿Y el de 5 kg?` | resuelve `BD-ARROZ-05 = 22.50 PEN`, 62 disponibles, sin reiniciar la conversación |
| Ruta interna | agente DB sin Managed DB | `DATABASE_NOT_CONFIGURED`; no abre `rag_platform` |
| Tool del agente | runtime HTTP/portal | `query_database` con observación real; sin timeout de 30 s |

La prueba HTTP se ejecutó contra el runtime real con sesión de portal y la
fuente externa; el resultado del tool se usó para componer la respuesta. No se
declara PASS de flujo de venta ni de pagos: esos gates pertenecen a P20-09..12.

## Contrato de seguridad de este corte

- La fuente se resuelve por `connector_id`, nunca por nombre.
- Sin `source_ids` explícitos no se elige una BD externa por conveniencia.
- Más de un conector distinto → `MULTIPLE_DATABASE_SOURCES`, sin adivinar.
- Workspace distinto → `PERMISSION_DENIED`.
- Conector inactivo/credencial ausente → `SOURCE_UNAVAILABLE` /
  `NEEDS_CREDENTIALS`.
- El SQL sigue pasando por AST, allowlist de tablas, blocklist de
  columnas, EXPLAIN y límite de filas.
- El LLM no recibe DSN, password ni SQL de administración.

## Límites explícitos (NO implementado todavía)

- Grants por agente/capability (P20-04): hoy el vínculo es `source_ids` del
  agente + RBAC del caller; falta la matriz capability/resource/row policy.
- Tools comerciales tipadas (`find_products`, `get_price_and_stock`, carrito,
  quote, pedidos) de P20-05. Hoy `query_database` responde preguntas de solo
  lectura; no crea órdenes ni cobra.
- Carrito, checkout simulado, reservas y postventa con identidad (P20-10..12).
- El agente demo se reparó a mano (`tools=[search_knowledge, query_database]`,
  `runtime.tool_routing=false`). P20-06 debe crear ese estado desde la UI, no
  por SQL manual.
- Cálculos derivados en la respuesta (p. ej. precio por kilo) son aritmética
  sobre datos reales, pero P20-07 debe restringir su presentación.

## Pruebas

```powershell
uv run --frozen --no-sync pytest tests/test_p20_external_sql_query.py -q
uv run --frozen --no-sync pytest tests/test_p20_sql_source_integrity.py -q
uv run --frozen --no-sync ruff check src/agents/tools/sql_expert_postgres.py `
  src/agents/tools/tools_builtin.py src/agents/runtime/agent_runtime.py
```

Resultado de este corte: 7 tests P20 nuevos PASS; pruebas SQL Expert
existentes (`test_sql_expert`, `test_sql_security`, `test_intelligence_pipeline`,
`test_organization_filter_injection`) 79 PASS.
