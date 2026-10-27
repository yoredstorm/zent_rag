# P17-06 — Contexto y vocabulario

## Cambios

- `Sources used` → `Fuentes citadas` en el workspace.
- Errores del chat dejan de exponer flags internos (`RAG_KNOWLEDGE_V2_*`) y
  ofrecen una acción: reintentar o revisar el estado de las fuentes.
- En el flujo principal se habla de `procesamiento`, `disponible` y
  `fuentes citadas`, no de chunks, embeddings, recall, nutrition score ni
  assertions.
- La cola de subida dice `En cola de procesamiento`.
- Los términos técnicos siguen disponibles en las vistas avanzadas
  (`Documents`, `Jobs`, `Understanding`, `Evaluation`, `Catalog`).

## Principios

- Una acción explica qué hace, cuándo usarla y qué no modifica.
- Un error no muestra un identificador técnico como única salida.
- Un estado no se comunica solo por color.
- Los IDs, hashes y trazas no aparecen en la respuesta conversacional.

## Límites

- No se agregó un drawer técnico nuevo en esta fase; las vistas técnicas
  existentes siguen siendo el lugar autorizado para ese detalle.
- La revisión con 5 usuarios y la auditoría axe de todas las vistas quedan en
  P17-08 (`NOT_STARTED`/`NOT_MEASURED`).
- No se cambió ningún endpoint ni contrato de retrieval.

## Pruebas

- `Sources.test.tsx` y `wizardSteps.test.tsx` actualizados al nuevo copy.
- `Ask.test.tsx` y `Quality.test.tsx` cubren el flujo de Preguntar/Mejorar.
- `npm run typecheck` y ESLint pasan en los archivos tocados.
