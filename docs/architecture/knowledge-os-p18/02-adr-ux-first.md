# ADR P18 — UX first, motor canónico intacto

- **Estado:** aceptado.
- **Contexto:** la experiencia Knowledge Alive debía simplificarse sin crear un
  segundo motor de ingesta, retrieval o aprendizaje.

## Decisión

1. La UI consume Sources, Knowledge Sessions, evidence/claim ledger, Qdrant,
   PostgreSQL, corpus y permisos existentes.
2. El wizard es una capa de presentación y estado de navegación; no es una
   fuente de verdad.
3. Se permiten cambios aditivos de contrato para corregir alcance y verdad:
   `corpus_id` en fuentes/carga, `sources_ready`, `ready_sources` y
   `citation_evidence_ids`.
4. No se crean tablas nuevas, motores de ingesta, canales SSE alternativos ni
   procesos de autoaprendizaje.
5. No se modifica un agente o workflow publicado por navegar o mirar una
   fuente. La vinculación exige una acción explícita en Agent Studio.
6. El flag `RAG_KNOWLEDGE_SIMPLE_UX_ENABLED` queda como rollback visual. Su
   default es `true`; `false` recupera la navegación anterior.

## Consecuencias

- Las fuentes históricas sin corpus requieren asignación explícita; no hay
  backfill silencioso.
- Los porcentajes de progreso solo existen si el backend mide el denominador.
- La prueba de cinco usuarios y el canary por tenant siguen siendo gates de
  release, no afirmaciones de este ADR.
