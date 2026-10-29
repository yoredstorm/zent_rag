# P18.3-09 — Snapshot inmutable del agente en workflows

Estado: **corregido y probado**.

## Invariante

Si un workflow V1 se publicó con el agente A, editar Agent Studio a B no puede
cambiar silenciosamente la ejecución V1. La ejecución usa A o falla cerrado.
Una configuración nueva requiere certificar y publicar una revisión.

## Cambios

1. `snapshot_from_fields`, `snapshot_fingerprint` y `execution_fingerprints`
   son la definición única de la configuración ejecutable del agente.
2. La certificación de workflow guarda:
   - `agent_id`, `revision_id`, `version`, `status`, rol;
   - `config_fingerprint`;
   - `model_fingerprint`, `tools_fingerprint`,
     `source_scope_fingerprint`, `purpose_fingerprint`.
3. `definition._certificate_row` ahora lee `agent_versions`; antes el
   certificado se descargaba sin ellos y la comparación era imposible.
4. `load_published_definition` rechaza con `agents_stale` si el agente cambió
   después de certificar.
5. Al iniciar una instancia se guarda `config_snapshot` completo en
   `policy_snapshot.agents[]`.
6. `_exec_llm` materializa el agente desde el snapshot pinneado. Si la fila
   viva cambió, usa A y registra la deriva; si el agente no existe o está
   inactivo, falla cerrado. Las instancias legacy sin snapshot usan la fila viva
   y se marcan como no certificables.

## Pruebas

`tests/test_p18_3_agent_pinning.py`: 4 passed.

- snapshot congelado con huellas;
- edición A→B después de iniciar: el nodo ejecuta A;
- workflow publicado con certificado A: editar B produce `agents_stale`;
- certificados legacy no se sobredeclaran protegidos.

Regresión de workflows: 59 passed
(`test_workflow_published_snapshot`, `publication_gate`, `durable_instances`,
`agent_context`, pinning).

## Límite legacy

Las instancias durables iniciadas antes de este cambio no tienen el snapshot
completo. No se reescribe su historial ni se declara que quedaron
automáticamente certificadas. El runbook es re-certificar y migrar nuevas
instancias; las antiguas deben tratarse como legacy.
