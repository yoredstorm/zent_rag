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
  FolderSimple,
  FlowArrow,
  Gear,
  GraduationCap,
  Key,
  Lifebuoy,
  NotePencil,
  Plugs,
  Robot,
  Rocket,
  RocketLaunch,
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
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Panel general",
    items: [{ to: "/", label: "Panel general", icon: SquaresFour, end: true }],
  },
  {
    label: "Construir",
    items: [
      { to: "/chat", label: "Playground", icon: ChatCircleDots },
      { to: "/agents", label: "Agentes", icon: Robot },
      { to: "/knowledge", label: "Conocimiento", icon: Database },
      { to: "/workflows", label: "Workflows", icon: FlowArrow },
    ],
  },
  {
    label: "Operar",
    items: [
      { to: "/usage", label: "Analítica", icon: ChartLineUp },
      { to: "/ai-quality", label: "Calidad de IA", icon: Target },
      { to: "/deployments", label: "Despliegues", icon: RocketLaunch },
    ],
  },
  {
    label: "Desarrolladores",
    items: [
      { to: "/keys", label: "API y Claves", icon: Key, key: "keys" },
      { to: "/webhooks", label: "Webhooks", icon: WebhooksLogo, key: "keys" },
      { to: "/developers", label: "Centro de desarrolladores", icon: Code },
      { to: "/developers/mcp", label: "MCP", icon: Plugs },
    ],
  },
  {
    label: "Organización",
    items: [
      { to: "/team", label: "Equipo y Acceso", icon: UsersThree, key: "users" },
      { to: "/billing", label: "Facturación", icon: CreditCard, key: "billing" },
      { to: "/security", label: "Seguridad y Auditoría", icon: ShieldCheck, key: "audit" },
      { to: "/settings", label: "Configuración", icon: Gear, key: "settings" },
    ],
  },
  {
    label: "Avanzado",
    collapsible: true,
    sections: [
      {
        heading: "Agentes",
        items: [{ to: "/prompts", label: "Instrucciones", icon: NotePencil, key: "prompts" }],
      },
      {
        heading: "Evaluación",
        items: [{ to: "/evaluation", label: "Evaluación", icon: ChartBar, key: "eval_ui" }],
      },
      {
        heading: "Datos y conectores",
        items: [
          { to: "/connectors", label: "Conectores", icon: Plugs, key: "connectors" },
          { to: "/knowledge-hub", label: "Knowledge Hub", icon: Books },
        ],
      },
      {
        heading: "Gobernanza y riesgo",
        items: [
          { to: "/security-center", label: "Security Center", icon: ShieldStar },
          { to: "/risk-center", label: "Risk Center", icon: WarningOctagon },
          { to: "/governance", label: "Gobernanza", icon: Scales },
          { to: "/audit/compliance", label: "Audit Compliance", icon: ClipboardText },
        ],
      },
      {
        heading: "Plataforma",
        items: [
          { to: "/projects", label: "Proyectos", icon: FolderSimple },
          { to: "/workspaces", label: "Workspaces", icon: Buildings },
          { to: "/chat-insights", label: "Chat Insights", icon: ChatsCircle },
          { to: "/copilot", label: "Copilot", icon: Sparkle },
          { to: "/marketplace", label: "Marketplace", icon: Storefront },
          { to: "/migrations", label: "Migraciones", icon: Swap },
          { to: "/releases", label: "Releases", icon: Rocket },
          { to: "/training", label: "Training", icon: GraduationCap },
          { to: "/onboarding", label: "Onboarding", icon: Compass },
          { to: "/disaster-recovery", label: "Disaster Recovery", icon: Lifebuoy },
          { to: "/notifications", label: "Notificaciones", icon: Bell },
        ],
      },
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