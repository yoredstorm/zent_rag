# P19.1-06 — Intención multivuelta, slots y recuperación durable

- **Estado:** PARTIAL. Contrato v2, rutas configurables, slots durables y gold
  set de 80 casos implementados; desambiguación de productos y UI conversacional
  completa pendientes.

## Hallazgo AS-IS

- El router v1 tenía rutas cerradas al pack demo y `confidence` heurística.
- `missing_slots` se calculaba, pero no se persistía un estado de conversación.
- Una segunda frase (“el de un kilo”) se clasificaba como `other`; no recuperaba
  el intent/slot anterior.
- No había límite de turnos ni idempotencia por `message_id`.

## Contrato

- `zent.workflow.intent.route/v2`:
  - `routes` con `id`, `keywords`, `examples`, `negative_examples`,
    `required_entities`, `priority`, `requires_identity_verification`;
  - ids de ruta propiedad del workflow (v2); v1 mantiene el pack cerrado por
    compatibilidad;
  - `other` obligatorio.
- `zent.workflow.intent.state/v1` persistido en
  `workflow_instances.state.conversation.<state_key>`:
  - `active_intent`, `slots`, `missing_slots`, `awaiting_slot`,
    `turn_index`, `last_message_id`, `expires_at`;
  - nunca guarda JWT ni identidad; el subject sigue viniendo del runtime.
- `merge_conversation_turn`:
  - si hay `awaiting_slot` y el mensaje no matchea una ruta, lo usa como valor
    del slot (sanitizado);
  - mismo `message_id` devuelve el mismo estado (`duplicate_message=true`);
  - límite de turnos (`TURN_LIMIT`).
- El nodo `intent_route` lee/escribe el state de la instancia durable; no crea
  memoria paralela.

## Rutas

- `POST /workflows/intent-route/test` (sin ejecutar rutas).
- Nodo `intent_route` dentro de workflows durables.
- `POST /workflows/instances/{id}/signal` reanuda el mismo proceso.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Ruta v2 custom por keywords | PASS | `test_v2_allows_workflow_owned_routes` |
| Inyección rechazada en v2 | PASS | `test_v2_route_ids_are_still_closed_by_config` |
| Slot durable “el de un kilo” | PASS | `test_conversation_slot_fill_is_durable_and_idempotent` |
| Mensaje duplicado idempotente | PASS | idem |
| Límite de turnos | PASS | `test_conversation_turn_limit_returns_other` |
| Gold set 80 casos: route accuracy / slot F1 | PASS 1.00 / 1.00; false authorizations 0 | `scripts/cert/evaluate_intent_goldset.py` |
| 4+ turnos con WAIT/RESUME real | NOT_RUN | falta E2E durable con DB real |
| Desambiguación de 2 productos | NOT_RUN | no implementada |

## Compatibilidad y rollback

- v1 sigue usando el pack demo; v2 permite rutas del workflow.
- El state se guarda en la instancia existente; no hay tabla nueva.
- Rollback: nodos v2 con rutas custom fallarían como “ruta no permitida” si se
  vuelve a v1. Migrar el workflow a v1 o mantener la rama.

## Riesgos residuales

- No hay clasificador LLM opcional ni calibración; `confidence` sigue siendo
  heurística y así se etiqueta.
- No hay desambiguación paginada de productos ni vínculo a un candidato del
  resultado anterior.
- No se implementó multi-intent secuencial con consentimiento.
- No se probó reboot del worker durante WAIT.
- Falta la UI de Test Studio para ver slots/estado de espera.
