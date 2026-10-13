# Slice log — fase de convergencia de autoridad

Registro por slice: qué cambió, qué autoridad se movió, qué evidencia lo
protege y qué deuda queda. Cada slice cierra con la suite enfocada verde.

---

## S0 — Harness de ratchets (commit `55dfcdb`)

- `tests/test_authority_ownership.py`: familias `phase_writes`, `result_totals`,
  `answer_writes`, `decision_writes`, `authority_flag_writes`,
  `terminal_mapper` con allowlist por archivo/cantidad y justificación.
- Frontera de confianza por AST: `ToolContext` solo en 2 sitios declarados y
  `tenant_id` debe venir de un atributo confiable.
- Registro de autoridad por estado crítico (14 símbolos verificados).
- CI: el ratchet corre en `Architecture invariants (fast, required)`.
- Sin cambios de comportamiento.

## S1 — Mapa BEFORE + duplicaciones + ADRs (commit `0faaf77`)

- `docs/architecture/ownership/00-baseline.md`: `BASELINE_SHA`
  `5cd3dec1812955c28dd6ce338f56322022a2079c`, CI 10/10 verde.
- `01-ownership-map-before.md`: matriz de 28 componentes.
- `02-duplicated-authorities.md`: P0-1..P0-5, P1-1..P1-7, P2-1..P2-6 con
  evidencia `file:line`.
- `03-adr-decisions.md`: ADR-001..006.
- Ratchet: el mapa no puede perder estados críticos del registro.

## S2 — Autoridad del cierre (este slice)

### Cambios de autoridad

| Antes | Después |
|---|---|
| `finish()` derivaba la fase del texto y del dict `answer_state` | `finalize_state` resuelve con `resolve_closure_phase` y aplica `phase_override`; el texto no decide |
| La política de cierre solo observaba divergencias | La resolución es la autoridad; la divergencia contra el oráculo es invariante crítico |
| `RUNTIME_RUN_STATE_STRICT` documentado pero inexistente (el `getattr` caía al default) | Campo real en `Settings` (default `off`), respetado, documentado en `.env.example` |
| Fallo operativo con evidencia "completa" podía terminar FINALIZED | Familia `OPERATIONAL_FAILURE_STATES` bloquea por construcción |
| Conflicto declarado (`CONFLICTING_EVIDENCE`/`CONFLICTING_RULE`) no vetaba la respuesta | La familia veta y el conflicto queda registrado como mismatch crítico |

### Reducer del cierre (`finalization_policy.resolve_closure_phase`)

| Entrada | Fase aplicada | Kind |
|---|---|---|
| status `error`/`failed` | FAILED | `operational` |
| status `limit_reached` | LIMIT_REACHED | `operational` |
| status `awaiting_approval`/`blocked` | BLOCKED | `operational` |
| familia = fallo operativo | BLOCKED | `operational_failure` (mismatch si la política quería finalizar) |
| familia = conflicto (fuentes o reglas) | ABSTAINED / UNDETERMINED | `conflict` (mismatch si la política quería finalizar) |
| política FINALIZE/ABSTAIN/BLOCK/UNDETERMINED | esa fase | `agreed` o `closure_authority_mismatch` |
| política CONTINUE/RETRIEVE_MORE/USE_TOOL | BLOCKED si el oráculo decía FINALIZED; si no, la del oráculo | `closure_not_authorized` / `continue` |
| oráculo y política no concluyentes distintos | la de la política | `classification_refined` (sin violación) |

Invariante de construcción: `phase == FINALIZED` exige
`decision.action == FINALIZE`. Verificado en la matriz completa (≥700
combinaciones) y en 100 iteraciones de estabilidad.

### Efectos medidos sobre los invariantes previos

Dos invariantes quedaron **inalcanzables en caminos productivos** (que es el
objetivo) y siguen vigentes como defensa en profundidad:

| Invariante | Estado | Evidencia |
|---|---|---|
| `deterministic_finalized_without_envelope` | inalcanzable: sin envelope la fase es UNDETERMINED y se registra `closure_authority_mismatch` | `tests/test_run_state.py::TestInvariants::test_determinista_sin_envelope_no_finaliza` + test de defensa forzando la fase |
| `incomplete_analysis_finalized` | inalcanzable: la política resuelve CONTINUE y el cierre pasa a BLOCKED con `closure_not_authorized` | `tests/test_run_state.py::TestInvariants::test_analisis_incompleto_no_autoriza_cierre` + test de defensa |

### Desviación documentada del plan original (ADR-004)

El plan inicial proponía agregar `closure` a `ENFORCE_STAGES`. **Se descarta**:
el hold de `enforcement.should_hold_trigger` solo aplica a `RETRIEVE_MORE`
antes del cierre; un hold en el cierre no tiene semántica. El fail-closed del
cierre es el modo estricto (`RUNTIME_RUN_STATE_STRICT`, ADR-002), que ahora es
un campo real. Se evita inventar una etapa sin comportamiento.

### Ratchets

- `closure_writes`: escritor único del campo `DecisionState.closure`.
- `terminal_mapper`: 2 sitios declarados (oráculo en el reducer + respaldo de
  `finish()` para llamadas directas).
- `phase_writes` sigue en 10 hits / 4 archivos: el reducer **no** agrega un
  writer de fase; `finish()` sigue siendo el único aplicador.

### Tests nuevos

`tests/test_closure_authority.py` (24 casos): status operativos, cierre
autorizado, fallos operativos, vetos por conflicto, oráculo legacy, propiedades
de la matriz completa, estabilidad ×100, integración con `finalize_state`,
modo estricto global y canary por org, y contrato del campo en `Settings`.

### Deuda que queda

- P0-3 (10 deciders de answerability): S4/S8.
- P0-4 (sufficiency duplicada): S4. La política todavía es ciega a
  contradicciones de excerpt (la familia de conflicto las cubre a nivel estado).
- P0-5 (tres writers de costo): S5.
- P1-3/P1-4/P1-5: S6/S7/S9.
