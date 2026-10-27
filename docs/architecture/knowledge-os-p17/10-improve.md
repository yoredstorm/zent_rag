# P17-05 — Mejorar

## Bandeja única

`/knowledge/improve` abre en la pestaña `Bandeja`. La bandeja compone, sin
crear tabla nueva:

- problemas de calidad (`/knowledge/quality`);
- conflictos (`/knowledge/conflicts`);
- vacíos (`/knowledge/gaps`);
- preguntas/aprobaciones (`/knowledge/learning/questions`);
- cola de revisión (`/catalog/suggestions`);
- mejoras (`/learning/improvements`).

Cada fila muestra el conteo y abre la cola existente. No se movieron ledgers ni
se duplicaron registros.

## Estados

- Si no hay pendientes y salud tiene dimensiones medidas: **No hay problemas
  conocidos**.
- Si no hay pendientes pero no hay medición: **Calidad aún no evaluada**.
- No se usa `0` como sustituto de una calidad no medida.

## Permisos

- Abrir una cola es lectura.
- Resolver conflicto exige `knowledge:admin`.
- Resolver gap exige `knowledge:write`.
- Aprobar/rechazar sugerencias exige `catalog:write`.
- Si falta permiso, la UI lo dice y no muestra la acción; el backend sigue
  siendo la autoridad final.
- No se agregaron endpoints de resolución ni aprobaciones nuevas.

## Límites

- La bandeja hace varias lecturas independientes; si una cola falla, las demás
  siguen visibles.
- La composición es una vista de lectura; no hay ordenación semántica avanzada
  ni deduplicación entre tipos distintos.
- No se implementó SOÑAR, reflexión periódica, promoción automática ni
  autoaprendizaje nuevo.

## Pruebas

- `Quality.test.tsx`: `/knowledge/improve` abre Bandeja y distingue no evaluado.
- Tests existentes de Quality/conflictos/gaps/learning siguen aplicando.

## Rollback

Revertir la pestaña Bandeja y la gate de acciones. Sin migración.
