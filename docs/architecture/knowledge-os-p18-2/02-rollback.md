# P18.2 — Rollback operativo

## Código

- Release anterior estable: `8a2d7c46907d51faf18a21e0de86c9b6ba411ae9`.
- Revertir la rama o desplegar ese SHA. El read model es stateless; no hay
  migración de conocimiento ni de documentos.
- Commits de la rama:
  - `fbd0a39` baseline documental
  - `2a35333` modos del Explorador
  - `7585b97` sello durable e idempotencia
  - `61897da` read model paginado
  - `0e6afeb` género técnico/narrativo
  - `51ed42d` propuestas por pasajes
  - `022c96f` grafo trazable
  - `577a6af` clasificación histórica
  - `19aa5eb` UX y métrica honesta
  - certificación: commit posterior con este documento

## Base de datos

La única migración es aditiva:

```powershell
alembic downgrade 173
```

Elimina `knowledge_learning_session_sources.idempotency_key` y su índice
único. No borra fuentes, jobs, sesiones ni objetos canónicos. Las claves de
idempotencia se pierden; los reintentos posteriores vuelven al comportamiento
anterior.

## Revisión histórica

Si se ejecutó el dry-run/hide de `explorer-cleanup`:

```http
POST /api/v1/knowledge/maintenance/explorer-cleanup
{
  "dry_run": false,
  "action": "restore"
}
```

Restaura únicamente claves de presentación `explorer_*`. No toca evidencia,
IDs, documentos ni agentes. En este entorno **no se aplicó** ningún hide de
P18.2.

## Datos no modificados

- PDF/CSV/Excel originales.
- `structured_documents` y `structured_blocks`.
- `evidence_ledger`.
- Objetos canónicos y sus IDs.
- Agentes, workflows, policies, ACL, facturación.

## Verificación post-rollback

1. `GET /api/v1/knowledge/objects` sigue devolviendo los mismos objetos.
2. El Explorador vuelve a la vista anterior.
3. Las sesiones existentes siguen consultables.
4. No aparecen fuentes duplicadas ni jobs nuevos por el rollback.
