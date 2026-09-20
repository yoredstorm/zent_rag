/**
 * Aplicabilidad de tools según las fuentes del agente.
 *
 * Espejo de `_filter_tools_by_sources` del backend: la UI deshabilita y el
 * runtime omite, para que el LLM no pierda pasos eligiendo una herramienta
 * que no puede funcionar (por ejemplo SQL con fuentes solo PDF).
 */

const DB_SOURCE_TYPES = new Set(["sql", "postgres", "mysql", "mssql", "oracle", "snowflake"]);
const TABULAR_SOURCE_TYPES = new Set(["csv", "excel"]);

/** `null` = no se pudo determinar (no se restringe). */
export function hasDbSources(sourceTypes: string[] | null | undefined): boolean {
  if (sourceTypes == null) return true;
  return sourceTypes.some((type) => DB_SOURCE_TYPES.has(type));
}

/** `null` = no se pudo determinar (no se restringe). */
export function hasTabularSources(sourceTypes: string[] | null | undefined): boolean {
  if (sourceTypes == null) return true;
  return sourceTypes.some(
    (type) => TABULAR_SOURCE_TYPES.has(type) || DB_SOURCE_TYPES.has(type),
  );
}

/**
 * Tipos de fuente relevantes para el agente: las seleccionadas; si no hay
 * ninguna seleccionada, todas las de la organización (igual que el backend).
 * Con `loading` devuelve `null` para no deshabilitar controles en falso.
 */
export function sourceTypesForSelection(
  sources: { id: string; type: string }[],
  selectedIds: string[] | null | undefined,
  loading = false,
): string[] | null {
  if (loading) return null;
  const selected = new Set(selectedIds || []);
  const relevant = selected.size > 0 ? sources.filter((source) => selected.has(source.id)) : sources;
  return relevant.map((source) => source.type);
}
