# Tests rojos P13

P00-P03 quedaron verdes y sus pruebas viven como suites permanentes:

- Publicación inmutable: `tests/test_workflow_published_snapshot.py`.
- Identidad de eventos/inbox/outbox: `tests/test_workflow_event_identity.py`.
- Policy efectiva y aislamiento: `tests/test_workflow_effective_policy.py`.
- Migraciones: `tests/test_workflow_p13_migrations.py` (pendiente de ejecución
  en CI con PostgreSQL limpio).

No quedan archivos `xfail` P13. Una nueva brecha debe añadirse aquí con
`pytest.mark.xfail(strict=True)`, reproducirse con `--runxfail`, y retirarse al
corregirse.
