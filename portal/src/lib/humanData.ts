/**
 * Representación humana de datos de workflow (Fase 1/2).
 * La UI muestra filas legibles; el JSON queda detrás de "Ver JSON".
 * Nada de valores inventados: solo formato.
 */

export type HumanRow = {
  key: string;
  label: string;
  value: unknown;
  kind: "scalar" | "object" | "array";
  summary: string;
};

const KEY_LABELS: Record<string, string> = {
  sent: "Enviado",
  channel: "Canal",
  title: "Título",
  message: "Mensaje",
  text: "Respuesta",
  answer: "Respuesta",
  query_id: "Consulta",
  result: "Resultado",
  status: "Estado",
  error: "Error",
  cost: "Costo",
  model: "Modelo",
  agent_id: "Agente",
  rows: "Resultados",
  columns: "Columnas",
  evidence: "Evidencia",
  before: "Antes",
  after: "Después",
  stock: "Stock",
  total: "Total",
  name: "Nombre",
  id: "ID",
  simulado: "Simulado",
  simulated: "Simulado",
  retrieved_at: "Obtenido",
  source: "Fuente",
};

export function humanizeKey(key: string): string {
  const raw = String(key ?? "");
  if (KEY_LABELS[raw]) return KEY_LABELS[raw];
  const spaced = raw.replace(/[_-]+/g, " ").trim();
  if (!spaced) return raw;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString("es-PE") : value.toLocaleString("es-PE", { maximumFractionDigits: 4 });
  }
  if (typeof value === "string") {
    const dateOnly = value.match(DATE_ONLY_RE);
    if (dateOnly) return `${dateOnly[3]}/${dateOnly[2]}/${dateOnly[1]}`;
    return value;
  }
  return String(value);
}

export function summarizeValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length === 1 ? "1 elemento" : `${value.length.toLocaleString("es-PE")} elementos`;
  }
  if (value && typeof value === "object") {
    const size = Object.keys(value as Record<string, unknown>).length;
    return size === 1 ? "1 campo" : `${size} campos`;
  }
  return formatScalar(value);
}

export function valueKind(value: unknown): HumanRow["kind"] {
  if (Array.isArray(value)) return "array";
  if (value !== null && typeof value === "object") return "object";
  return "scalar";
}

export function toHumanRows(data: unknown): HumanRow[] {
  if (!data || typeof data !== "object" || Array.isArray(data)) return [];
  return Object.entries(data as Record<string, unknown>).map(([key, value]) => ({
    key,
    label: humanizeKey(key),
    value,
    kind: valueKind(value),
    summary: summarizeValue(value),
  }));
}

export type CompactTable = { columns: string[]; rows: string[][]; total: number };

/** Tabla compacta para arrays de objetos; null si no aplica. */
export function tableFromItems(items: unknown, maxRows = 20): CompactTable | null {
  if (!Array.isArray(items) || items.length === 0) return null;
  const objects = items.filter((item) => item && typeof item === "object" && !Array.isArray(item));
  if (objects.length !== items.length) return null;
  const columns = Array.from(
    new Set(objects.flatMap((item) => Object.keys(item as Record<string, unknown>))),
  ).slice(0, 8);
  const rows = objects
    .slice(0, maxRows)
    .map((item) => columns.map((column) => formatScalar((item as Record<string, unknown>)[column])));
  return { columns, rows, total: items.length };
}
