import type { Icon } from "@phosphor-icons/react";
import {
  ArrowClockwise,
  Briefcase,
  MagnifyingGlass,
  Package,
  Plus,
  Sparkle,
  Stack,
} from "@phosphor-icons/react";

/** Tipos compartidos del Marketplace global (un solo catálogo). */

export type ProductPricing = {
  model?: string;
  amount?: number;
  currency?: string;
  interval?: string;
  unit?: string;
};

export type MarketplaceProduct = {
  id: string;
  slug: string;
  name: string;
  short_description: string | null;
  long_description?: string | null;
  product_type: string;
  version: number;
  status: string;
  category: string;
  applies_to: string[];
  capabilities: string[];
  logo: string | null;
  certification: string | null;
  publisher: string | null;
  pricing: ProductPricing;
  published_at: string | null;
  updated_at?: string | null;
  included_assets?: { kind?: string; ref?: string; alias?: string }[];
  dependencies?: { kind?: string; ref?: string; requirement?: string }[];
  installation_flow?: { key?: string; question?: string }[];
  configuration_schema?: Record<string, unknown>;
  events?: string[];
  documentation?: string | null;
  support?: Record<string, unknown>;
  security?: Record<string, unknown>;
  privacy?: Record<string, unknown>;
  release_notes?: unknown[];
  countries?: string[];
  industries?: string[];
  screenshots?: string[];
  tags?: string[];
};

export type InstallHealthChild = {
  alias: string;
  install_id: string;
  slug?: string;
  name?: string;
  status: string;
  connected: boolean;
  needs_credentials?: boolean;
  needs_purpose?: boolean;
  last_used_at?: string | null;
};

export type ProductInstall = {
  id: string;
  product_id: string;
  product_version: number;
  status: string;
  readiness: string;
  health: {
    state?: string;
    children?: InstallHealthChild[];
    workflows?: number;
    agents?: number;
    last_used_at?: string | null;
  };
  last_used_at: string | null;
  update_available: boolean;
  latest_version: number;
  installed_assets: Record<string, string>;
  created_at: string;
  product: {
    slug: string;
    name: string;
    product_type: string;
    short_description: string | null;
    category: string;
    applies_to: string[];
    logo: string | null;
    status: string;
  };
};

export type CatalogFacets = {
  categories: { key: string; count: number }[];
  applies_to: { key: string; count: number }[];
  pricing_models: { key: string; count: number }[];
  product_types: { key: string; count: number }[];
};

export const TYPE_LABEL: Record<string, string> = {
  INTEGRATION: "Integración",
  WORKFLOW_TEMPLATE: "Workflow",
  AGENT_TEMPLATE: "Agente",
  INTELLIGENCE_PACK: "Intelligence Pack",
  BUSINESS_PACK: "Business Pack",
  SEMANTIC_PACK: "Semantic Pack",
  COMPOSITE_PACK: "Composite Pack",
};

export const TYPE_ICON: Record<string, Icon> = {
  INTEGRATION: Package,
  WORKFLOW_TEMPLATE: ArrowClockwise,
  AGENT_TEMPLATE: Plus,
  INTELLIGENCE_PACK: Sparkle,
  BUSINESS_PACK: Briefcase,
  SEMANTIC_PACK: MagnifyingGlass,
  COMPOSITE_PACK: Stack,
};

export const CATEGORY_LABEL: Record<string, string> = {
  sales: "Ventas",
  support: "Atención al cliente",
  finance: "Finanzas",
  payments: "Pagos",
  inventory: "Inventario",
  ecommerce: "Ecommerce",
  productivity: "Productividad",
  data: "Datos",
  intelligence: "Inteligencia",
  communication: "Comunicación",
  marketing: "Marketing",
  security: "Seguridad",
  operations: "Operaciones",
  development: "Desarrollo",
  erp_crm: "ERP / CRM",
  government: "Gobierno",
  demo: "Demo",
  other: "Otros",
};

export const SURFACE_LABEL: Record<string, string> = {
  AGENTS: "Agents",
  WORKFLOWS: "Workflows",
  KNOWLEDGE: "Knowledge",
  DATA: "Datos",
  INTEGRATIONS: "Integraciones",
  CHANNELS: "Canales",
  PAYMENTS: "Pagos",
  AUTOMATIONS: "Automatizaciones",
  ANALYTICS: "Analítica",
  ADMIN: "Admin",
};

export const READINESS_META: Record<
  string,
  { label: string; tone: "ok" | "warn" | "danger" | "info" | "neutral" }
> = {
  READY: { label: "Operativo", tone: "ok" },
  installed: { label: "Instalado", tone: "info" },
  NEEDS_CONFIGURATION: { label: "Requiere configuración", tone: "warn" },
  NEEDS_CREDENTIALS: { label: "Faltan credenciales", tone: "warn" },
  MISSING_DEPENDENCY: { label: "Falta una dependencia", tone: "danger" },
  INCOMPATIBLE: { label: "No compatible", tone: "danger" },
  DISABLED: { label: "Pausado", tone: "neutral" },
  ERROR: { label: "Con errores", tone: "danger" },
};

const CURRENCY_SYMBOL: Record<string, string> = { PEN: "S/", USD: "$", EUR: "€" };

/** Precio legible: nunca inventa montos; sin contrato → "A consultar". */
export function priceLabel(pricing: ProductPricing | undefined): string {
  const model = (pricing?.model || "").toUpperCase();
  const currency = CURRENCY_SYMBOL[(pricing?.currency || "").toUpperCase()] || pricing?.currency || "";
  const amount = typeof pricing?.amount === "number" ? pricing.amount : null;
  switch (model) {
    case "":
    case "FREE":
      return "Gratis";
    case "INCLUDED":
      return "Incluido";
    case "CONTACT_SALES":
    case "CUSTOM":
      return "A consultar";
    case "ONE_TIME":
      return amount === null ? "Pago único" : `${currency} ${amount} pago único`;
    case "SUBSCRIPTION": {
      const interval =
        (pricing?.interval || "MONTH").toUpperCase() === "YEAR" ? "año" : "mes";
      return amount === null ? `Suscripción / ${interval}` : `${currency} ${amount} / ${interval}`;
    }
    case "USAGE":
      return amount === null
        ? "Por uso"
        : `${currency} ${amount} / ${pricing?.unit || "uso"}`;
    case "PER_CALL":
    case "BYOC_NO_MARKUP":
    case "ZENT_MANAGED_MARKUP":
    case "MONTHLY":
    case "TIERED":
    case "USAGE_PLUS_BASE":
      return priceLabel(legacyPricingToContract(pricing));
    default:
      return "A consultar";
  }
}

function legacyPricingToContract(pricing: ProductPricing | undefined): ProductPricing {
  const model = (pricing?.model || "").toUpperCase();
  const amount = typeof pricing?.amount === "number" ? pricing.amount : null;
  if (model === "BYOC_NO_MARKUP") return { model: "INCLUDED" };
  if (model === "PER_CALL") {
    return amount === null
      ? { model: "CUSTOM" }
      : { model: "USAGE", amount, currency: pricing?.currency, unit: pricing?.unit || "llamada" };
  }
  if (model === "MONTHLY") {
    return amount === null
      ? { model: "CUSTOM" }
      : { model: "SUBSCRIPTION", amount, currency: pricing?.currency, interval: "MONTH" };
  }
  return { model: "CUSTOM" };
}

export function readinessMeta(readiness: string | undefined) {
  return READINESS_META[readiness || "installed"] ?? READINESS_META.installed;
}

export function relativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const diff = Date.now() - then;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "hace instantes";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  if (days < 30) return `hace ${days} d`;
  return new Date(iso).toLocaleDateString();
}
