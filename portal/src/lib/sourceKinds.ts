// =============================================================================
// Tipos de fuente que no se indexan como documentos.
// =============================================================================
// Una base de datos no genera `document_count`; su disponibilidad depende de la
// conexión y del catálogo. Tratarla como "sin indexar" bloquea el chat y deja el
// wizard en "Procesando" para siempre.
// =============================================================================

const DATABASE_SOURCE_TYPES = new Set([
  "sql",
  "postgres",
  "postgresql",
  "mysql",
  "mssql",
  "oracle",
  "snowflake",
  "db2",
]);

export function isDatabaseSourceType(type: string | null | undefined): boolean {
  return DATABASE_SOURCE_TYPES.has(String(type || "").toLowerCase());
}

export function isDatabaseSource(source: { type: string }): boolean {
  return isDatabaseSourceType(source.type);
}
