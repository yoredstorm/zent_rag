import {
  Bell,
  Books,
  Buildings,
  ChartBar,
  ChartLineUp,
  ChatCircleDots,
  ChatsCircle,
  ClipboardText,
  Code,
  Compass,
  CreditCard,
  Database,
  Eye,
  FolderSimple,
  FlowArrow,
  Gear,
  GraduationCap,
  Graph,
  Key,
  Lifebuoy,
  NotePencil,
  Plugs,
  Pulse,
  Robot,
  Rocket,
  RocketLaunch,
  StackSimple,
  Scales,
  ShieldCheck,
  ShieldStar,
  Sparkle,
  SquaresFour,
  Storefront,
  Swap,
  Target,
  UsersThree,
  WarningOctagon,
  WebhooksLogo,
  Wrench,
  type Icon,
} from "@phosphor-icons/react";
import type { Session } from "../api";

export type NavLeaf = { to: string; label: string; icon: Icon; end?: boolean; key?: string };
export type NavSection = { heading: string; items: NavLeaf[] };
export type NavGroup = {
  label: string | null;
  items?: NavLeaf[];
  sections?: NavSection[];
  collapsible?: boolean;
  /** Arranca colapsado (el usuario puede abrirlo; se recuerda su elección). */
  defaultCollapsed?: boolean;
};

/**
 * Information architecture del workspace.
 *
 * Clusters por modelo mental, no por organigrama:
 * Inicio (qué está pasando) → Conocimiento (qué sabe Zent) → Construir (qué creo)
 * → Operar (qué corre solo) → Evaluar (qué tan bien responde) → Desarrollar (cómo integro)
 * → Gobernar (cómo lo controlo) → Gestionar (quién entra, qué se paga).
 *
 * Las rutas no cambian: esto es jerarquía visual y de descubrimiento.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Inicio",
    items: [
      { to: "/", label: "Panel general", icon: SquaresFour, end: true },
      { to: "/intelligence", label: "Intelligence", icon: Sparkle },
      { to: "/chat-insights", label: "Chat Insights", icon: ChatsCircle },
    ],
  },
  {
    label: "Conocimiento",
    items: [
      { to: "/knowledge", label: "Conocimiento", icon: Database },
      {
        to: "/company-intelligence",
        label: "Company Intelligence",
        icon: Graph,
      },
      { to: "/knowledge-hub", label: "Knowledge Hub", icon: Books },
      { to: "/data-sources", label: "Fuentes de datos", icon: StackSimple },
      { to: "/integrations", label: "Integraciones API", icon: Plugs },
      { to: "/connectors", label: "Conectores", icon: Plugs, key: "connectors" },
    ],
  },
  {
    label: "Construir",
    items: [
      { to: "/chat", label: "Playground", icon: ChatCircleDots },
      { to: "/agents", label: "Agentes", icon: Robot },
      { to: "/workflows", label: "Workflows", icon: FlowArrow },
      { to: "/prompts", label: "Instrucciones", icon: NotePencil, key: "prompts" },
      { to: "/copilot", label: "Copilot", icon: Sparkle },
    ],
  },
  {
    label: "Operar",
    items: [
      { to: "/assistants", label: "Asistentes", icon: Pulse },
      { to: "/watchers", label: "Vigilancia de datos", icon: Eye },
      { to: "/deployments", label: "Despliegues", icon: RocketLaunch },
      { to: "/environments", label: "Entornos", icon: StackSimple },
      { to: "/usage", label: "Analítica", icon: ChartLineUp },
    ],
  },
  {
    label: "Evaluar",
    items: [
      { to: "/ai-quality", label: "Calidad de IA", icon: Target },
      { to: "/evaluation", label: "Evaluación", icon: ChartBar, key: "eval_ui" },
    ],
  },
  {
    label: "Desarrollar",
    items: [
      { to: "/keys", label: "API y Claves", icon: Key, key: "keys" },
      { to: "/webhooks", label: "Webhooks", icon: WebhooksLogo, key: "keys" },
      { to: "/developers", label: "Centro de desarrolladores", icon: Code },
      { to: "/developers/tools", label: "Herramientas", icon: Wrench },
      { to: "/developers/mcp", label: "MCP", icon: Plugs },
    ],
  },
  {
    label: "Gobernar",
    items: [
      { to: "/security", label: "Seguridad y Auditoría", icon: ShieldCheck, key: "audit" },
      { to: "/security-center", label: "Security Center", icon: ShieldStar },
      { to: "/risk-center", label: "Risk Center", icon: WarningOctagon },
      { to: "/governance", label: "Gobernanza", icon: Scales },
      { to: "/audit/compliance", label: "Audit Compliance", icon: ClipboardText },
      { to: "/disaster-recovery", label: "Disaster Recovery", icon: Lifebuoy },
    ],
  },
  {
    label: "Gestionar",
    collapsible: true,
    defaultCollapsed: true,
    items: [
      { to: "/team", label: "Equipo y Acceso", icon: UsersThree, key: "users" },
      { to: "/billing", label: "Facturación", icon: CreditCard, key: "billing" },
      { to: "/settings", label: "Configuración", icon: Gear, key: "settings" },
      { to: "/workspaces", label: "Workspaces", icon: Buildings },
      { to: "/projects", label: "Proyectos", icon: FolderSimple },
      { to: "/marketplace", label: "Marketplace", icon: Storefront },
      { to: "/products", label: "Catálogo de productos", icon: Storefront, key: "products" },
      { to: "/releases", label: "Releases", icon: Rocket },
      { to: "/migrations", label: "Migraciones", icon: Swap },
      { to: "/training", label: "Training", icon: GraduationCap },
      { to: "/onboarding", label: "Onboarding", icon: Compass },
      { to: "/demos", label: "Demo Center", icon: Sparkle },
      { to: "/notifications", label: "Notificaciones", icon: Bell },
    ],
  },
];

type Entitlements = Record<string, boolean | number | null>;

function isViewerOnly(roles: string[] | undefined): boolean {
  const r = roles || [];
  if (r.some((role) => role === "owner" || role === "admin" || role === "member")) {
    return false;
  }
  return r.includes("viewer");
}

export function canSeeNavItem(
  session: Session | null,
  key?: string,
  entitlements: Entitlements = {}
): boolean {
  if (!key) return true;
  const roles = session?.roles || [];
  const perms = session?.permissions || [];
  const orgAdmin = roles.includes("owner") || roles.includes("admin");
  if (key === "users" || key === "keys") return orgAdmin;
  if (key === "billing" || key === "settings") return orgAdmin;
  if (key === "audit") return orgAdmin || perms.includes("audit:read");
  if (key === "prompts" || key === "connectors") return !isViewerOnly(roles);
  if (key === "eval_ui") return entitlements.eval_ui === true;
  return true;
}

export function navLeaves(group: NavGroup): NavLeaf[] {
  return [...(group.items ?? []), ...(group.sections ?? []).flatMap((s) => s.items)];
}

export function visibleNavLeaves(session: Session | null, entitlements: Entitlements = {}): NavLeaf[] {
  return NAV_GROUPS.flatMap((g) =>
    navLeaves(g).filter((item) => canSeeNavItem(session, item.key, entitlements))
  );
}

/** Grupo y hoja de navegación activos para una ruta (título, breadcrumbs, contexto). */
export function navContextForPath(
  pathname: string
): { group: NavGroup; leaf: NavLeaf } | null {
  for (const group of NAV_GROUPS) {
    for (const leaf of navLeaves(group)) {
      if (leaf.end ? pathname === leaf.to : pathname === leaf.to || pathname.startsWith(`${leaf.to}/`)) {
        return { group, leaf };
      }
    }
  }
  return null;
}
