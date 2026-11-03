# P18.5-01 — Snapshots inmutables y pinning ejecutable de agentes

## Identidad

- Rama: `fix/p18-5-security-execution-live-studio`
- Commits: `3b859f9` (baseline), `e23b2ed` (implementación)
- Baseline: `e6c42c2579df0e997ef2a0a0d0916f05dc735bef`

## Matriz antes / después

| Aspecto | Antes | Después |
|---|---|---|
| `resolve_agent` | `snapshot.get("tools") or agent.tools` | Presencia de clave; `tools=[]` devuelve `[]` |
| `system_prompt=""` | Hereda prompt vivo | Devuelve `""` |
| Snapshot incompleto | Completa desde agente vivo | `strict=True` falla con `AgentSnapshotError` |
| Hash del snapshot de instancia | Solo warning | Comparación obligatoria; mismatch bloquea el nodo |
| Instancia sin `config_snapshot` | Usa agente vivo | Bloquea con `agent_snapshot_missing` (`UNCERTIFIED_LEGACY`) |
| Acción irreversible en definición publicada/instancia sin snapshot | Podía ejecutarse | Bloqueada por `policy.agent_snapshot_unverified` |
| Ejecución publicada | Lee agente vivo en runtime | Snapshot capturado en la misma lectura que verifica el certificado |
| Auditoría | Sin huella por nodo | `agent_snapshot_status`, `agent_config_fingerprint`, `agent_version_id` en la salida del nodo |

## Contrato de snapshot

- `schema_version` sigue en `2` para no invalidar certificados existentes.
- Semántica explícita: `[]`, `""`, `null` y clave ausente son distintos.
- Un snapshot certificado debe declarar `system_prompt`, `model` y `tools`.
  Si falta una clave, la ejecución de instancia/publicada falla cerrado.
- El modo legacy de `resolve_agent(strict=False)` solo existe para llamadores
  históricos (p. ej. `public_query`); no autoriza acciones irreversibles.
- `snapshot_from_fields` sigue haciendo deep copy JSON; no comparte listas/dicts.

## Archivos y contratos

- `src/platform/deployments/versions.py`: `snapshot_issues`, `validate_agent_snapshot`, `resolve_agent(strict=...)`.
- `src/platform/workflows/nodes.py::_exec_llm`: resolución estricta, hash, provenance y bloqueo.
- `src/platform/workflows/instances.py::_build_policy_snapshot`: `agent_version_id`, `agent_version_number`, `snapshot_schema_version`.
- `src/platform/workflows/release_policy.py::_agent_fingerprint(include_snapshots=True)`.
- `src/platform/workflows/definition.py`: snapshots certificados devueltos con la definición publicada.
- `src/platform/workflows/runtime.py::ExecutionContext`: `agent_snapshots`, `graph_hash`, `workflow_version`, `definition_source`.
- Compatibilidad: campos JSON aditivos; no cambia el contrato público de runs.

## Pruebas ejecutadas

```text
uv run pytest tests/test_p18_5_agent_snapshot_security.py -q
6 passed
```

Cubre: presencia vs truthiness, snapshot incompleto, deep copy, instancia con
tools vacías + edición viva, instancia sin snapshot. También se ejecutó:

```text
uv run pytest tests/test_p18_3_agent_pinning.py tests/test_agent_versions.py -q
(parte de 43 passed)
```

## Multi-tenant / workspace

La consulta de agente sigue acotada por `organization_id`. El snapshot se
vincula a la instancia congelada; no se acepta `agent_id` de otro tenant. El
workspace efectivo viaja en la política y se valida en el PEP.

## Compatibilidad y migración

- Sin migración de base de datos.
- Snapshots `schema_version=2` existentes con las tres claves siguen siendo
  válidos. Snapshots incompletos se bloquean en ejecución real (decisión
  fail-closed documentada).
- Rollback: revertir `e23b2ed` restaura el comportamiento anterior; las
  instancias ya creadas conservan su JSON y no requieren backfill.

## Riesgos residuales

- P1: snapshots legacy incompletos quedan bloqueados hasta re-certificación; no
  se reescriben instancias activas automáticamente.
- P2: `execution_fingerprints` mantiene el algoritmo anterior para no invalidar
  certificados; la igualdad de hash no debe usarse como prueba de presencia.

## Decisión

**PASS** para P18.5-01. P0 de expansión de tools/prompt cerrado con prueba de
regresión adversarial.

## Próxima fase autorizada

P18.5-02.
