# P18.3-06 — Paginación determinista de evidencia

Estado: **corregido y probado**.

## Defecto reproducido

Orden observable:

```sql
strength DESC NULLS LAST, created_at DESC, id ASC
```

Predicado anterior:

```sql
(COALESCE(strength, 0), created_at, id) < (:c_strength, :c_created, :c_id)
```

Con tres filas de igual `strength` y `created_at`, la primera página devolvía el
ID menor y la segunda quedaba vacía. Los NULL también se comparaban como 0,
aunque el orden los manda al final.

## Corrección

- `src/knowledge/evidence_paging.py`:
  - cursor tipado `EvidenceCursor(strength, created_at, evidence_id)`;
  - codec versionado `v1` en base64 URL-safe;
  - predicado explícito que respeta `strength DESC`, `created_at DESC` e
    `id ASC`, incluido el grupo NULL;
  - `fetch_evidence_page()` lee `limit + 1`, devuelve `total`, `returned`,
    `next_cursor`, `has_more` y `read_scope`.
- `source_insight` usa el helper y expone `pagination.evidence.next_cursor` y
  `read_scope`.
- Nuevo endpoint aditivo:
  `GET /api/v1/knowledge/workspaces/{corpus_id}/sources/{source_id}/evidence`.
- Migración `175_evidence_ledger_paging.py` agrega el índice
  `(organization_id, source_id, strength DESC NULLS LAST, created_at DESC, id ASC)`.

## Pruebas

`tests/test_p18_3_evidence_paging.py`: 8 passed.

- 3 filas empatadas, página de 1, sin duplicados ni omisiones;
- NULL al final, recorrido completo;
- 1.001 y 10.001 filas, páginas de 1.000;
- aislamiento entre tenants con el mismo `source_id` lógico;
- borrado entre páginas documentado como drift de snapshot;
- cursor inválido rechazado;
- empates con distinta fortaleza.

`tests/test_p18_3_evidence_api.py`: 1 passed. Recorre el endpoint real con
`limit=1`, valida `read_scope`, cursor inválido 400 y corpus ajeno 404.

## Semántica bajo concurrencia

No se abre una transacción larga. El cursor garantiza una visita por fila para
las filas que permanecen; si una fila se inserta o borra entre páginas, el
`total` puede cambiar y `read_scope.snapshot_consistency=false` lo declara. Para
una foto consistente se debe usar una transacción de lectura o un export, no
bloquear el producto.
