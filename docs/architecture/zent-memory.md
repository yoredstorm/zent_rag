# ADR: Zent Memory Architecture

Estado: **fundación observable**. No hay auto-optimización de producción.

Depende de [judgment-fabric.md](judgment-fabric.md), el Evidence/Claim Ledger
(`src/core/domain/evidence.py`) y el Decision Learning de sólo lectura
(`src/decision/learning.py`). No reemplaza `src/learning` (gaps, improvements,
replay): esa cola sigue siendo humana. Esta fase agrega la memoria que el
Learning Engine consumirá después.

## Decisión

Zent distingue cuatro memorias. La conversación no es la memoria: produce
eventos.

```
Conversation / Run
        ↓
Memory Events          (ledger append-only)
        ↓
Memory Store           (MemoryRecord, tenant-scoped)
        ↓
Memory Recall          (pocas, ACTIVE, del mismo organization_id)
        ↓
Judgment Fabric        (JEV juzga; no escribe memoria ni políticas)
```

| Tipo | Alcance | Hecho |
| --- | --- | --- |
| Conversation | Una conversación o su run | Entidad, tema, restricción, parámetro |
| Knowledge | Evidencia | Apunta a Claim Ledger o Evidence Ledger. Un texto del LLM no es un hecho |
| Operational | Cómo resolver un tipo de problema | Firma de patrón, no el prompt |
| Learning | Meta sobre el sistema | Por ejemplo reintento tras `sql.schema_mismatch` |

`ACTIVE` significa: patrón validado y autorizado para que el runtime lo
**considere**. No autoriza cambiar prompts, thresholds, modelos, chunking,
retrieval policies, agentes, workflows ni configuración de tenant.

## Madurez

`MemoryMaturityPolicy` es el único lugar con umbrales
(`support_count`, confianza, contradicción, stale).

```
OBSERVED → REINFORCED → PATTERN → VALIDATED → ACTIVE
```

Excepciones: `CONTRADICTED`, `STALE`, `REJECTED`, `EXPIRED`, `SUPERSEDED`.

Una conversación no llega a `ACTIVE`. `VALIDATED` exige experimento, golden
set, evidencia estadística o aprobación admin. Knowledge exige un `ref_id` de
claim o evidence ledger; en Postgres el checker confirma que esa fila existe
en el mismo `organization_id`.

## Firma

Determinística, por dimensiones: intent family, source type, retrieval
modality, tool family, failure category. Un prompt largo cae en
`unclassified`. Sin embeddings.

`visibility` admite `tenant` y reserva `product`. Esta fase sólo escribe
`tenant`. Recall filtra `organization_id` y `visibility = tenant`. No hay
aprendizaje cruzado entre tenants.

## Judgment Fabric

`OrchestratorDecisionHook` llama `recall_for_decision` antes de
`DecisionEngine.decide`. El estado que ve JEV lleva
`known_operational_patterns` (id, pattern_key, success_rate, support_count,
confidence). Después se appende `memory.used`. El trace guarda `memory_ids`.
JEV no importa el servicio de escritura.

## Qué no persiste

Chain-of-thought, secretos, credenciales, documentos completos. El ledger
guarda decisión, señales, confianza, memoria usada, resultado de política y
outcome.

## Fuera de alcance

Mutación autónoma de producción. Promoción automática de prompts, modelos,
chunking o políticas. Patrones globales de producto.

El ciclo posterior vive en [self-improving-rag.md](self-improving-rag.md):
observa, formula hipótesis, experimenta en seco y recomienda. `ACTIVE` sigue
siendo una señal. La promoción la hace un admin.
