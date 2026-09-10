export const KNOWLEDGE_HEADINGS = {
  overview: "Resumen",
  sources: "Fuentes",
  learning: "Aprendizaje",
  map: "Mapa",
  glossary: "Glosario de negocio",
  catalog: "Catálogo",
  understanding: "Entendimiento",
  review: "Cola de revisión",
  improvements: "Mejoras de inteligencia",
  jobs: "Trabajos de sync",
  playground: "Playground de búsqueda",
  database: "Database Builder",
  collections: "Colecciones",
  documents: "Documentos",
  sql: "Fuentes SQL",
  importCsv: "Import CSV / Excel",
  hub: "Knowledge Hub",
  add: "Añade conocimiento a Zent",
} as const;

export type KnowledgePillarId = "resumen" | "fuentes" | "semantica" | "mejora" | "avanzado";

export type KnowledgeTab = {
  to: string;
  label: string;
  end?: boolean;
};

export const KNOWLEDGE_PILLARS: (KnowledgeTab & { id: Exclude<KnowledgePillarId, "avanzado"> })[] = [
  { id: "resumen", to: "/knowledge", label: "Resumen", end: true },
  { id: "fuentes", to: "/knowledge/sources", label: "Fuentes" },
  { id: "semantica", to: "/knowledge/glossary", label: "Semántica" },
  { id: "mejora", to: "/knowledge/learning", label: "Mejora" },
];

export const KNOWLEDGE_SUBNAVS: Record<"semantica" | "mejora", KnowledgeTab[]> = {
  semantica: [
    { to: "/knowledge/glossary", label: "Términos" },
    { to: "/knowledge/understanding", label: "Entendimiento" },
    { to: "/knowledge/catalog", label: "Catálogo" },
  ],
  mejora: [
    { to: "/knowledge/learning", label: "Aprendizaje" },
    { to: "/knowledge/improvements", label: "Mejoras" },
    { to: "/knowledge/map", label: "Mapa" },
    { to: "/knowledge/review", label: "Revisión" },
  ],
};

export const KNOWLEDGE_ROUTE_TITLES: Record<string, string> = {
  "/knowledge": KNOWLEDGE_HEADINGS.overview,
  "/knowledge/sources": KNOWLEDGE_HEADINGS.sources,
  "/knowledge/learning": KNOWLEDGE_HEADINGS.learning,
  "/knowledge/map": KNOWLEDGE_HEADINGS.map,
  "/knowledge/glossary": KNOWLEDGE_HEADINGS.glossary,
  "/knowledge/catalog": KNOWLEDGE_HEADINGS.catalog,
  "/knowledge/understanding": KNOWLEDGE_HEADINGS.understanding,
  "/knowledge/review": KNOWLEDGE_HEADINGS.review,
  "/knowledge/improvements": KNOWLEDGE_HEADINGS.improvements,
  "/knowledge/database": KNOWLEDGE_HEADINGS.database,
  "/knowledge/collections": KNOWLEDGE_HEADINGS.collections,
  "/knowledge/documents": KNOWLEDGE_HEADINGS.documents,
  "/knowledge/sql": KNOWLEDGE_HEADINGS.sql,
  "/knowledge/jobs": KNOWLEDGE_HEADINGS.jobs,
  "/knowledge/playground": KNOWLEDGE_HEADINGS.playground,
  "/knowledge-hub": KNOWLEDGE_HEADINGS.hub,
  "/knowledge/add": KNOWLEDGE_HEADINGS.add,
};

export const KNOWLEDGE_ADVANCED_TABS: KnowledgeTab[] = [
  { to: "/knowledge/jobs", label: "Sincronización" },
  { to: "/knowledge/sql", label: "SQL" },
  { to: "/knowledge/database", label: "Base" },
  { to: "/connectors", label: "Conectores" },
  { to: "/knowledge/collections", label: "Colecciones" },
  { to: "/knowledge/documents", label: "Documentos" },
  { to: "/knowledge/playground", label: "Búsqueda" },
  { to: "/knowledge-hub", label: "Knowledge Hub" },
];

const PREFIX_GROUPS: { id: KnowledgePillarId; prefixes: string[] }[] = [
  {
    id: "fuentes",
    prefixes: ["/knowledge/sources", "/knowledge/add"],
  },
  {
    id: "semantica",
    prefixes: ["/knowledge/glossary", "/knowledge/understanding", "/knowledge/catalog"],
  },
  {
    id: "mejora",
    prefixes: [
      "/knowledge/learning",
      "/knowledge/improvements",
      "/knowledge/map",
      "/knowledge/review",
    ],
  },
  {
    id: "avanzado",
    prefixes: [
      "/knowledge/jobs",
      "/knowledge/sql",
      "/knowledge/database",
      "/knowledge/collections",
      "/knowledge/documents",
      "/knowledge/playground",
      "/knowledge-hub",
      "/connectors",
    ],
  },
];

export function normalizeKnowledgePath(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) return pathname.slice(0, -1);
  return pathname || "/";
}

function matchesPrefix(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`);
}

export function knowledgePillarForPath(pathname: string): KnowledgePillarId {
  const path = normalizeKnowledgePath(pathname);
  if (path === "/knowledge") return "resumen";
  for (const group of PREFIX_GROUPS) {
    if (group.prefixes.some((prefix) => matchesPrefix(path, prefix))) return group.id;
  }
  return "resumen";
}

export function knowledgeTabIsActive(pathname: string, tab: KnowledgeTab): boolean {
  const path = normalizeKnowledgePath(pathname);
  if (tab.end) return path === tab.to;
  return matchesPrefix(path, tab.to);
}
