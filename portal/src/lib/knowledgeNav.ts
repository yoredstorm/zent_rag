export const KNOWLEDGE_HEADINGS = {
  home: "Conocimiento",
  explorer: "Explorador",
  health: "Salud",
  sources: "Fuentes",
  activity: "Actividad",
  evaluation: "Evaluación",
  object: "Objeto de conocimiento",
  search: "Búsqueda de conocimiento",
  ask: "Preguntar",
  improve: "Mejorar",
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

export type KnowledgeSimpleSection = "resumen" | "fuentes" | "preguntar" | "mejorar";

export const KNOWLEDGE_SIMPLE_TABS: KnowledgeTab[] = [
  { to: "/knowledge", label: "Resumen", end: true },
  { to: "/knowledge/sources", label: "Fuentes" },
  { to: "/knowledge/ask", label: "Preguntar" },
  { to: "/knowledge/improve", label: "Mejorar" },
];

export type KnowledgeAdvancedGroup = {
  id: "investigar" | "administrar" | "diagnosticar" | "modelar";
  label: string;
  description: string;
  tabs: KnowledgeTab[];
};

/** Herramientas agrupadas por intención, no por pantalla técnica. */
export const KNOWLEDGE_SIMPLE_ADVANCED_GROUPS: KnowledgeAdvancedGroup[] = [
  {
    id: "investigar",
    label: "Investigar",
    description: "Explorar el conocimiento y su procedencia.",
    tabs: [
      { to: "/knowledge/explorer", label: "Explorador" },
      { to: "/knowledge/map", label: "Mapa" },
      { to: "/knowledge/understanding", label: "Estudio semántico" },
    ],
  },
  {
    id: "administrar",
    label: "Administrar",
    description: "Organizar fuentes, colecciones y conectores.",
    tabs: [
      { to: "/knowledge/workspaces", label: "Workspaces" },
      { to: "/knowledge/collections", label: "Colecciones" },
      { to: "/knowledge/documents", label: "Documentos" },
      { to: "/connectors", label: "Conectores" },
    ],
  },
  {
    id: "diagnosticar",
    label: "Diagnosticar",
    description: "Ver trabajos, evaluación y estado técnico.",
    tabs: [
      { to: "/knowledge/evaluation", label: "Evaluación" },
      { to: "/knowledge/jobs", label: "Trabajos" },
    ],
  },
  {
    id: "modelar",
    label: "Modelar datos",
    description: "Glosario, catálogo, SQL y bases gestionadas.",
    tabs: [
      { to: "/knowledge/glossary", label: "Glosario" },
      { to: "/knowledge/catalog", label: "Catálogo" },
      { to: "/knowledge/sql", label: "Fuentes SQL" },
      { to: "/knowledge/database", label: "Database Builder" },
      { to: "/knowledge/database/import", label: "Importar CSV / Excel" },
    ],
  },
];

export const KNOWLEDGE_LEGACY_ADVANCED_GROUPS: KnowledgeAdvancedGroup[] = [
  {
    id: "investigar",
    label: "Investigar",
    description: "Explorar el conocimiento y su procedencia.",
    tabs: [
      { to: "/knowledge/understanding", label: "Estudio semántico" },
      { to: "/knowledge/evaluation", label: "Evaluación" },
    ],
  },
  {
    id: "administrar",
    label: "Administrar",
    description: "Organizar fuentes, colecciones y conectores.",
    tabs: [
      { to: "/knowledge/workspaces", label: "Workspaces" },
      { to: "/knowledge/collections", label: "Colecciones" },
      { to: "/knowledge/documents", label: "Documentos" },
      { to: "/connectors", label: "Conectores" },
    ],
  },
  {
    id: "diagnosticar",
    label: "Diagnosticar",
    description: "Ver trabajos y estado técnico.",
    tabs: [{ to: "/knowledge/jobs", label: "Trabajos" }],
  },
  {
    id: "modelar",
    label: "Modelar datos",
    description: "Glosario, catálogo y bases gestionadas.",
    tabs: [
      { to: "/knowledge/glossary", label: "Glosario" },
      { to: "/knowledge/catalog", label: "Catálogo" },
      { to: "/knowledge/playground", label: "Playground" },
    ],
  },
];

export const KNOWLEDGE_SIMPLE_ADVANCED_TABS: KnowledgeTab[] =
  KNOWLEDGE_SIMPLE_ADVANCED_GROUPS.flatMap((group) => group.tabs);

export function knowledgeTabs(simple: boolean): KnowledgeTab[] {
  return simple ? KNOWLEDGE_SIMPLE_TABS : KNOWLEDGE_PILLARS;
}

export function knowledgeAdvancedGroups(
  simple: boolean,
): KnowledgeAdvancedGroup[] {
  return simple ? KNOWLEDGE_SIMPLE_ADVANCED_GROUPS : KNOWLEDGE_LEGACY_ADVANCED_GROUPS;
}

export function knowledgeAdvancedTabs(simple: boolean): KnowledgeTab[] {
  return knowledgeAdvancedGroups(simple).flatMap((group) => group.tabs);
}

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
  "/knowledge/ask": KNOWLEDGE_HEADINGS.ask,
  "/knowledge/improve": KNOWLEDGE_HEADINGS.improve,
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

export function legacyKnowledgeRedirectTarget(
  to: string,
  search: string,
  tab?: string,
): string {
  const params = new URLSearchParams(search);
  if (tab && !params.has("tab")) params.set("tab", tab);
  const query = params.toString();
  return `${to}${query ? `?${query}` : ""}`;
}

const SIMPLE_SECTION_PREFIXES: { section: KnowledgeSimpleSection; prefixes: string[] }[] = [
  { section: "resumen", prefixes: ["/knowledge", "/knowledge/activity"] },
  {
    section: "fuentes",
    prefixes: ["/knowledge/sources", "/knowledge/add", "/knowledge/sessions"],
  },
  {
    section: "preguntar",
    prefixes: [
      "/knowledge/ask",
      "/knowledge/search",
      "/knowledge/playground",
      "/knowledge/workspaces",
    ],
  },
  {
    section: "mejorar",
    prefixes: [
      "/knowledge/improve",
      "/knowledge/health",
      "/knowledge/quality",
      "/knowledge/review",
      "/knowledge/gaps",
      "/knowledge/conflicts",
      "/knowledge/improvements",
      "/knowledge/evaluation",
    ],
  },
];

const SIMPLE_ADVANCED_PREFIXES = [
  "/knowledge/explorer",
  "/knowledge/objects",
  "/knowledge/map",
  "/knowledge/understanding",
  "/knowledge/jobs",
  "/knowledge/documents",
  "/knowledge/collections",
  "/knowledge/glossary",
  "/knowledge/catalog",
  "/knowledge/sql",
  "/knowledge/database",
  "/connectors",
];

export function knowledgeSimpleSectionForPath(
  pathname: string,
): KnowledgeSimpleSection | "avanzado" | null {
  const path = normalizeKnowledgePath(pathname);
  if (SIMPLE_ADVANCED_PREFIXES.some((prefix) => matchesPrefix(path, prefix))) {
    return "avanzado";
  }
  for (const group of SIMPLE_SECTION_PREFIXES) {
    if (
      group.prefixes.some((prefix) =>
        prefix === "/knowledge" ? path === prefix : matchesPrefix(path, prefix),
      )
    ) {
      return group.section;
    }
  }
  return null;
}
