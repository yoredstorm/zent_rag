# P19.1-02 — Identidad verificada, ownership y límites por registro

- **Estado:** DONE en ruta HTTP/workflow y preview; PARTIAL en reanudación
  durable desde hooks sin request.
- **Riesgo cerrado:** G02 para las rutas instrumentadas; no certifica canales
  externos ni RLS de proveedor.

## Hallazgo AS-IS

- `ExecutionContext` solo tenía org/workspace/actor; no distinguía actor de
  titular.
- `execute_binding` no recibía principal ni permisos efectivos.
- `_execute_connected_select` llamaba `_execute_data_query_plan` sin
  `principal`; un plan con `ownership.required` fallaba cerrado, pero un plan
  sin ownership podía leer filas amplias.
- `preview_data_query` se ejecutaba con autoridad administrativa y solo exigía
  `workflows:read`.
- No había revalidación de identidad en WAIT/RESUME más allá del run.

## Contrato

`src/platform/workflows/principal.py`:

```json
{
  "schema": "zent.workflow.principal/v1",
  "organization_id": "...",
  "workspace_id": "...",
  "actor_id": "...",
  "subject_id": "CUST-A",
  "authn_method": "portal_session",
  "assurance_level": "high",
  "verified_at": "...",
  "expires_at": "...",
  "claims": {"customer_ref": "CUST-A"},
  "provenance": {"customer_ref": "trusted_channel"}
}
```

- `subject_id`/`claims` no se leen de `trigger.message`, del LLM ni del body.
- El principal se construye desde `TenantContext`/canal autenticado.
- Se valida org/workspace y vigencia antes de ejecutar.
- `principal_hash` se registra para auditoría; no se guardan JWT ni secretos.
- `execute_binding` y `_dispatch_binding` propagan el principal.
- `_execute_data_query_plan` añade `owner_field = verified_claim` antes del SQL;
  sin claim: `PERMISSION_DENIED`/`IDENTITY_REQUIRED`, nunca “consultar y
  filtrar después”.
- Preview y run usan la misma política de ownership.

## Rutas

- `POST /workflows/{id}/run` y dry-run construyen principal desde la sesión.
- `POST /workflows/instances/{id}/signal` propaga el principal actual al
  reanudar.
- `POST /data-query/preview` propaga principal y exige `data_queries:preview`.
- `_workflow_handler` de decisión construye principal de API con assurance
  media.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Principal válido/expirado | PASS | `test_workflow_data_p19_principal.py` |
| Scope org/workspace distinto | PASS | idem |
| Claims con token/password | PASS | idem |
| `public_ref` sin PII | PASS | idem |
| A lee su saldo, B el suyo | PASS | `test_verified_principal_enforces_ownership_for_a_not_b` |
| Sin principal en plan ownership | PASS (falla cerrado) | idem |
| Principal de otra org | PASS (denegado) | idem |
| Preview con ownership | PASS (misma política) | `test_workflow_data_p19_catalog.py` |

## Compatibilidad y rollback

- Sin migración para el modelo: el principal viaja en memoria/argumentos.
- Planes legacy sin `ownership` mantienen lectura, pero quedan marcados en
  preview como legacy.
- Rollback de código elimina la propagación; los planes con ownership vuelven
  a fallar cerrado. No hay pérdida de datos.

## Riesgos residuales

- No existe todavía autenticación de cliente final (DNI/OTP) en el repo; el
  claim `customer_ref` debe venir de un canal confiable fuera de este cambio.
- Reanudación desde scheduler/hook sin request no tiene principal: falla
  cerrado. Falta persistir una referencia de identidad y revalidarla contra el
  proveedor de auth.
- No se implementó RLS en PostgreSQL externo; la defensa es de aplicación.
- Falta prueba de revocación de token durante WAIT con proveedor real.
- `support`/`supervisor` con propósito auditado no está modelado aún.
