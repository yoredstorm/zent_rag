/**
 * Espejo portal de `src/platform/workflows/business_schema.py` y
 * `parameters.py`. El backend es la fuente de verdad de los formularios; este
 * módulo solo tipa y ayuda a renderizar (Simple / Guided / Advanced).
 */

export type ParameterLevel = "simple" | "guided" | "advanced";

export const LEVEL_LABELS: Record<ParameterLevel, string> = {
  simple: "Simple",
  guided: "Guiado",
  advanced: "Avanzado",
};

export const LEVEL_RANK: Record<ParameterLevel, number> = {
  simple: 0,
  guided: 1,
  advanced: 2,
};

export type BusinessParameter = {
  key: string;
  label: string;
  description?: string | null;
  type: string;
  required: boolean;
  default?: unknown;
  placeholder?: string | null;
  examples: unknown[];
  advanced: boolean;
  min_level: ParameterLevel;
  secret: boolean;
  dynamic_options?: string | null;
  data_source?: string | null;
  unit?: string | null;
  validation: Record<string, unknown>;
  help?: string | null;
  business_group?: string | null;
};

export type BusinessOutputField = {
  key: string;
  label: string;
  type: string;
  description?: string | null;
  example?: unknown;
  sample?: unknown;
  unit?: string | null;
  business_group?: string | null;
};

export type NodeBusinessSchema = {
  node_type: string;
  label: string;
  category: string;
  description?: string | null;
  risk_level: "info" | "normal" | "elevated" | "critical";
  parameters: BusinessParameter[];
  outputs: BusinessOutputField[];
};

export type OutputContract = {
  node_type: string;
  outputs: BusinessOutputField[];
  sample: Record<string, unknown>;
  source: "contract" | "sample" | "runtime";
};

export type NodeSchemasPayload = {
  schemas: NodeBusinessSchema[];
  output_contracts: Record<string, OutputContract>;
};

export type SelectOption = { value: string; label: string };

export function visibleParameters(
  parameters: BusinessParameter[],
  level: ParameterLevel,
  includeSecret = false,
): BusinessParameter[] {
  const rank = LEVEL_RANK[level] ?? 0;
  return parameters.filter((p) => {
    if (!includeSecret && p.secret) return false;
    return (LEVEL_RANK[p.min_level] ?? 0) <= rank;
  });
}

export function staticOptions(param: BusinessParameter): SelectOption[] {
  const raw = param.validation?.options;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((o): o is { value: unknown; label?: unknown } => !!o && typeof o === "object")
    .map((o) => ({ value: String(o.value), label: String(o.label ?? o.value) }));
}

export function isSelectType(param: BusinessParameter): boolean {
  return (
    param.type === "enum" ||
    param.type === "boolean" ||
    [
      "person",
      "team",
      "database",
      "table",
      "column",
      "field",
      "entity",
      "agent",
      "integration",
      "action",
      "template",
      "timezone",
    ].includes(param.type)
  );
}

export function getByPath(source: Record<string, unknown>, path: string): unknown {
  let cur: unknown = source;
  for (const part of path.split(".")) {
    if (cur && typeof cur === "object" && !Array.isArray(cur)) {
      cur = (cur as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return cur;
}

export function setByPath(
  source: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const parts = path.split(".");
  const clone = structuredClone(source);
  let cur: Record<string, unknown> = clone;
  for (const part of parts.slice(0, -1)) {
    const next = cur[part];
    if (!next || typeof next !== "object" || Array.isArray(next)) {
      cur[part] = {};
    }
    cur = cur[part] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
  return clone;
}

/** Valor a mostrar en un input controlado. */
export function toInputValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return "";
  return String(value);
}

/** Valor a persistir en config según el tipo del parámetro. */
export function fromInputValue(param: BusinessParameter, raw: string): unknown {
  if (param.type === "number" || param.type === "integer" || param.type === "money" || param.type === "percentage") {
    if (raw === "") return "";
    const num = Number(raw);
    return Number.isFinite(num) ? num : raw;
  }
  if (param.type === "boolean") {
    if (raw === "true") return true;
    if (raw === "false") return false;
    return raw;
  }
  return raw;
}

export function defaultFor(param: BusinessParameter): unknown {
  return param.default ?? "";
}
