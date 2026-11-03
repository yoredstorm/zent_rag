# Onboarding vivo — diagnóstico y corrección del 17% atascado

- **Caso:** `ppimentel@omnio.pe`, fuente `Bodega pepito` (`zent_external_mvp`).
- **Síntoma:** wizard en `Analizar`, 17%, `QUEUED`, más de 10 minutos sin feedback.
- **Estado final:** sesión `REVIEW_REQUIRED`, job `completed`, 100%.

## Causa raíz

El job de discovery murió 3 veces con:

```text
ConnectorError: Blocked private network IP: 192.168.65.254
(add host to connector config ssrf_allowlist to allow)
```

`host.docker.internal` resuelve a la red privada de Docker. El test de conexión
no aplicaba el guard SSRF, así que el wizard decía «Conexión verificada»; el
discovery sí lo aplicaba y fallaba. El frontend además hacía un poll acotado de
40 intentos (~48 s), por lo que se quedó mostrando el último 17% aunque el job
ya estaba `dead`.

## Correcciones

### Backend

- `connect_database` valida el host con `plugin.validate()` antes de
  `test_connection`. Un host privado sin allowlist ahora falla en la conexión,
  no después.
- `analyze` es idempotente: si ya hay un job activo para la sesión, no crea
  otro.
- `progress` expone:
  - `job_status`, `job_error`, `job_attempts`;
  - `job_updated_at`, `last_update_seconds_ago`, `stalled`;
  - `error_code` y `error_hint` accionables.
- Si el job está `dead`/`failed`, la sesión pasa a `FAILED` y el wizard recibe
  el error real.
- `SSRF_BLOCKED` se traduce a un hint: agregar el host a «Hosts permitidos».

### Frontend

- Poll continuo mientras el estado sea `DISCOVERING`/`ANALYZING`, con backoff
  hasta 5 s. Ya no se detiene a los 48 s.
- El paso Analizar muestra error real, hint y botón **Reintentar análisis**.
- Si el job lleva más de 120 s sin avance, muestra «sin avance» y permite
  reintentar.
- El formulario de conexión detecta hosts privados (`localhost`, `127.x`,
  `10.x`, `192.168.x`, `172.16-31.x`, `.internal`) y ofrece **Permitir host**.
- Sin autorización explícita, el formulario bloquea el envío con un mensaje
  claro. No hay allowlist implícita.
- Frases de espera específicas para base de datos, no «Leyendo el archivo».

## Evidencia

- `GET /api/v1/data-onboarding/sessions/49b90740.../progress`:
  `status=REVIEW_REQUIRED`, `percent=100`, `job_status=completed`.
- `ingestion_jobs.aa5fd1fe...`: `completed`, `progress=100`, `attempts=1`.
- `tests/test_data_onboarding.py`: 29 passed.
- Vitest onboarding: 24 passed.
- Nuevo test de conexión SSRF: `test_database_connection_reports_ssrf_block_before_discovery`.

## Nota operativa

El conector existente se corrigió localmente agregando:

```json
{
  "ssrf_allowlist": ["host.docker.internal", "192.168.65.254"],
  "allowed_schemas": ["bodega", "public"]
}
```

Para una instalación nueva, el wizard lo pide explícitamente. No se habilita
ninguna red privada por defecto.

## Segundo hallazgo: catálogo invisible por workspace

Al preguntar `cuéntame qué productos vendes`, el agente respondía con el error
`Zent necesita saber qué campo es el precio`. El catálogo tenía `UnitPrice`
mapeado, así que el problema no era el modelo semántico.

Causa: `start_discovery_scan` creaba `catalog_sources` sin `workspace_id`.
`list_fields_all` filtra por workspace cuando el resolver recibe uno:

```sql
JOIN catalog_sources s ON t.source_id = s.id
WHERE s.workspace_id = :wid
```

Con `workspace_id` nulo, el resolver veía cero campos y devolvía
`CONTEXT_MISSING`.

Correcciones:

- `start_discovery_scan` acepta y propaga `workspace_id`.
- `_analyze_database` pasa el workspace de la sesión de onboarding.
- El registro existente se reparó con
  `UPDATE catalog_sources SET workspace_id = ...`.
- El resolver ya devuelve `bodega.product_catalog_v.price` para preguntas de
  precio y el error deja de aparecer.

Las preguntas de stock siguen usando las tools tipadas
(`get_price_and_stock`), que leen `available`/`on_hand` directamente.

## Tercer hallazgo: base de datos tratada como documento sin indexar

El Agent Studio mostraba:

```text
Espera a que termine el indexado; ahora mismo no hay nada que buscar.
```

aunque la fuente `Bodega pepito` estaba `ready` y el agente respondía por API.

Causa: la UI decidía «indexado» con `document_count > 0`. Una base de datos no
genera documentos, así que `document_count` siempre es 0. Eso marcaba la fuente
como pendiente en tres lugares:

- el aviso del chat de prueba;
- el contador «1 fuente conectada · 1 en proceso»;
- el poll de 3 s que nunca terminaba;
- la etiqueta «Procesando» para `status=ready`.

Corrección:

- `isDatabaseSource` distingue `sql`, `postgres`, `mysql`, `mssql`, `oracle`,
  `snowflake` y `db2`.
- El aviso de indexado y el contador ignoran fuentes de base de datos.
- `sourceReadiness("ready", "sql")` muestra «Base de datos conectada».
- El poll de fuentes solo espera documentos reales.

El 70% del encabezado es otra cosa: readiness de publicación
(modelo, prompt, knowledge, datasource y tools). Los 3 puntos restantes son
evaluación, versión y deployment; no bloquean el chat.


