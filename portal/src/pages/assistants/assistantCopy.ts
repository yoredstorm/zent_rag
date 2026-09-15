import { GATEWAY_ROUTES, TOOL_CHOICES } from "../../components/agentStudio/advancedCopy";

export const COPY = {
  tagline: "Un asistente es un agente trabajando solo: vigila datos, corre flujos y te avisa.",
  listSubtitle: "Agentes que trabajan solos. Aquí ves qué vigilan y si algo falló.",
  createAgent: "Crear agente",
  createHint: "Primero el cerebro, después las automatizaciones.",
  empty: "Todavía ningún agente tiene trabajo automático. Crea un agente y, en su ficha, agrega una automatización.",
  openOperation: "Ver operación",
  editAgent: "Editar agente",
  playground: "Probar en Playground",
  watchingTitle: "Qué está vigilando",
  watchingEmpty: "Nada todavía. Agrega una automatización.",
  knowledgeTitle: "Conocimiento",
  knowledgeEmpty: "Sin bases de conocimiento asociadas.",
  toolsTitle: "Herramientas",
  toolsEmpty: "Ninguna herramienta extra.",
  permissionsEmpty: "Usa solo lo de sus flujos.",
  automationsTitle: "¿Qué debe hacer solo?",
  automationsHint:
    "El copiloto propondrá el flujo y lo asociará a este asistente. Si no necesita razonamiento, te avisará que puede funcionar sin IA (costo casi cero).",
  automationsEmpty: "Aún no hay automatizaciones para este asistente.",
};

export const ASSISTANT_TABS = ["resumen", "automatizaciones", "actividad"] as const;
export type AssistantTab = (typeof ASSISTANT_TABS)[number];

export const ASSISTANT_TAB_LABEL: Record<AssistantTab, string> = {
  resumen: "Qué hace",
  automatizaciones: "Automatizaciones",
  actividad: "Actividad",
};

const LEGACY_TABS: Record<string, AssistantTab> = {
  conocimiento: "resumen",
  permisos: "resumen",
  ajustes: "resumen",
};

export function parseAssistantTab(value: string | null): AssistantTab {
  if (!value) return "resumen";
  if ((ASSISTANT_TABS as readonly string[]).includes(value)) return value as AssistantTab;
  return LEGACY_TABS[value] ?? "resumen";
}

export type AssistantCard = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  is_active: boolean;
  automations: number;
  active: number;
  actions_today: number;
  last_activity: string | null;
  health: string;
  watches: string[];
  automation_names: string[];
};

export type AssistantAgent = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  is_active: boolean;
  model: string | null;
  tools: string[];
  config: { purpose?: string | null; knowledge_base_ids?: string[] };
};

export type Automation = {
  workflow_id: string;
  name: string;
  status: string;
  when: string;
  runs_7d: number;
  failed_runs: number;
  success_rate: number | null;
  last_activity: string | null;
};

export type AutomationsPayload = {
  summary: {
    automations: number;
    active: number;
    actions_today: number;
    last_activity: string | null;
    health: string;
  };
  automations: Automation[];
};

export type ActivityItem = {
  kind: string;
  title: string;
  detail: string | null;
  at: string;
  status: string;
  tech: Record<string, unknown>;
};

export type ActivityPayload = {
  items: ActivityItem[];
  run_count: number;
  automation_count: number;
};

export const HEALTH_BADGE: Record<string, { text: string; className: string }> = {
  healthy: { text: "● Activo", className: "badge badge-ok" },
  needs_attention: { text: "● Necesita atención", className: "badge badge-danger" },
  paused: { text: "● Pausado", className: "badge badge-muted" },
  idle: { text: "○ Sin automatizaciones", className: "badge badge-muted" },
};

export const HEALTH_STATUS: Record<string, string> = {
  healthy: "Saludable",
  needs_attention: "Necesita atención",
  paused: "Pausado",
  idle: "Sin automatizaciones",
};

const WORKFLOW_STATUS: Record<string, string> = {
  active: "Activo",
  draft: "Borrador",
  paused: "Pausado",
  archived: "Archivado",
  inactive: "Inactivo",
};

export function workflowStatusLabel(status: string): string {
  return WORKFLOW_STATUS[status] ?? status;
}

export function modelHumanLabel(model: string | null): string {
  const raw = (model || "zent-default").trim() || "zent-default";
  const found = GATEWAY_ROUTES.find((route) => route.value === raw);
  if (!found) return raw;
  const short = found.label.replace(/\s*\([^)]*\)\s*/g, "").trim();
  return `${short} · ${found.tech}`;
}

export function toolHumanLabel(tool: string): string {
  return TOOL_CHOICES.find((choice) => choice.tool === tool)?.label ?? tool;
}

/** El API puede seguir diciendo "El agente…"; en esta pantalla se lee como asistente. */
export function humanizeActivityTitle(title: string): string {
  return title.replace(/^El agente\b/, "El asistente");
}
