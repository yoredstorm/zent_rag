export const KNOWLEDGE_HEADINGS = {
  overview: "Resumen",
  sources: "Fuentes",
  model: "Modelo del negocio",
  quality: "Calidad",
  evaluation: "Evaluación",
  activity: "Actividad de aprendizaje",
  // Rutas legadas (redirects o Avanzado).
  learning: "Aprendizaje",
  map: "Mapa",
  glossary: "Glosario de negocio",
  catalog: "Catálogo",
  understanding: "Estudio semántico",
  review: "Cola de revisión",
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
  | "resumen"
  | "fuentes"
  | "modelo"
  | "calidad"
  | "evaluacion"
  | "avanzado";

export type KnowledgeTab = {
  to: string;
  label: string;
  end?: boolean;
};

export type KnowledgePillar = KnowledgeTab & {
  id: Exclude<KnowledgePillarId, "avanzado">;
};

export const KNOWLEDGE_PILLARS: KnowledgePillar[] = [
  { id: "resumen", to: "/knowledge", label: "Resumen", end: true },
  { id: "fuentes", to: "/knowledge/sources", label: "Fuentes" },
  { id: "modelo", to: "/knowledge/model", label: "Modelo" },
  { id: "calidad", to: "/knowledge/quality", label: "Calidad" },
  { id: "evaluacion", to: "/knowledge/evaluation", label: "Evaluación" },
];

export const KNOWLEDGE_ADVANCED_TABS: KnowledgeTab[] = [
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
  "/knowledge": KNOWLEDGE_HEADINGS.overview,
  "/knowledge/sources": KNOWLEDGE_HEADINGS.sources,
  "/knowledge/model": KNOWLEDGE_HEADINGS.model,
  "/knowledge/quality": KNOWLEDGE_HEADINGS.quality,
  "/knowledge/evaluation": KNOWLEDGE_HEADINGS.evaluation,
  "/knowledge/activity": KNOWLEDGE_HEADINGS.activity,
  "/knowledge/learning": KNOWLEDGE_HEADINGS.activity,
  "/knowledge/map": KNOWLEDGE_HEADINGS.model,
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
    id: "fuentes",
    prefixes: ["/knowledge/sources", "/knowledge/add"],
  },
  {
    id: "modelo",
    prefixes: ["/knowledge/model", "/knowledge/map"],
  },
  {
    id: "calidad",
    prefixes: [
      "/knowledge/quality",
      "/knowledge/review",
      "/knowledge/improvements",
      "/knowledge/gaps",
      "/knowledge/conflicts",
    ],
  },
  {
    id: "evaluacion",
    prefixes: ["/knowledge/evaluation"],
  },
  {
    id: "avanzado",
    prefixes: [
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
      "/knowledge/activity",
      "/knowledge/learning",
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
