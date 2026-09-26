# Evidence-first gate — la evidencia deja de ser un string recortado

Documento de la corrección de la regresión «categoría 31 / byte 105»: el
retrieval encontraba el fragmento correcto y la respuesta terminaba en
«No hay evidencia suficiente en las fuentes consultadas…».

## 1. Causa raíz

La evidencia nunca fue un objeto de primera clase: era **texto dentro de
`history`**, recortado en cascada por posición.

```
search_knowledge   chunk recortado a 1200 chars (tabular 6000), output a 14000
AgentRuntime       observation = output[:3000]
                   └── el chunk relevante se perdía si estaba más allá del char 3000
AnswerGate         evidence = "\n".join(line[:1500] for line in observations[-8:])
                   └── segunda pérdida, sobre lo que ya venía recortado
build_jev_state    tope de sección 8000 + presupuesto global
Passage/evidence   preview de 240 chars por ítem para el evidence gate del RAG
```

Consecuencia: **JEV decidía si existía evidencia viendo una versión peor de la
evidencia que vio el generador**. Si el fragmento con «Fee Application (byte
105)» quedaba fuera de los cortes, el veredicto era «sin respaldo» y el runtime
reemplazaba toda la respuesta por `INSUFFICIENT_ANSWER`.

A esto se sumaban dos problemas de política:

- el score del gate mezclaba *grounding*, *completeness* y *presentación* en un
  único número: una respuesta respaldada pero mal presentada podía caer a
  `abstain`;
- no había verificación por claim: una afirmación sin respaldo anulaba la
  respuesta completa.

## 2. Tres distinciones que ahora son código

| Concepto | Qué es | Dónde vive |
|---|---|---|
| **SOURCE** | documento disponible (`Cat31_dapp_C.pdf`) | `sources` del flujo (`collect_sources`) |
| **EVIDENCE** | fragmento recuperado con `evidence_id` | `EvidenceRegistry` / `EvidenceItem` |
| **CLAIM** | afirmación respaldada por fragmentos | `ClaimJudgment` (`shared` + `rag/adaptive/claims.py`) |

Un `meta["evidence"]` sin `content` ya **no** se registra: eso es una fuente,
todavía no evidencia.

## 3. Una sola fuente lógica: `EvidenceRegistry`

`src/runtime/evidence.py` (sin duplicar modelos: reutiliza `EvidenceItem` de
`src/core/domain/adaptive.py`).

- Cada fragmento recuperado entra **completo** y recibe un `evidence_id` estable
  (`E1`, `E2`, …), deduplicado por `(document_id, chunk_id)`.
- Generador, JEV, citas y «Ver flujo» consumen **la misma selección**: los
  `evidence_id` son idénticos en los cuatro.
- El contenido completo vive en el run; el step persistido guarda sólo un
  excerpt (`_evidence_meta_for_flow`), así el flujo no crece con la KB.

```
search_knowledge ─┐
                  ├─► EvidencePacket[] ─► EvidenceRegistry ─► EvidenceSelector
retrieval motor ──┘                                          │
                                                             ├─ prompt del generador
                                                             ├─ estado de JEV
                                                             ├─ citas (evidence_id)
                                                             └─ «Ver flujo»
```

## 4. Selección por relevancia, no por posición

`select_evidence(items, question, budget_chars=…)` reparte
`RUNTIME_EVIDENCE_BUDGET_CHARS` (default 12 000) en este orden:

1. `exact_entity_match` — TODAS las entidades pedidas están en el fragmento
   (o en el nombre de su fuente: `Cat31_dapp_C.pdf` cubre «categoría 31»);
2. `source_name_match` — el nombre de la fuente coincide con lo que se nombró;
3. `entity_pin` — el fragmento vino del pin de entidades del retrieval;
4. `section_match` — la sección del chunk coincide con los números pedidos;
5. `lexical_match` — solapamiento léxico con la pregunta;
6. `semantic_match` — el resto, por score.

Dentro de cada nivel ordena por score. Cada fragmento entra hasta
`MAX_ITEM_CHARS`; si el presupuesto restante alcanza el mínimo
(`MIN_ITEM_CHARS`) entra recortado y **se marca `complete: false`**; si no,
se descarta y se registra en `dropped`. Nunca hay `texto[:N]` como criterio.

## 5. Evidence sufficiency (antes de generar)

`assess_sufficiency(items, question, retrieval_rounds_left)` devuelve señales
**medidas**, no cuotas:

```
has_evidence, supporting_chunks, entity_coverage, entities_asked,
entities_covered, missing_entities, exact_entity_match, top_score,
recommended_action (generate | retrieve_more | answer_with_limits | abstain),
reason
```

`UNKNOWN != ZERO`: si la pregunta no nombra entidades, `entity_coverage` y
`exact_entity_match` **no se publican** (`None`), no se rellenan con 0.

La regla determinística fuerte (`entity_match`) gana sobre el juicio de JEV: si
la pregunta nombra «categoría 31 byte 105» y ambos aparecen en la evidencia, JEV
puede pedir lo que falte de *otras* entidades, pero no puede declarar que no hay
evidencia.

## 6. Política del answer gate (contenido ≠ presentación)

`src/runtime/answer_gate.py` separa dos preguntas y compone la acción en código:

```
CONTENT/GROUNDING:  ¿está respaldada por las fuentes?
PRESENTATION:       ¿está bien explicada?

sin evidencia usable           ─► retrieve_more   (si queda presupuesto)
                                  └► abstain      (agotado)
evidencia irrelevante          ─► retrieve_more   | abstain
evidencia relevante y borrador
sin respaldo                   ─► retrieve_more   | revise
respaldo ok y falta
completitud o forma            ─► revise          (nunca abstain)
claims sin respaldo            ─► revise          (se quitan; no se anula todo)
respaldo parcial               ─► answer_with_limits
todo ok                        ─► approve
```

Una respuesta imperfecta se revisa; una respuesta sin evidencia se abstiene.
Los motivos de presentación (`poor_structure`, `too_short`, `missing_example`,
`unclear`, …) **no** pueden producir abstención.

Verificación por claim: los extremos los decide el código (overlap fuerte o
ausencia de evidencia) y los claims de la banda incierta se preguntan a JEV en
la **misma llamada** del gate (`claim_N_supported` / `claim_N_contradicted`),
que es el vocabulario del `POST_GENERATION` del RAG. El runtime declara lo que
no se pudo respaldar en vez de borrarlo en silencio.

## 7. Citas ancladas a `evidence_id`

`Citation.evidence_id` + `citations_payload(selection, cited_ids=…)`: la marca
`[Doc N]` del texto apunta a una evidencia concreta, así que renumerar o
reordenar el contexto no rompe la procedencia. `doc_index` en el flujo es el
número que el generador realmente vio; un fragmento que no entró al contexto se
publica como `RETRIEVED` sin índice, nunca con un índice inventado.

## 8. Observabilidad («Ver flujo»)

- `steps.evidence_sufficiency`: acción recomendada, motivo, entidades
  cubiertas/faltantes, `exact_entity_match`, chars de evidencia.
- `steps.answer_gate`: `grounding_verdict`, `presentation_verdict`,
  `evidence_ids`, `evidence_chars`, `missing_entities`, resumen de claims.
- `flow.evidence`: fragmentos con `evidence_id`, título, sección, página, score,
  método de recuperación, `entity_pin`, `doc_index`, `status`
  (`USED`/`RETRIEVED`) y `cited`.
- `flow.evidence_sufficiency` y `flow.citations`.

Métricas: `zent_evidence_sufficiency_total{action,reason}`,
`zent_evidence_selection_total`, `zent_evidence_selected_chars`, más las ya
existentes del loop (`zent_agent_jev_action_total`,
`zent_agent_jev_retrieval_total`, `zent_adaptive_claim_verdict_total`).

## 9. Configuración

| Variable | Default | Qué hace |
|---|---|---|
| `RAG_RUNTIME_EVIDENCE_BUDGET_CHARS` | `12000` | Presupuesto de evidencia del run (generador y JEV ven el mismo texto) |
| `RAG_RUNTIME_ANSWER_GATE` | `off` (forzado `on` en agentes de conocimiento con el loop JEV activo) | Verificación del borrador: off/shadow/on |
| `RAG_RUNTIME_AGENT_JEV_LOOP` | `on` | Juicio por paso; el veredicto manda |
| `RAG_RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS` | `2` | Rondas de búsqueda dirigida por JEV |
| `RAG_RAG_RESPONSE_PRESENTATION_GATE` | `true` | Suma las preguntas de presentación al gate |

El nombre real de cada variable es `RAG_` + el nombre exacto del campo de
`Settings` (`env_prefix="RAG_"`). Un nombre sin el prefijo se ignora **en
silencio**: `tests/test_config_env_contract.py` compara `.env.example`,
`docker-compose.yml`, `docker-compose.prod.yml` y `deploy/k8s/configmap.yaml`
contra `Settings.model_fields` y falla si alguna variable no mapea.

## 10. Rollback

- `RAG_RUNTIME_ANSWER_GATE=off` devuelve el gate al comportamiento previo.
- `RAG_RUNTIME_AGENT_JEV_LOOP=off` apaga el juicio por paso.
- El registry y la selección son internos: sin gate activo, el generador usa la
  misma evidencia seleccionada (mejor contexto, mismo contrato de salida).

Ningún flag nuevo cambia el comportamiento por defecto de otros caminos: el
camino legacy sigue disponible cuando no hay evidencia estructurada
(tools que sólo devuelven texto).

## 11. Tests

`tests/test_evidence_first_gate.py`:

- **regresión byte 105**: retrieval → registry → selección → generador → JEV →
  respuesta final (no `INSUFFICIENT_ANSWER`), con la evidencia observable;
- **truncamiento**: el texto crudo cortado a 3000/1500 pierde el fragmento
  relevante y la selección lo conserva (escenario L);
- **suficiencia**: exact match de entidades, entidad ausente, cobertura parcial,
  `UNKNOWN != ZERO`;
- **gate**: presentación mediocre → revise (nunca abstain), evidencia relevante
  con borrador flojo → revise, sin evidencia → retrieve_more → abstain,
  evidencia irrelevante, `answer_with_limits`, claims;
- **end-to-end A–L**: match exacto, entidad explícita, JEV pide otra búsqueda,
  evidencia insuficiente, claim sin respaldo, presentación pobre después de un
  cierre por termination, varias fuentes, evidencia tras mucho texto irrelevante.

`tests/test_config_env_contract.py`: contrato de nombres de variables.

## 12. Expansión de sección y ventana por relevancia (segunda vuelta)

La regresión volvió a aparecer con otra forma: el retrieval sí traía el título
correcto, pero en **piezas de tabla de 100-600 chars partidas por el parser**
(«4 6 2 Fee Application (byte 105) Validating Carrier»), y el padre de sección
que las contiene —9.378 chars con los valores 1-5, la definición de fare
component/pricing unit cambiada, la jerarquía `3, 2, 5, 4, 1` y los ejemplos—
nunca entraba. El generador veía ~1.260 chars de fragmentos y rellenaba de
memoria.

Cuatro cambios, todos deterministas:

- **Chunker** (`src/knowledge/structure/chunker.py`): las piezas diminutas de
  tabla se fusionan (o se descartan si son sólo encabezado, el padre conserva el
  texto) y el overlap de `_split_text` ya no arranca a mitad de palabra.
- **Expansión de sección** (`HybridRetriever._expand_pinned_parents`): un
  fragmento pineado se cambia por su padre de sección cuando el store lo tiene.
  El lookup es por `metadata.chunk_id` (`get_documents_by_chunk_ids`), no por id
  de punto: el `parent_id` del hijo es el `chunk_id` lógico del padre. El
  `StructuredRetriever` usa el mismo lookup.
- **Ventana por relevancia** (`src/runtime/evidence.py::relevance_window`): un
  fragmento más grande que el presupuesto entra como encabezado + tramos
  alrededor de lo que la pregunta nombra, no como `texto[:N]` (el overview de
  157 KB dejaba «Table 988» —offset 5.470— y «Record 2» —offset 6.896— afuera
  del corte de 4.000). Una sección expandida entra completa si cabe.
- **Filtro por categoría nombrada** (`search_knowledge`): si la pregunta dice
  «categoría 31», los chunks de fuentes cuyo nombre declara otra categoría
  (`Rec2_Cat10_dapp_C.pdf`) no ocupan el top; el filtro nunca deja la búsqueda
  vacía.

