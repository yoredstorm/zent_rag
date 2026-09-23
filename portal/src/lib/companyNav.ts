import type { Icon } from "@phosphor-icons/react";

export type CompanyTab = {
  to: string;
  label: string;
  end?: boolean;
};

/** Secciones de Company Intelligence Studio (§1). */
export const COMPANY_TABS: readonly CompanyTab[] = [
  { to: "/company-intelligence", label: "Overview", end: true },
  { to: "/company-intelligence/map", label: "Company Map" },
  { to: "/company-intelligence/concepts", label: "Concepts" },
  { to: "/company-intelligence/processes", label: "Processes" },
  { to: "/company-intelligence/systems", label: "Systems" },
  { to: "/company-intelligence/data", label: "Data" },
  { to: "/company-intelligence/rules", label: "Rules" },
  { to: "/company-intelligence/events", label: "Events" },
  { to: "/company-intelligence/relationships", label: "Relationships" },
  { to: "/company-intelligence/authority", label: "Source Authority" },
  { to: "/company-intelligence/gaps", label: "Knowledge Gaps" },
  { to: "/company-intelligence/changes", label: "Changes" },
  { to: "/company-intelligence/people", label: "Institucional" },
  { to: "/company-intelligence/ask", label: "Preguntar" },
];

/** Tipos de entidad que cubre cada listado (§1). */
export const COMPANY_LIST_TYPES: Record<string, string[]> = {
  concepts: ["concept", "term", "domain"],
  processes: ["process", "workflow"],
  systems: ["system", "service", "database", "api"],
  data: ["dataset", "table", "field"],
  rules: ["rule", "policy", "metric", "kpi"],
  events: ["event"],
};

export const COMPANY_HEADINGS: Record<string, string> = {
  overview: "Company Intelligence",
  map: "Company Map",
  concepts: "Conceptos de negocio",
  processes: "Procesos",
  systems: "Sistemas",
  data: "Datos",
  rules: "Reglas y políticas",
  events: "Eventos",
  relationships: "Relaciones",
  authority: "Source Authority",
  gaps: "Knowledge Gaps",
  changes: "Cambios",
  people: "Conocimiento institucional",
  ask: "Preguntar a tu empresa",
  entity: "Entidad",
};

export function companyTabIsActive(pathname: string, tab: CompanyTab): boolean {
  if (tab.end) return pathname === tab.to;
  return pathname === tab.to || pathname.startsWith(`${tab.to}/`);
}

export type CompanyIconMap = Record<string, Icon>;
