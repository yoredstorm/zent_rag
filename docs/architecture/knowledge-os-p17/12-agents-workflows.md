# P17-07 — Agentes y workflows

## Acción contextual

En la ficha de una fuente aparece `Usar en un agente` solo si el usuario tiene
`agents:write` (o no hay lista de permisos, comportamiento legacy). Abre un
agente nuevo con `?source_id=...`; no crea ni publica nada.

`useAgentStudio` lee ese parámetro en un agente **nuevo**, espera a que la
fuente exista en `/sources`, la agrega a `config.source_ids` y activa
`search_knowledge`. Si la fuente no está permitida, no aparece en la lista y no
se agrega. Un agente existente ignora el parámetro y conserva su configuración.

## Estado de las fuentes en Agent Studio

`AgentKnowledgeSection` muestra:

- “Este agente podrá consultar estas fuentes respetando sus permisos.”
- Estado real por fuente: Listo para consultar, Procesando, Recibida, Necesita
  atención o No medido (mismo adaptador de P17-02).

No se otorga visibilidad ni permiso adicional. La lista de fuentes sigue siendo
la que devuelve `/api/v1/sources` para el tenant/workspace.

## Workflows

`WorkflowContextPanel` ya expone el scope `knowledge.rag` y las contribuciones
de conocimiento por nodo. No se modificó el contrato de workflows ni se agregó
un binding nuevo. Añadir conocimiento no publica ni promueve un workflow.

## Invariantes

- No se tocan agentes promovidos, versiones publicadas ni instancias activas.
- No se agregan APIs nuevas de binding.
- `source_ids` y `knowledge_scope` son las únicas autoridades reutilizadas.
- Una relación del grafo no es permiso de lectura.
- Knowledge OS no ejecuta APIs, SQL de escritura, pagos ni correo.

## Pruebas

- `AgentStudio.test.tsx`: agente nuevo con `?source_id=s1`, fuente
  preseleccionada, estado Procesando, aviso de permisos. `51 passed` junto con
  `SourceDetail.test.tsx`.
- `SourceDetail.test.tsx`: link `Usar en un agente` con el ID correcto.
- `WorkflowContextPanel.test.tsx` existente: scope de conocimiento visible.
- E2E completo fuente→agente→tenant B: `NOT_VERIFIED`; requiere un agente real
  publicado y un segundo tenant en Playwright.
