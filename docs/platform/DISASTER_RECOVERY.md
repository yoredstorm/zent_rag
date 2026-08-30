# Disaster recovery — restore drill

No “hacer backups”: **restaurar**. Orden importa: Qdrant desfasado de PG produce retrieval incorrecto.

## Orden de restore

1. Poner la API en mantenimiento (Cloudflare / quitar backends).
2. Restaurar **Postgres** (`pg_restore` o PITR). Correr Alembic `upgrade head` si el dump es de un schema anterior.
3. Restaurar **Qdrant** del snapshot **más cercano y no posterior** al dump PG. Si Qdrant es más nuevo que PG, hay vectores huérfanos; si es más viejo, hay filas sin vectores (re-sync sources).
4. Vaciar Redis (o no restaurar).
5. Verificar bucket S3 (blobs referenciados por `kb_sources`).
6. Health: `GET /health`, login portal, una query RAG, un connector sync de prueba.
7. Quitar mantenimiento.

## Checklist del drill (cada trimestre)

- [ ] Restore PG en un instance aislado (no prod).
- [ ] Restore Qdrant snapshot en colección temporal.
- [ ] Una query conocida devuelve las mismas sources (o documentar drift).
- [ ] Tiempo real medido vs RTO de [BACKUPS.md](BACKUPS.md).
- [ ] Secretos de restore (keys de backup) rotados y fuera del repo.

## Failover

Una sola región / una VM: no hay multi-region en esta fase. DR = restore a una VM nueva + DNS Cloudflare.
