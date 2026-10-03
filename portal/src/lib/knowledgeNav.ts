export const KNOWLEDGE_HEADINGS = {
  home: "Conocimiento",
  explorer: "Explorador",
  health: "Salud",
  sources: "Fuentes",
  activity: "Actividad",
  evaluation: "Evaluación",
  object: "Objeto de conocimiento",
  search: "Búsqueda de conocimiento",
  // Rutas legadas (redirects o Avanzado).
  overview: "Conocimiento",
  model: "Explorador",
  quality: "Salud",
  learning: "Actividad",
  map: "Explorador",
  glossary: "Glosario de negocio",
  catalog: "Catálogo",
  understanding: "Estudio semántico",
  review: "Conflictos",
  improvements: "Mejoras de inteligencia",
  jobs: "Trabajos de sync",
  playground: "Playground de búsqueda",
  database: "Database Builder",
  collections: "Colecciones",
  documents: "Documentos",
  sql: "Fuentes SQL",
  importCsv: "Import CSV / Excel",
  add: "Añade conocimiento a Zent",
  workspaces: "Workspaces",
} as const;

export type KnowledgePillarId =
  | "inicio"
  | "explorador"
  | "salud"
  | "fuentes"
  | "actividad"
  | "avanzado";

export type KnowledgeTab = {
  to: string;
  label: string;
  end?: boolean;
};

export type KnowledgePillar = KnowledgeTab & {
  id: Exclude<KnowledgePillarId, "avanzado">;
};

/**
 * IA del Knowledge OS: el conocimiento primero, el pipeline después.
 * Inicio (qué sabe) · Explorador (cómo se organiza) · Salud (qué necesita
 * atención) · Fuentes (de dónde viene) · Actividad (qué está aprendiendo).
 */
export const KNOWLEDGE_PILLARS: KnowledgePillar[] = [
  { id: "inicio", to: "/knowledge", label: "Inicio", end: true },
  { id: "explorador", to: "/knowledge/explorer", label: "Explorador" },
  { id: "salud", to: "/knowledge/health", label: "Salud" },
  { id: "fuentes", to: "/knowledge/sources", label: "Fuentes" },
  { id: "actividad", to: "/knowledge/activity", label: "Actividad" },
];

export const KNOWLEDGE_ADVANCED_TABS: KnowledgeTab[] = [
  { to: "/knowledge/evaluation", label: "Evaluación" },
  { to: "/knowledge/understanding", label: "Estudio semántico" },
  { to: "/knowledge/playground", label: "Playground" },
  { to: "/knowledge/jobs", label: "Trabajos" },
  { to: "/knowledge/documents", label: "Documentos" },
  { to: "/knowledge/collections", label: "Colecciones" },
  { to: "/knowledge/workspaces", label: "Workspaces" },
  { to: "/knowledge/glossary", label: "Glosario" },
  { to: "/knowledge/catalog", label: "Catálogo" },
  { to: "/connectors", label: "Conectores" },
];

export const KNOWLEDGE_ROUTE_TITLES: Record<string, string> = {
  "/knowledge": KNOWLEDGE_HEADINGS.home,
  "/knowledge/explorer": KNOWLEDGE_HEADINGS.explorer,
  "/knowledge/health": KNOWLEDGE_HEADINGS.health,
  "/knowledge/sources": KNOWLEDGE_HEADINGS.sources,
  "/knowledge/activity": KNOWLEDGE_HEADINGS.activity,
  "/knowledge/evaluation": KNOWLEDGE_HEADINGS.evaluation,
  "/knowledge/search": KNOWLEDGE_HEADINGS.search,
  // Rutas legadas.
  "/knowledge/model": KNOWLEDGE_HEADINGS.model,
  "/knowledge/quality": KNOWLEDGE_HEADINGS.quality,
  "/knowledge/learning": KNOWLEDGE_HEADINGS.activity,
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
  "/knowledge/add": KNOWLEDGE_HEADINGS.add,
  "/knowledge/workspaces": KNOWLEDGE_HEADINGS.workspaces,
};

const PREFIX_GROUPS: { id: KnowledgePillarId; prefixes: string[] }[] = [
  {
    id: "explorador",
    prefixes: [
      "/knowledge/explorer",
      "/knowledge/objects",
      "/knowledge/model",
      "/knowledge/map",
    ],
  },
  {
    id: "salud",
    prefixes: [
      "/knowledge/health",
      "/knowledge/quality",
      "/knowledge/review",
      "/knowledge/improvements",
      "/knowledge/gaps",
      "/knowledge/conflicts",
    ],
  },
  {
    id: "fuentes",
    prefixes: ["/knowledge/sources", "/knowledge/add"],
  },
  {
    id: "actividad",
    prefixes: ["/knowledge/activity", "/knowledge/learning", "/knowledge/sessions"],
  },
  {
    id: "avanzado",
    prefixes: [
      "/knowledge/evaluation",
      "/knowledge/glossary",
      "/knowledge/understanding",
      "/knowledge/catalog",
      "/knowledge/workspaces",
      "/knowledge/jobs",
      "/knowledge/sql",
      "/knowledge/database",
      "/knowledge/collections",
      "/knowledge/documents",
      "/knowledge/playground",
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
  if (path === "/knowledge" || path === "/knowledge/search") return "inicio";
  for (const group of PREFIX_GROUPS) {
    if (group.prefixes.some((prefix) => matchesPrefix(path, prefix))) return group.id;
  }
  return "inicio";
}

export function knowledgeTabIsActive(pathname: string, tab: KnowledgeTab): boolean {
  const path = normalizeKnowledgePath(pathname);
  if (tab.end) return path === tab.to;
  return matchesPrefix(path, tab.to);
}
