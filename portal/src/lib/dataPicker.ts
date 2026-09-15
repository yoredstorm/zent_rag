/**
 * Data Picker — construye las fuentes de datos visibles para el usuario a
 * partir del grafo real: contrato de salida del nodo (backend) + sample del
 * último run (Live Preview). Nunca inventa datos: sin sample, solo se muestran
 * los campos declarados.
 */
import type { BusinessOutputField, NodeBusinessSchema } from "./businessSchema";
import type { WorkflowGraph } from "./workflowGraph";
import { nodeMeta } from "./workflowGraph";

export type DataFieldOption = {
  key: string;
  label: string;
  /** Referencia técnica que se escribe en el config. */
  ref: string;
  type: string;
  sample?: unknown;
};

export type DataSourceOption = {
  id: string;
  label: string;
  kind: "trigger" | "node";
  fields: DataFieldOption[];
};

export type NodeSamples = {
  trigger_payload?: Record<string, unknown>;
  nodes?: Record<string, { node_type?: string; status?: string; output?: Record<string, unknown> }>;
};

/** Catálogo backend de datos (`GET /workflows/{id}/data-catalog`). */
export type DataCatalogField = {
  key: string;
  label: string;
  ref: string;
  type?: string;
  sample?: unknown;
};

export type DataCatalogSource = {
  id: string;
  label: string;
  kind: "trigger" | "node";
  node_type?: string;
  fields?: DataCatalogField[];
  context_writes?: string[];
};

export type DataCatalogPayload = {
  workflow_id: string;
  run_id?: string | null;
  sources: DataCatalogSource[];
};

const TRIGGER_DEFAULTS: DataFieldOption[] = [
  { key: "message", label: "Mensaje recibido", ref: "{{trigger.message}}", type: "text" },
  { key: "query", label: "Consulta recibida", ref: "{{trigger.query}}", type: "text" },
];

function humanize(key: string): string {
  const text = key.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key;
}

function samplePreview(value: unknown): unknown {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "object") return undefined;
  return value;
}

function fieldsFromSample(
  output: Record<string, unknown>,
  nodeId: string,
  declared: Set<string>,
): DataFieldOption[] {
  const fields: DataFieldOption[] = [];
  for (const [key, value] of Object.entries(output)) {
    if (Array.isArray(value) && value.length > 0 && value[0] && typeof value[0] === "object" && !Array.isArray(value[0])) {
      const first = value[0] as Record<string, unknown>;
      for (const [childKey, childValue] of Object.entries(first)) {
        fields.push({
          key: `rows.0.${childKey}`,
          label: humanize(childKey),
          ref: `{{nodes.${nodeId}.output.${key}.0.${childKey}}}`,
          type: typeof childValue === "number" ? "number" : typeof childValue === "boolean" ? "boolean" : "text",
          sample: samplePreview(childValue),
        });
      }
      continue;
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
        fields.push({
          key: `${key}.${childKey}`,
          label: humanize(childKey),
          ref: `{{nodes.${nodeId}.output.${key}.${childKey}}}`,
          type: typeof childValue === "number" ? "number" : typeof childValue === "boolean" ? "boolean" : "text",
          sample: samplePreview(childValue),
        });
      }
      continue;
    }
    if (declared.has(key)) continue;
    fields.push({
      key,
      label: humanize(key),
      ref: `{{nodes.${nodeId}.output.${key}}}`,
      type: typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "text",
      sample: samplePreview(value),
    });
  }
  return fields;
}

function fieldsFromContract(
  outputs: BusinessOutputField[],
  nodeId: string,
  sample: Record<string, unknown> | undefined,
): DataFieldOption[] {
  return outputs.map((field) => ({
    key: field.key,
    label: field.label,
    ref: `{{nodes.${nodeId}.output.${field.key}}}`,
    type: field.type,
    sample: sample ? samplePreview(sample[field.key]) : (field.sample ?? field.example ?? undefined),
  }));
}

export function buildDataSources(
  graph: WorkflowGraph | null,
  schemas: Record<string, NodeBusinessSchema> | null,
  samples: NodeSamples | null,
  excludeNodeId?: string | null,
): DataSourceOption[] {
  if (!graph) return [];
  const payload = samples?.trigger_payload ?? {};
  const triggerFields: DataFieldOption[] = [
    ...TRIGGER_DEFAULTS.map((f) => ({ ...f, sample: samplePreview(payload[f.key]) })),
  ];
  for (const [key, value] of Object.entries(payload)) {
    if (key.startsWith("_")) continue;
    if (TRIGGER_DEFAULTS.some((f) => f.key === key)) continue;
    if (value !== null && typeof value === "object") continue;
    triggerFields.push({
      key,
      label: humanize(key),
      ref: `{{trigger.${key}}}`,
      type: typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "text",
      sample: samplePreview(value),
    });
  }
  const sources: DataSourceOption[] = [
    { id: "trigger", label: "Cuando ocurre el evento", kind: "trigger", fields: triggerFields },
  ];

  for (const node of graph.nodes) {
    if (node.id === excludeNodeId) continue;
    if (node.type.startsWith("trigger_") || node.type === "end") continue;
    const output = samples?.nodes?.[node.id]?.output;
    const schema = schemas?.[node.type];
    const declared = new Set((schema?.outputs ?? []).map((f) => f.key));
    const label = node.label || nodeMeta(node.type).label;
    const fields = [
      ...fieldsFromContract(schema?.outputs ?? [], node.id, output),
      ...(output ? fieldsFromSample(output, node.id, declared) : []),
    ];
    if (fields.length === 0 && !output) continue;
    sources.push({ id: node.id, label, kind: "node", fields });
  }
  return sources;
}

/** Normaliza el catálogo backend al shape del Data Picker. */
export function dataSourcesFromCatalog(
  payload: DataCatalogPayload | null | undefined,
  excludeNodeId?: string | null,
): DataSourceOption[] {
  if (!payload?.sources?.length) return [];
  const sources: DataSourceOption[] = [];
  for (const source of payload.sources) {
    if (source.kind === "node" && source.id === excludeNodeId) continue;
    const fields = (source.fields ?? []).map((field) => ({
      key: field.key,
      label: field.label,
      ref: field.ref,
      type: field.type ?? "text",
      sample: samplePreview(field.sample),
    }));
    if (fields.length === 0 && source.kind !== "trigger") continue;
    sources.push({ id: source.id, label: source.label, kind: source.kind, fields });
  }
  return sources;
}
