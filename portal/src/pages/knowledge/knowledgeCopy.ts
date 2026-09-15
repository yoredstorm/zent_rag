export const COPY = {
  subtitle:
    "El conocimiento son las fuentes que tus agentes leen. Aquí las cargas y ves si están sanas.",
  addSource: "Añadir fuente",
  continue: "Continuar",
  empty: "Todavía no hay fuentes. Carga documentos o datos y, después, créales un agente.",
  readyTitle: "Tus fuentes están listas.",
  readyBody: (count: number, broken: number) =>
    broken > 0
      ? `${count} fuentes conectadas. ${broken} necesitan atención.`
      : `${count} fuentes conectadas.`,
  playground: "Probar en Playground",
  createAgent: "Crear agente",
  viewSources: "Ver fuentes",
  sourcesHint:
    "Los agentes eligen estas fuentes en Agent Studio. Prueba en Playground cuando estén indexadas.",
  attentionEmpty: "No se detectaron problemas en tus fuentes ni trabajos de sincronización.",
  allSources: "Todas las fuentes",
  open: "Abrir",
  sync: "Sincronizar",
  syncNow: "Sincronizar ahora",
  lastSync: "Última sync",
  documents: "Documentos",
  issues: "Incidencias",
  indexedReady: "Esta fuente ya está indexada; el agente puede citar estos documentos.",
  indexedEmpty: "Aún no hay documentos; sincroniza o espera el indexado.",
  documentsEmpty: "Esta fuente aún no tiene documentos indexados.",
  neverSynced: "Todavía no se ha sincronizado.",
  learningSqlHint: "Aprendizaje lee esquemas SQL. Archivos e indexado viven en Fuentes.",
  sqlEmptyTitle: "Esta pantalla aprende bases SQL",
  sqlEmptyBody: (fileCount: number) =>
    fileCount > 0
      ? `Tienes ${fileCount} archivo${fileCount === 1 ? "" : "s"} en Fuentes. Conecta una base de datos para el grafo y el aprendizaje de esquema.`
      : "Conecta una base de datos en Fuentes o Conectores. Los PDFs se indexan en Fuentes, no aquí.",
  goToSources: "Ir a fuentes",
  collection: "Colección",
  collectionHint: "PDF y base en la misma colección; en Agent Studio marca las dos.",
  deleteSource: "Eliminar",
  deleteSourceBody: "Se borra la fuente, sus documentos y los vectores. No se puede deshacer.",
  principalKb: "Principal",
  uploadFile: "Archivo",
  pickFile: "Elige un archivo.",
};

const FILE_LIKE = new Set(["file", "csv", "excel", "gdrive"]);

export function fileLikeSourceCount(sources: { type?: string }[]): number {
  return sources.filter((source) => FILE_LIKE.has(source.type || "")).length;
}

const SOURCE_TYPE_LABEL: Record<string, string> = {
  file: "Archivo",
  sql: "Base de datos",
  csv: "CSV",
  excel: "Excel",
  web: "Sitio web",
  s3: "Amazon S3",
  api: "API",
  gdrive: "Google Drive",
};

export function isFileUploadType(type: string): boolean {
  return type === "file" || type === "csv" || type === "excel";
}

export function sourceTypeLabel(type: string, managed?: boolean): string {
  if (managed) return "Base de datos gestionada";
  return SOURCE_TYPE_LABEL[type] ?? type;
}

const SOURCE_STATUS_LABEL: Record<string, string> = {
  created: "En cola",
  connected: "Conectada",
  discovering: "Descubriendo",
  profiled: "Perfilada",
  ready: "Lista",
  ingesting: "Indexando",
  indexed: "Indexada",
  error: "Error",
};

export function sourceStatusLabel(status: string): string {
  return SOURCE_STATUS_LABEL[status] || status || "—";
}

export function sourceStatusBadgeClass(status: string): string {
  if (status === "error") return "badge-danger";
  if (status === "ready" || status === "indexed") return "badge-ok";
  if (status === "ingesting" || status === "discovering") return "badge-pending";
  return "badge-muted";
}

export function sourceTypeBlurb(type: string, managed?: boolean): string {
  if (managed || type === "sql") return "Tablas, campos y relaciones que el agente puede consultar.";
  if (type === "file") return "Temas y secciones del documento que el agente puede citar.";
  if (type === "csv" || type === "excel") return "Campos, medidas y dimensiones del dataset.";
  if (type === "web") return "Páginas y temas del sitio que el agente puede citar.";
  if (type === "gdrive") return "Archivos de Drive que el agente puede citar cuando estén indexados.";
  return "Abre la fuente para ver qué documentos hay indexados.";
}

const DOC_STATUS_LABEL: Record<string, string> = {
  active: "Activo",
  deleted: "Eliminado",
  stale: "Desactualizado",
};

export function documentStatusLabel(status: string): string {
  return DOC_STATUS_LABEL[status] || status || "—";
}

export const SOURCE_TABS = ["resumen", "documentos", "sincronizar"] as const;
export type SourceTab = (typeof SOURCE_TABS)[number];

export const SOURCE_TAB_LABEL: Record<SourceTab, string> = {
  resumen: "Resumen",
  documentos: "Documentos",
  sincronizar: "Sincronizar",
};

const LEGACY_SOURCE_TABS: Record<string, SourceTab> = {
  overview: "resumen",
  understood: "resumen",
  content: "resumen",
  permissions: "resumen",
  advanced: "resumen",
  sync: "sincronizar",
};

export function parseSourceTab(value: string | null): SourceTab {
  if (!value) return "resumen";
  if ((SOURCE_TABS as readonly string[]).includes(value)) return value as SourceTab;
  return LEGACY_SOURCE_TABS[value] ?? "resumen";
}
