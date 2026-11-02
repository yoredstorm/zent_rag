# P19.1-03 — Revisión y hash verificable de bindings

- **Estado:** DONE para data_query y publicaciones nuevas; legacy sin hash
  permanece en modo explícito.
- **Riesgo cerrado:** G03 para ejecución con `binding_ref` + `binding_hash`.

## Hallazgo AS-IS

- `upsert_binding` hacía `ON CONFLICT DO UPDATE`: el mismo `capability_ref`
  apuntaba a otro plan sin cambiar la referencia lógica.
- El nodo comparaba `binding_ref` después de `execute_binding`; la consulta ya
  había ocurrido.
- No había versión/hash de plan persistido ni historial de revisiones.

## Contrato

Migración `179_binding_revisions`:

- `workflow_capability_bindings.plan_version`, `canonical_plan_hash`,
  `policy_version`, `superseded_at`.
- `workflow_capability_binding_revisions` con config/hash/versión/estado.

Ejecución:

1. El nodo lee `binding_ref` y `binding_hash` del config.
2. Preflight por ID, org, workspace y estado activo.
3. Compara `binding_plan_hash(binding)` contra el hash pineado.
4. `execute_binding(... binding_ref, expected_binding_hash)` vuelve a resolver
   una sola vez y compara antes de despachar.
5. Drift: `PLAN_STALE`; cero SQL.
6. Si la actualización ocurre después de resolver, se ejecuta el objeto ya
   resuelto, no una segunda lectura.

`binding_plan_hash` usa `binding_id + capability_ref + provider_kind +
sha256(config canónico)`. No incluye credenciales ni filas.

Publicación P19.1-01:

- Cada publicación genera `capability_ref` nuevo.
- Se archiva la revisión anterior y se inserta la nueva.
- Un plan publicado no se sobrescribe desde la API.

## Rutas

- `POST /workflows/{id}/run` → nodo `data_query`.
- `POST /data-query/preview` → valida `policy_hash` vigente.
- `POST /data-query/plans` → binding nuevo con revisión.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Cambiar tabla manteniendo ID | PASS: `PLAN_STALE`, 0 queries | `test_binding_drift_is_denied_before_any_query` |
| Revisión 1 y 2 archivadas | PASS | idem |
| Hash correcto ejecuta el mismo binding | PASS | `test_matching_pin_executes_the_same_binding` |
| Preview con policy hash viejo | PASS: `POLICY_STALE` | `test_preview_rejects_stale_policy_without_querying` |
| Publicaciones no se pisan | PASS | `test_publish_never_overwrites...` |

## Compatibilidad y rollback

- Aditiva. Workflows antiguos sin `binding_hash` siguen ejecutando por
  `binding_ref` si existe; si no existe, por `capability_ref` (legacy).
- UI/readiness deben mostrar “Consulta cambiada: revisar y republicar” cuando
  falte hash; todavía no se implementó el diff humano.
- Rollback 179 elimina columnas/tabla de revisiones. Los nodos con hash pineado
  fallarían `PLAN_STALE`; es el comportamiento seguro.

## Riesgos residuales

- El snapshot de release del workflow no congela explícitamente el hash; el
  nodo lo lee de `config`. Falta escribir el hash en la definición publicada.
- `upsert_binding` interno todavía puede actualizar bindings no publicados por
  la API; no se expone a HTTP.
- No hay diff visual de columnas/filtros ni métricas
  `binding_drift_denied/plan_stale/query_version`.
- No se probó concurrencia editor vs ejecución con dos transacciones reales.
