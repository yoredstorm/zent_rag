# P18.3-04 — Fuentes históricas sin corpus

Estado: **herramienta lista; aplicación real: BLOCKED_AUTHORIZATION**.

## Causa del 404

`_sources_for_corpus` exige `corpus_id = :cid`. Una fuente histórica con
`kb_sources.corpus_id IS NULL` no pertenece a ningún corpus consultable, aunque
tenga workspace y documentos. El endpoint responde 404 sin revelar la fuente.

## Inventario local

| Clase | Fuentes |
|---|---:|
| `corpus_id IS NULL` | 282 |
| Sin workspace | 83 |
| Con workspace y corpora candidatos | 199 |
| Vínculo explícito único | 0 |

No se asignó ninguna automáticamente. El caso real de un tenant no tiene
autorización registrada: se usa una copia sintética para las pruebas.

## Herramienta

`src/scripts/legacy_source_corpus_backfill.py`:

```text
plan     dry-run, plan JSONL + SHA-256, sin escribir kb_sources
apply    --plan-file --plan-id --plan-sha256 --approve
rollback --plan-id --approve
```

- `determinate`: solo con vínculo explícito (`knowledge_base.corpus_id` o
  `source.config_json.corpus_id`) dentro de la misma organización y workspace.
- `ambiguous`: más de un candidato explícito; no elige.
- `needs_resolution`: workspace con corpus pero sin vínculo; el operador debe
  usar `--resolve source_id=corpus_id`.
- `orphan`: sin workspace o sin corpus.
- `cross_scope_conflict`: corpus de otra organización/workspace o inexistente.

Apply usa `UPDATE ... WHERE corpus_id IS NULL AND organization_id=... AND
workspace_id IS NOT DISTINCT FROM ... AND knowledge_base_id IS NOT DISTINCT
FROM ... RETURNING updated_at`, journal antes/después y `ON CONFLICT` para
idempotencia. Rollback solo revierte si `corpus_id` y `updated_at` siguen
siendo los del apply; si no, marca `conflict`.

## Evidencia ejecutada

```text
plan org 02e24672... -> 2 orphan, 0 apply
plan org 0186014c... -> 1 needs_resolution, 0 apply
```

Pruebas `tests/test_p18_3_legacy_backfill.py`: 7 passed.

- determinante aplica, repite sin duplicar y revierte;
- un único corpus del workspace **no** se asigna solo;
- selección humana resuelve un ambiguo;
- huérfano y cross-scope quedan bloqueados;
- CAS rechaza un cambio posterior al plan;
- rollback no pisa un cambio concurrente;
- checksum cambia con la decisión.

## Migración

`176_legacy_source_corpus_journal.py` crea
`legacy_source_corpus_journal` y su índice. Es aditiva y reversible.

## Desbloqueo

Autorización del titular del tenant para el caso real o una copia fidedigna
autorizada. Hasta entonces, no se declara PASS de legado.
