/**
 * Catálogo de nodos backend (GET /api/v1/workflows/node-catalog) → NodeMeta.
 *
 * El backend es la fuente de verdad del catálogo; `NODE_LIBRARY` local queda
 * como fallback cuando el endpoint no está disponible (Fase 5). Los tipos
 * visuales (icono/color/summary/defaults) se conservan del registry local.
 */
import {
  NODE_LIBRARY,
  type FieldDef,
  type NodeCategory,
  type NodeMeta,
  type PortDef,
} from "./workflowGraph";

export type CatalogParameter = {
  key: string;
  label: string;
  description?: string | null;
  type?: string;
  required?: boolean;
  default?: unknown;
  placeholder?: string | null;
  examples?: unknown[];
  advanced?: boolean;
  min_level?: "simple" | "guided" | "advanced";
  secret?: boolean;
  validation?: { options?: { value: string; label: string }[] } | null;
  dynamic_options?: string | null;
  data_source?: string | null;
};

export type CatalogPort = { type?: string };

export type CatalogNode = {
  node_type: string;
  version?: number;
  label?: string;
  business_name?: string;
  short_description?: string;
  long_description?: string;
  category?: string;
  risk_level?: string;
  capabilities?: string[];
  inputs?: Record<string, CatalogPort>;
  outputs?: Record<string, CatalogPort>;
  context_reads?: string[];
  context_writes?: string[];
  requires?: string[];
  optional_dependencies?: string[];
  supports_simulation?: boolean;
  supports_agent?: boolean;
  supports_knowledge?: boolean;
  when_to_use?: string[];
  when_not_to_use?: string[];
  examples?: unknown[];
  parameters?: CatalogParameter[];
  output_fields?: unknown[];
  available?: boolean;
  unavailable_reason?: string | null;
};

export type CatalogCategory = { id: string; label: string; order: number };

export type NodeCatalogPayload = {
  catalog_version: number;
  generated_at: string;
  categories: CatalogCategory[];
  nodes: CatalogNode[];
};

const FALLBACK_INPUT: PortDef[] = [{ name: "in", type: "json" }];
const FALLBACK_OUTPUT: PortDef[] = [{ name: "out", type: "json" }];

const FIELD_TYPE_MAP: Record<string, FieldDef["type"]> = {
  textarea: "textarea",
  json: "json",
  number: "number",
  integer: "number",
  money: "number",
  percentage: "number",
  boolean: "select",
  enum: "select",
  select: "select",
};

const RISK_LEVELS = ["info", "normal", "elevated", "critical"] as const;

function localPorts(local: NodeMeta | undefined, side: "input" | "output"): PortDef[] {
  const raw = local?.ports?.[side];
  if (!raw || raw.length === 0) return side === "input" ? FALLBACK_INPUT : FALLBACK_OUTPUT;
  return raw.map((port) => (typeof port === "string" ? { name: port, type: "json" } : port));
}

function portsFrom(
  raw: Record<string, CatalogPort> | undefined,
  fallback: PortDef[]
): PortDef[] {
  const entries = Object.entries(raw ?? {});
  if (entries.length === 0) return fallback;
  return entries.map(([name, port]) => ({ name, type: port?.type ?? "json" }));
}

export function parameterToField(parameter: CatalogParameter): FieldDef {
  const declared = String(parameter.type ?? "text");
  const fieldType = FIELD_TYPE_MAP[declared] ?? "text";
  const options =
    fieldType === "select"
      ? declared === "boolean"
        ? [
            { value: "true", label: "Sí" },
            { value: "false", label: "No" },
          ]
        : parameter.validation?.options ?? []
      : undefined;
  const defaultValue = parameter.default;
  return {
    key: parameter.key,
    label: parameter.label,
    type: fieldType,
    placeholder: parameter.placeholder ?? undefined,
    options,
    default:
      typeof defaultValue === "string" || typeof defaultValue === "number"
        ? defaultValue
        : undefined,
    refs:
      Boolean(parameter.data_source) ||
      ["text", "textarea", "json", "data_reference"].includes(declared),
    adv: Boolean(parameter.advanced) || parameter.min_level === "advanced",
  };
}

export function catalogNodeToMeta(node: CatalogNode): NodeMeta {
  const local = NODE_LIBRARY[node.node_type];
  const parameters = node.parameters ?? [];
  const category = String(local?.category ?? node.category ?? "data") as NodeCategory;
  const risk = String(node.risk_level ?? "") as (typeof RISK_LEVELS)[number];
  return {
    type: node.node_type,
    category,
    label: node.business_name || node.label || local?.label || node.node_type,
    icon: local?.icon ?? "◆",
    color: local?.color ?? "bg-faint",
    ports: {
      input: portsFrom(node.inputs, localPorts(local, "input")),
      output: portsFrom(node.outputs, localPorts(local, "output")),
    },
    fields: parameters.length > 0 ? parameters.map(parameterToField) : local?.fields ?? [],
    defaults: local?.defaults,
    summary: local?.summary,
    risk: RISK_LEVELS.includes(risk) ? risk : local?.risk,
    description: node.short_description ?? undefined,
    available: node.available,
    unavailableReason: node.unavailable_reason ?? null,
    contextReads: node.context_reads ?? [],
    contextWrites: node.context_writes ?? [],
    requires: node.requires ?? [],
  };
}

export function catalogIndex(
  payload: NodeCatalogPayload | null | undefined
): Record<string, NodeMeta> {
  const index: Record<string, NodeMeta> = {};
  for (const node of payload?.nodes ?? []) {
    if (!node || !node.node_type) continue;
    index[node.node_type] = catalogNodeToMeta(node);
  }
  return index;
}

/** Labels de categoría del backend (el portal mantiene colores locales). */
export function catalogCategoryLabels(
  payload: NodeCatalogPayload | null | undefined
): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const category of payload?.categories ?? []) {
    if (category?.id && category?.label) labels[category.id] = category.label;
  }
  return labels;
}

/** Une el catálogo backend con el fallback local (backend gana por tipo). */
export function libraryWithCatalog(
  payload: NodeCatalogPayload | null | undefined,
  fallback: Record<string, NodeMeta> = NODE_LIBRARY
): Record<string, NodeMeta> {
  return { ...fallback, ...catalogIndex(payload) };
}

export type CatalogFetcher = <T>(path: string) => Promise<T>;

const CACHE_TTL_MS = 60_000;
let catalogCache: { key: string; payload: NodeCatalogPayload; at: number } | null = null;

export function clearNodeCatalogCache(): void {
  catalogCache = null;
}

export async function fetchNodeCatalog(
  fetcher: CatalogFetcher,
  cacheKey: string
): Promise<NodeCatalogPayload | null> {
  const now = Date.now();
  if (catalogCache && catalogCache.key === cacheKey && now - catalogCache.at < CACHE_TTL_MS) {
    return catalogCache.payload;
  }
  try {
    const payload = await fetcher<NodeCatalogPayload>("/api/v1/workflows/node-catalog");
    if (!payload || !Array.isArray(payload.nodes)) return null;
    catalogCache = { key: cacheKey, payload, at: now };
    return payload;
  } catch {
    return null;
  }
}
