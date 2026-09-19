import {
  ArrowsLeftRight,
  BellSimple,
  BookOpen,
  Broadcast,
  Buildings,
  Cards,
  ChartBar,
  ChartLineUp,
  ChatText,
  Coins,
  Cpu,
  Flask,
  FlowArrow,
  Gauge,
  GitBranch,
  Globe,
  Handshake,
  Lifebuoy,
  Package,
  PiggyBank,
  Pulse,
  Robot,
  RocketLaunch,
  Scroll,
  ShieldCheck,
  ShieldWarning,
  Smiley,
  Storefront,
  TrendUp,
  UsersThree,
  Factory,
  type Icon,
} from "@phosphor-icons/react";

export type PlatformNavItem = { to: string; label: string; icon: Icon; end?: boolean };
export type PlatformNavGroup = { label: string; items: PlatformNavItem[] };

const BASE = "/control-center";

/** Labels en inglés (herramienta interna); la jerarquía visual la aplica el shell. */
export const PLATFORM_NAV: PlatformNavGroup[] = [
  {
    label: "Business",
    items: [
      { to: `${BASE}`, label: "Overview", icon: Gauge, end: true },
      { to: `${BASE}/tenants`, label: "Tenants", icon: Buildings },
      { to: `${BASE}/customers`, label: "Customers", icon: UsersThree },
      { to: `${BASE}/subscriptions`, label: "Subscriptions", icon: Cards },
      { to: `${BASE}/revenue`, label: "Revenue", icon: TrendUp },
      { to: `${BASE}/partners`, label: "Partners", icon: Handshake },
    ],
  },
  {
    label: "AI Platform",
    items: [
      { to: `${BASE}/model-gateway`, label: "Model Gateway", icon: Coins },
      { to: `${BASE}/decision-engine`, label: "Decision Engine", icon: FlowArrow },
      { to: `${BASE}/ai-runtime`, label: "AI Runtime", icon: Cpu },
      { to: `${BASE}/inference-proxy`, label: "Inference", icon: Cpu },
      { to: `${BASE}/knowledge-hub`, label: "Knowledge", icon: BookOpen },
      { to: `${BASE}/evals`, label: "Evals", icon: Flask },
      { to: `${BASE}/feedback`, label: "Feedback", icon: Smiley },
      { to: `${BASE}/workflows`, label: "Workflows", icon: FlowArrow },
      { to: `${BASE}/copilot`, label: "Copilot", icon: Robot },
    ],
  },
  {
    label: "Observability",
    items: [
      { to: `${BASE}/analytics`, label: "Analytics", icon: ChartBar },
      { to: `${BASE}/usage`, label: "Usage", icon: ChartLineUp },
      { to: `${BASE}/traces`, label: "Traces", icon: GitBranch },
      { to: `${BASE}/chat-insights`, label: "Chat Insights", icon: ChatText },
      { to: `${BASE}/model-health`, label: "Model Health", icon: Pulse },
      { to: `${BASE}/realtime`, label: "Real-Time", icon: Broadcast },
    ],
  },
  {
    label: "FinOps",
    items: [
      { to: `${BASE}/costs`, label: "AI Costs", icon: Coins },
      { to: `${BASE}/metering`, label: "Metering", icon: Gauge },
      { to: `${BASE}/cost-governance`, label: "Cost Governance", icon: PiggyBank },
      { to: `${BASE}/optimizer`, label: "Optimizer", icon: ChartLineUp },
      { to: `${BASE}/capacity`, label: "Capacity", icon: Gauge },
    ],
  },
  {
    label: "Trust",
    items: [
      { to: `${BASE}/trust`, label: "Trust Overview", icon: ShieldCheck },
      { to: `${BASE}/security-center`, label: "Security Center", icon: ShieldWarning },
      { to: `${BASE}/trust-safety`, label: "Trust & Safety", icon: ShieldWarning },
      { to: `${BASE}/risk-center`, label: "Risk Center", icon: ShieldWarning },
      { to: `${BASE}/governance`, label: "Governance", icon: ShieldCheck },
      { to: `${BASE}/compliance`, label: "Compliance", icon: ShieldCheck },
      { to: `${BASE}/audit`, label: "Audit", icon: Scroll },
      { to: `${BASE}/audit-intel`, label: "Audit Intelligence", icon: ShieldWarning },
    ],
  },
  {
    label: "Operations",
    items: [
      { to: `${BASE}/status`, label: "System Status", icon: Pulse },
      { to: `${BASE}/ops-center`, label: "Ops Center", icon: ShieldCheck },
      { to: `${BASE}/operations`, label: "Operations", icon: Gauge },
      { to: `${BASE}/regions`, label: "Regions", icon: Globe },
      { to: `${BASE}/dr`, label: "Disaster Recovery", icon: Lifebuoy },
      { to: `${BASE}/migrations`, label: "Migrations", icon: ArrowsLeftRight },
      { to: `${BASE}/releases`, label: "Releases", icon: GitBranch },
      { to: `${BASE}/data-export`, label: "Data Export", icon: Package },
    ],
  },
  {
    label: "Platform",
    items: [
      { to: `${BASE}/marketplace`, label: "Marketplace", icon: Storefront },
      { to: `${BASE}/marketplace-factory`, label: "Marketplace Factory", icon: Factory },
      { to: `${BASE}/ecosystem`, label: "Ecosystem", icon: Storefront },
      { to: `${BASE}/notifications`, label: "Notifications", icon: BellSimple },
      { to: `${BASE}/onboarding`, label: "Onboarding", icon: RocketLaunch },
      { to: `${BASE}/security`, label: "Security", icon: ShieldCheck },
      { to: `${BASE}/settings`, label: "Settings", icon: UsersThree },
    ],
  },
];

export function platformNavLeaves(): PlatformNavItem[] {
  return PLATFORM_NAV.flatMap((g) => g.items);
}

/** Grupo y hoja de navegación activos para una ruta del Control Center. */
export function platformNavContextForPath(
  pathname: string
): { group: PlatformNavGroup; item: PlatformNavItem } | null {
  for (const group of PLATFORM_NAV) {
    for (const item of group.items) {
      if (item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`)) {
        return { group, item };
      }
    }
  }
  return null;
}
