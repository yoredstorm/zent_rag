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
  type Icon,
} from "@phosphor-icons/react";

export type PlatformNavItem = { to: string; label: string; icon: Icon; end?: boolean };
export type PlatformNavGroup = { label: string; items: PlatformNavItem[] };

const BASE = "/control-center";

export const PLATFORM_NAV: PlatformNavGroup[] = [
  {
    label: "BUSINESS",
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
    label: "AI PLATFORM",
    items: [
      { to: `${BASE}/model-gateway`, label: "Model Gateway", icon: Coins },
      { to: `${BASE}/inference-proxy`, label: "Inference", icon: Cpu },
      { to: `${BASE}/knowledge-hub`, label: "Knowledge", icon: BookOpen },
      { to: `${BASE}/evals`, label: "Evals", icon: Flask },
      { to: `${BASE}/feedback`, label: "Feedback", icon: Smiley },
      { to: `${BASE}/workflows`, label: "Workflows", icon: FlowArrow },
      { to: `${BASE}/copilot`, label: "Copilot", icon: Robot },
    ],
  },
  {
    label: "OBSERVABILITY",
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
    label: "FINOPS",
    items: [
      { to: `${BASE}/costs`, label: "AI Costs", icon: Coins },
      { to: `${BASE}/metering`, label: "Metering", icon: Gauge },
      { to: `${BASE}/cost-governance`, label: "Cost Governance", icon: PiggyBank },
      { to: `${BASE}/optimizer`, label: "Optimizer", icon: ChartLineUp },
      { to: `${BASE}/capacity`, label: "Capacity", icon: Gauge },
    ],
  },
  {
    label: "TRUST",
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
    label: "OPERATIONS",
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
    label: "PLATFORM",
    items: [
      { to: `${BASE}/marketplace`, label: "Marketplace", icon: Storefront },
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