# P18.5-04 — Revocaciones y RBAC vigentes durante WAIT/RESUME

## Identidad

- Commit: `732e25e`
- Baseline: `e6c42c2579df0e997ef2a0a0d0916f05dc735bef`

## Hallazgo reproducido

`resolve_effective_policy` devolvía el `instance_policy` congelado sin consultar
`workflow_policy_revocations`. Una capability revocada mientras la instancia
estaba en `WAITING` seguía autorizada al reanudar. Además `_revocations` capturaba
toda excepción y devolvía `set()`: una caída de PostgreSQL se interpretaba como
“sin revocaciones”.

## Contrato

```
política congelada (snapshot inmutable)
        ∩ RBAC vigente del caller (solo reduce)
        ∪ revocaciones vigentes (solo reduce)
        → EffectiveExecutionPolicy.with_hash()
```

- `overlay_restrictive_policy` nunca reconstruye desde el workflow/agente vivo.
- Error leyendo revocaciones → `policy_store_error=True`, `revoked_capabilities={"*"}`.
- `authorize_node` bloquea escrituras si `policy_store_error`; las lecturas
  pueden continuar bajo el comportamiento documentado.
- `*` revoca escrituras, no bloquea nodos de lectura/LLM.
- El hash de la política cambia al aplicarse una revocación; el run registra
  `effective_scope_hash`.
- Un `instance_policy` corrupto produce una política deny-all, no una
  reconstrucción desde la fila viva.

## TOCTOU

La revalidación ocurre en `resolve_effective_policy`, antes de `execute_graph`, y
el PEP vuelve a evaluar `revoked_capabilities` inmediatamente antes del nodo. La
ventana residual entre la lectura del overlay y el efecto externo es de
milisegundos y no es transaccional para proveedores HTTP; se documenta como
riesgo residual P2. Una revocación creada después de esa ventana puede no
detener una llamada ya iniciada, pero no autoriza nuevas llamadas.

## Pruebas

```text
uv run pytest tests/test_p18_5_revocation_resume.py -q
3 passed
```

- Revocación creada después del snapshot → aparece en el overlay y el PEP
  devuelve `policy.revoked`.
- Outage de Postgres simulado → `policy_store_error`, `*`, escritura denegada
  con `policy.revocation_unavailable`/`policy.revoked`.
- `instance_policy` corrupto → deny-all, no ampliación.

La suite de durables incluye señales concurrentes y doble señal:

```text
tests/test_workflow_durable_instances.py::test_duplicate_signal_does_not_run_twice
tests/test_workflow_durable_instances.py::test_concurrent_signals_exactly_one_winner
(incluida en 150 passed, 1 skipped)
```

## Compatibilidad

- Sin migración nueva en esta fase.
- Instancias existentes conservan su snapshot; solo se les agrega el deny-overlay.
- Si la tabla de revocaciones no existe (instalación vieja), se considera vacía;
  una caída real no se confunde con tabla ausente (`SQLSTATE 42P01`).

## Riesgos residuales

- P2: ventana TOCTOU para efectos HTTP no transaccionales.
- P2: el RBAC del actor no se recalcula en señales de sistema (el actor es
  `system`); sí se intersecta cuando el caller pasa permisos explícitos.
- P2: `revocation_epoch` es informativo, no un reloj distribuido.

## Decisión

**PASS** para P18.5-04. P0 de revocación durante espera cerrado.

## Próxima fase autorizada

P18.5-05.
