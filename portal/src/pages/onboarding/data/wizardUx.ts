import type { Suggestion } from "./types";

const MAX_DIGEST = 6;
const MAX_CLAUSES = 2;

const ID_RE = /\b(dni|ruc|rut|correo|email|cuit|nit|cedula|cédula)\b/i;

export type DigestSplit = {
  highlights: Suggestion[];
  rest: Suggestion[];
};

function factType(item: Suggestion): string {
  return String(item.payload?.fact_type || "").toLowerCase();
}

function isIdentifier(item: Suggestion): boolean {
  if (factType(item) === "identifier") return true;
  const blob = `${item.title} ${String(item.payload?.key || "")}`;
  return ID_RE.test(blob);
}

function isDocumentFlow(suggestions: Suggestion[], flow?: string, kind?: string): boolean {
  if (flow === "documents" || kind === "document") return true;
  return suggestions.some((s) => s.type === "document_fact");
}

function documentRank(item: Suggestion): number {
  const type = factType(item);
  if (type === "party") return 0;
  if (type === "identifier" || isIdentifier(item)) return 1;
  if (type === "amount") return 2;
  if (type === "date") return 3;
  if (type === "clause") return 4;
  return 5;
}

function isUncertainMapping(item: Suggestion): boolean {
  if (item.confidence === "low") return true;
  if (Array.isArray(item.evidence) && item.evidence.length > 1) return true;
  return Boolean(item.payload?.uncertain);
}

function splitByIds(ordered: Suggestion[], max: number): DigestSplit {
  return {
    highlights: ordered.slice(0, max),
    rest: ordered.slice(max),
  };
}

export function selectDigestHighlights(
  suggestions: Suggestion[],
  opts?: { flow?: string; kind?: string; max?: number }
): DigestSplit {
  const max = opts?.max ?? MAX_DIGEST;
  if (!suggestions.length) {
    return { highlights: [], rest: [] };
  }

  if (!isDocumentFlow(suggestions, opts?.flow, opts?.kind)) {
    const uncertain = suggestions.filter(isUncertainMapping);
    const certain = suggestions.filter((s) => !isUncertainMapping(s));
    return splitByIds([...uncertain, ...certain], max);
  }

  const ranked = suggestions
    .map((item, index) => ({ item, index, rank: documentRank(item) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index);

  const highlights: Suggestion[] = [];
  const rest: Suggestion[] = [];
  let clauses = 0;

  for (const { item, rank } of ranked) {
    if (highlights.length >= max) {
      rest.push(item);
      continue;
    }
    if (rank === 4) {
      if (clauses >= MAX_CLAUSES) {
        rest.push(item);
        continue;
      }
      clauses += 1;
    }
    highlights.push(item);
  }

  const highlightIds = new Set(highlights.map((h) => h.id));
  const originalRest = suggestions.filter((s) => !highlightIds.has(s.id));
  return { highlights, rest: originalRest.length ? originalRest : rest };
}

export type AnalyzeGlimpse = { id: string; text: string };

const TERMINAL_ANALYZE = new Set(["REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION"]);
const MAX_GLIMPSES = 12;

export function analyzePercent(input: {
  phases: Array<{ id?: string; state: string }>;
  status?: string | null;
  jobProgress?: number | null;
}): number {
  if (input.status && TERMINAL_ANALYZE.has(input.status)) return 100;
  const total = input.phases.length;
  const done = input.phases.filter((p) => p.state === "done").length;
  const phasePct = total > 0 ? (done / total) * 100 : 0;
  const job = input.jobProgress;
  const raw =
    typeof job === "number" && Number.isFinite(job)
      ? (phasePct + Math.min(Math.max(job, 0), 100)) / 2
      : phasePct;
  const capped =
    (input.status === "ANALYZING" || input.status === "DISCOVERING") && typeof job !== "number"
      ? Math.min(raw, 90)
      : raw;
  return Math.round(Math.min(Math.max(capped, 0), 100));
}

function factGlimpse(fact: {
  fact_type?: string;
  key?: string;
  value?: string;
}, index: number): AnalyzeGlimpse | null {
  const key = String(fact.key || "").trim();
  const value = String(fact.value || "").trim();
  if (!value) return null;
  const type = String(fact.fact_type || "").toLowerCase();
  let text = value;
  if (type === "party" || type === "identifier") {
    text = key ? `Ah, ${key} es ${value}` : `Ah, ${value}`;
  } else if (type === "amount") {
    text = `Vi un monto: ${value}`;
  } else if (type === "date") {
    text = `Fecha: ${value}`;
  } else if (type === "clause") {
    text = value.length > 80 ? `${value.slice(0, 77)}…` : value;
  } else if (key) {
    text = `${key}: ${value}`;
  }
  return { id: `fact-${index}-${key || type}`, text };
}

export function buildAnalyzeGlimpses(understanding: {
  facts?: Array<{ fact_type?: string; key?: string; value?: string }>;
  likely_entity?: string;
  columns?: Array<{ physical_name?: string }>;
  entities?: Array<{ name?: string }>;
}): AnalyzeGlimpse[] {
  const out: AnalyzeGlimpse[] = [];
  const facts = understanding.facts || [];
  if (facts.length) {
    for (let i = 0; i < facts.length && out.length < MAX_GLIMPSES; i++) {
      const item = factGlimpse(facts[i], i);
      if (item) out.push(item);
    }
    return out;
  }
  const entity = String(understanding.likely_entity || "").trim();
  if (entity) out.push({ id: "entity", text: `Esto parece ${entity}` });
  for (const [i, name] of (understanding.entities || []).entries()) {
    const label = String(name.name || "").trim();
    if (!label || out.length >= MAX_GLIMPSES) continue;
    out.push({ id: `ent-${i}`, text: `Esto parece ${label}` });
  }
  for (const [i, col] of (understanding.columns || []).entries()) {
    const name = String(col.physical_name || "").trim();
    if (!name || out.length >= MAX_GLIMPSES) continue;
    out.push({ id: `col-${i}-${name}`, text: `Columna ${name}…` });
  }
  return out.slice(0, MAX_GLIMPSES);
}

export type AskEvidenceItem =
  | string
  | {
      evidence_id?: string;
      id?: string;
      type?: string;
      source_name?: string;
      title?: string;
      snippet?: string;
      content?: string;
      text?: string;
      excerpt?: string;
      page?: string | number | null;
    };

const EVIDENCE_KIND: Record<string, string> = {
  document_chunk: "documento",
  sql_result: "consulta",
  api_response: "API",
  tool_result: "herramienta",
  semantic_definition: "definición",
  approved_metric: "métrica",
  human_verified_context: "verificado",
};

function clipSnippet(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= 140) return compact;
  return `${compact.slice(0, 137)}…`;
}

function oneAskEvidence(item: AskEvidenceItem): string | null {
  if (typeof item === "string") {
    const text = item.trim();
    return text || null;
  }
  if (!item || typeof item !== "object") return null;
  const snippet = clipSnippet(
    String(item.snippet || item.content || item.text || item.excerpt || "")
  );
  const source = String(item.source_name || item.title || "").trim();
  const kind = EVIDENCE_KIND[String(item.type || "").toLowerCase()] || "";
  const page = item.page;
  const parts: string[] = [];
  if (source) parts.push(source);
  if (kind && !parts.some((p) => p.toLowerCase() === kind.toLowerCase())) {
    parts.push(kind);
  }
  if (page !== undefined && page !== null && String(page).trim()) {
    parts.push(`pág. ${page}`);
  }
  if (snippet) parts.push(snippet);
  return parts.length ? parts.join(" · ") : null;
}

export function formatAskEvidence(items?: AskEvidenceItem[] | null): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of items || []) {
    const label = oneAskEvidence(item);
    if (!label || seen.has(label)) continue;
    seen.add(label);
    out.push(label);
    if (out.length >= 8) break;
  }
  return out;
}
