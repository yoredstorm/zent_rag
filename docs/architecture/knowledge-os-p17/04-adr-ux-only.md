# ADR — P17: simplificación UX sin cambiar el Knowledge OS

- **Estado:** aceptado para P17.
- **Fecha:** 2026-10-26.
- **Contexto:** la superficie actual tiene cinco pilares y duplicaciones de
  Preguntar/Fuentes/Resumen/Explorar. La arquitectura canónica ya existe y tiene
  contratos de sources, ingesta, retrieval, evidencia, calidad y workspaces.

## Decisión

1. La nueva navegación es una capa de presentación: Resumen, Fuentes, Preguntar
   y Mejorar, con Avanzado por disclosure.
2. No se crean tablas, índices, motores ni registros paralelos.
3. Los agregados de UI se calculan en el cliente desde endpoints existentes.
4. Solo se agrega un endpoint de lectura si una cita no puede resolverse con el
   contrato actual (`evidence_id` → documento/página/fragmento).
5. Las rutas actuales se conservan con redirects que preservan params.
6. El cambio se controla con `knowledge_simple_ux`, apagado por defecto.
7. Las acciones de escritura conservan sus permisos y endpoints. Ocultar una
   acción no autoriza ni desautoriza nada por sí mismo.

## Consecuencias

- El pipeline, retrieval, ACL, agentes y workflows no se tocan.
- El rollback es apagar el flag; las rutas legacy siguen.
- Hay deuda de consolidación de componentes que se resuelve por fases, no con
  un único PR gigante.
- La UI debe tolerar que un endpoint auxiliar falle sin romper la tarea
  principal.

## Rechazado

- Nuevo motor de conocimiento o segundo portal.
- Migrar datos para "simplificar" nombres.
- Unificar ledgers de calidad en una tabla nueva.
- Cambiar retrieval o agentes desde Knowledge OS.
- Activación automática de flags experimentales.
- SOÑAR, self-learning nuevo o promoción autónoma de conocimiento.
