import type { Session } from "../api";
import { canSeeNavItem } from "./nav";

export const PRODUCT_TOUR_STORAGE_KEY = "zent_product_tour_v2";
export const PRODUCT_TOUR_START_EVENT = "zent:product-tour-start";

export type TourStatus = { status: "skipped" | "completed" };

export type TourStep = {
  id: string;
  target: string;
  title: string;
  body: string;
  navKey?: string;
  fallbackTarget?: string;
  optional?: boolean;
};

type Entitlements = Record<string, boolean | number | null>;

export const TOUR_STEPS: TourStep[] = [
  {
    id: "dashboard",
    target: "nav-dashboard",
    title: "Panel general",
    body: "Resumen del tenant: salud del sistema, uso reciente y lo que pide atención. Entra aquí cuando quieras ver si algo está roto o cuánto consumiste, sin recorrer cada módulo.",
  },
  {
    id: "build",
    target: "nav-group-construir",
    title: "Construir",
    body: "Este bloque es donde nace el producto: agentes, conocimiento, playground y workflows. Empieza aquí si todavía no tienes un agente respondiendo con tus datos.",
  },
  {
    id: "playground",
    target: "nav-chat",
    title: "Playground",
    body: "Prueba preguntas contra tus agentes sin desplegar nada a producción. Úsalo para iterar instrucciones y comprobar respuestas antes de que un usuario real las vea.",
  },
  {
    id: "agents",
    target: "nav-agents",
    title: "Agentes",
    body: "Crea, configura y versiona cada agente: instrucciones, herramientas y cómo habla. De aquí sale lo que tus usuarios van a consultar en chat, API o workflows.",
  },
  {
    id: "knowledge",
    target: "nav-knowledge",
    title: "Conocimiento",
    body: "Sube documentos, bases y fuentes para que el agente cite información tuya. Entra cuando quieras que las respuestas dejen de ser genéricas y usen tu negocio.",
  },
  {
    id: "workflows",
    target: "nav-workflows",
    title: "Workflows",
    body: "Encadena agentes, conectores y aprobaciones en un proceso. Úsalo cuando una pregunta no basta y hay que ejecutar varios pasos (clasificar, avisar, escribir en otro sistema).",
  },
  {
    id: "operate",
    target: "nav-group-operar",
    title: "Operar",
    body: "Aquí operas lo que ya construiste: métricas, calidad, despliegues y entornos. Pasa a este bloque cuando el agente deja de ser un experimento y tiene que aguantar uso real.",
  },
  {
    id: "usage",
    target: "nav-usage",
    title: "Analítica",
    body: "Consumo, latencia y errores en el tiempo. Entra cuando quieras ver si el uso sube, si algo se puso lento o si un modelo está fallando.",
  },
  {
    id: "ai-quality",
    target: "nav-ai-quality",
    title: "Calidad de IA",
    body: "Evalúa si las respuestas cumplen el listón: alucinaciones, citas y regresiones. Úsalo antes de un go-live o cuando notas que la calidad bajó sin un cambio obvio.",
  },
  {
    id: "deployments",
    target: "nav-deployments",
    title: "Despliegues",
    body: "Publica una versión del agente en un entorno (producción o staging). Entra cuando ya validaste en playground y quieres que el tráfico real use esa versión.",
  },
  {
    id: "environments",
    target: "nav-environments",
    title: "Entornos",
    body: "Separa staging de producción y controla variables por entorno. Úsalo para probar cambios con datos o claves distintas sin tocar a los usuarios finales.",
  },
  {
    id: "developers-group",
    target: "nav-group-desarrolladores",
    title: "Desarrolladores",
    body: "Todo lo que necesitas para integrar Zent fuera de este panel: API, webhooks y MCP. Entra a este bloque cuando tu producto, no solo el chat interno, tiene que hablar con Zent.",
  },
  {
    id: "keys",
    target: "nav-keys",
    navKey: "keys",
    title: "API y Claves",
    body: "Crea y rota claves de API para que backends y scripts llamen a tus agentes. Úsalas en servidor; no las pegues en el frontend ni las compartas en tickets.",
  },
  {
    id: "webhooks",
    target: "nav-webhooks",
    navKey: "keys",
    title: "Webhooks",
    body: "Zent avisa a tu sistema cuando pasa algo (ingesta lista, evaluación, error). Configúralos si quieres reaccionar en tu propio backend sin estar preguntando a la API.",
  },
  {
    id: "developers-center",
    target: "nav-developers",
    title: "Centro de desarrolladores",
    body: "Guías, ejemplos y puntos de entrada para integrar la API. Úsalo cuando estás escribiendo el primer cliente o no recuerdas qué endpoint usar.",
  },
  {
    id: "mcp",
    target: "nav-mcp",
    title: "MCP",
    body: "Conecta Zent como servidor MCP para que otras apps (Cursor, Claude, etc.) usen tus agentes y conocimiento. Úsalo si integras Zent dentro de herramientas que ya hablan MCP.",
  },
  {
    id: "organization",
    target: "nav-group-organizacion",
    title: "Organización",
    body: "Personas, plan, seguridad y ajustes del tenant. Este bloque no construye agentes: administra quién entra, qué se paga y cómo queda auditado.",
  },
  {
    id: "team",
    target: "nav-team",
    navKey: "users",
    title: "Equipo y Acceso",
    body: "Invita gente, asigna roles y controla quién puede crear agentes o ver claves. Entra cuando alguien nuevo necesita acceso o cuando hay que quitar un permiso.",
  },
  {
    id: "billing",
    target: "nav-billing",
    navKey: "billing",
    title: "Facturación",
    body: "Plan, consumo facturable y límites del tenant. Revisa esta página si el trial se acaba, si vas a subir de plan o si un tope de requests te está cortando.",
  },
  {
    id: "security",
    target: "nav-security",
    navKey: "audit",
    title: "Seguridad y Auditoría",
    body: "Auditoría de acciones sensibles y controles de seguridad del tenant. Úsalo para ver quién cambió qué, o para cumplir una revisión interna.",
  },
  {
    id: "settings",
    target: "nav-settings",
    navKey: "settings",
    title: "Configuración",
    body: "Nombre, preferencias y ajustes generales de la organización. Entra para cambios de configuración que no son de un agente concreto ni de facturación.",
  },
  {
    id: "advanced",
    target: "nav-group-avanzado",
    title: "Avanzado",
    body: "Evaluación extra, conectores, gobernanza, riesgo y herramientas de plataforma. Está colapsado a propósito: ábrelo cuando el flujo básico ya te queda corto.",
  },
  {
    id: "workspace",
    target: "workspace-selector",
    title: "Workspace",
    body: "Cambia entre workspaces de la misma organización sin volver a iniciar sesión. Úsalo si tienes demo y negocio separados, o varios equipos en un mismo tenant.",
  },
  {
    id: "search",
    target: "command-palette",
    optional: true,
    title: "Buscar",
    body: "Ctrl+K abre la paleta y salta a páginas, agentes o fuentes. Úsalo cuando ya conoces el nombre y no quieres bajar todo el menú.",
  },
];

export function filterTourSteps(
  session: Session | null,
  entitlements: Entitlements = {}
): TourStep[] {
  return TOUR_STEPS.map((step) => {
    if (!step.navKey) return step;
    if (canSeeNavItem(session, step.navKey, entitlements)) return step;
    if (step.fallbackTarget) {
      return { ...step, target: step.fallbackTarget };
    }
    return null;
  }).filter((step): step is TourStep => step !== null);
}

export function readTourStatus(): TourStatus | null {
  const raw = window.localStorage.getItem(PRODUCT_TOUR_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as TourStatus;
    if (parsed.status === "skipped" || parsed.status === "completed") return parsed;
  } catch {
    return null;
  }
  return null;
}

export function shouldAutoStart(): boolean {
  return readTourStatus() === null;
}

function writeStatus(status: TourStatus["status"]) {
  window.localStorage.setItem(PRODUCT_TOUR_STORAGE_KEY, JSON.stringify({ status }));
}

export function markSkipped(): void {
  writeStatus("skipped");
}

export function markCompleted(): void {
  writeStatus("completed");
}

export function visibleTourTarget(id: string): HTMLElement | null {
  const nodes = document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`);
  for (const node of nodes) {
    const rect = node.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return node;
  }
  return null;
}

export function visibleTourSteps(steps: TourStep[]): TourStep[] {
  return steps.filter((step) => !step.optional || visibleTourTarget(step.target) !== null);
}

export function requestProductTourStart(): void {
  window.dispatchEvent(new CustomEvent(PRODUCT_TOUR_START_EVENT));
}

const PATH_TOUR_TARGET: Record<string, string> = {
  "/": "nav-dashboard",
  "/chat": "nav-chat",
  "/agents": "nav-agents",
  "/knowledge": "nav-knowledge",
  "/workflows": "nav-workflows",
  "/usage": "nav-usage",
  "/ai-quality": "nav-ai-quality",
  "/deployments": "nav-deployments",
  "/environments": "nav-environments",
  "/keys": "nav-keys",
  "/webhooks": "nav-webhooks",
  "/developers": "nav-developers",
  "/developers/mcp": "nav-mcp",
  "/team": "nav-team",
  "/billing": "nav-billing",
  "/security": "nav-security",
  "/settings": "nav-settings",
};

export function tourTargetForPath(to: string): string | undefined {
  return PATH_TOUR_TARGET[to];
}

export function tourTargetForGroup(label: string | null): string | undefined {
  if (label === "Construir") return "nav-group-construir";
  if (label === "Operar") return "nav-group-operar";
  if (label === "Desarrolladores") return "nav-group-desarrolladores";
  if (label === "Organización") return "nav-group-organizacion";
  if (label === "Avanzado") return "nav-group-avanzado";
  return undefined;
}
