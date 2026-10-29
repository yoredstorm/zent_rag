# P18.3-05 — Shadow reprocess reversible

Estado: **NOT_RUN**. Razón: no hay copia autorizada del tenant histórico y la
regla del programa prohíbe `--purge` sobre producción como estrategia de
evaluación.

## Diseño congelado

1. Inventario por fuente: original y hash, parser, documentos/bloques,
   evidencia, objetos canónicos, edges, modelo de embedding, puntos Qdrant,
   agentes/workflows referenciadores.
2. Copia cifrada o export controlado en staging, aislada de índices productivos,
   con ID-mapping y provenance.
3. Parser + perfil + compilador actuales sobre la copia. Las propuestas
   `heuristic-passage-v1` quedan fuera del almacén verificado.
4. Comparación antes/después: documentos, bloques, candidatos, falsos
   conceptos, reglas, afirmaciones, relaciones, evidencia, documentos sin
   pasaje, retrieval y gold set.
5. Referencias persistentes: preservar IDs idénticos o publicar mapas de
   correspondencia; no dejar referencias colgantes.
6. Revisión humana de diferencias de clasificación y objetos de alto riesgo.
7. Promoción solo con aprobación, flag por tenant/corpus, release versionada,
   replay y rollback.
8. Fallo a mitad de reproceso: la versión aprobada anterior sigue consultable.

## Salvaguardas existentes

`src/scripts/knowledge_reprocess.py` mantiene `--dry-run`; no se ejecutó
`--purge`. Los artefactos P18.2 (`before`, `after`, `narrative-quality-after`)
se conservan como evidencia histórica, no como certificado de comprensión.

## Por qué no se simula como PASS

Sin copia autorizada no se puede demostrar que el original no se modifica ni
que los IDs referenciados por workflows siguen válidos. Un reproceso local
sobre otra base no es equivalente a la fuente productiva.
