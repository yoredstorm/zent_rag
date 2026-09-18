import { Link } from "react-router-dom";
import { WIZARD_STEP_HEADINGS, type ReadyAction } from "./types";

const PILLAR_ACTIONS: ReadyAction[] = [
  { label: "Abrir Semántica", to: "/knowledge/glossary" },
  { label: "Abrir Mejora", to: "/knowledge/learning" },
];

const DEFAULT_ACTIONS: ReadyAction[] = [
  { label: "Pregúntale a Zent", to: "/chat" },
  { label: "Crear agente", to: "/agents/new" },
];

export type TabularReadiness = {
  workbooks: number;
  tables: number;
  columns: number;
  rows: number;
  relations: number;
  indexing: string;
  quality_score: number | null;
};

export function ReadinessStep({
  overall,
  scores,
  labels,
  improvements,
  warning,
  readyHeadline,
  readySubtitle,
  readyActions,
  tabular,
}: {
  overall: number;
  scores: Record<string, number>;
  labels: Record<string, string>;
  improvements: string[];
  warning: string | null;
  readyHeadline?: string;
  readySubtitle?: string;
  readyActions?: ReadyAction[];
  tabular?: TabularReadiness | null;
}) {
  const extras = readyActions && readyActions.length > 0 ? readyActions : DEFAULT_ACTIONS;
  const seen = new Set<string>();
  const actions = [...PILLAR_ACTIONS, ...extras].filter((action) => {
    const key = `${action.to}|${action.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-text" data-testid="ready-heading">
        {WIZARD_STEP_HEADINGS.ready}
      </h2>
      <p className="text-sm text-muted">
        {readyHeadline || "Tu conocimiento está listo."}
      </p>
      <p className="text-sm text-muted">
        {readySubtitle || "Conectado, entendido y listo para preguntar."}
      </p>
      <p className="text-3xl font-semibold">{Math.round(overall)}%</p>
      <ul className="space-y-2 text-sm">
        {Object.entries(labels).map(([key, label]) => (
          <li key={key} className="flex justify-between">
            <span>{label}</span>
            <span>{Math.round(scores[key] ?? 0)}%</span>
          </li>
        ))}
      </ul>
      {warning && <p className="text-sm text-warn">{warning}</p>}
      {tabular && (
        <div
          className="rounded-lg border border-border-soft p-3 text-sm"
          data-testid="tabular-structure"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-text">Estructura detectada</span>
            <span
              className={
                tabular.indexing === "completed" ? "text-ok" : "text-warn"
              }
            >
              {tabular.indexing === "completed" ? "Indexado" : "En análisis"}
            </span>
          </div>
          <ul className="mt-2 space-y-1 text-muted">
            <li>
              {tabular.tables} tabla(s) · {tabular.columns} columnas ·{" "}
              {tabular.rows.toLocaleString()} filas
            </li>
            <li>
              {tabular.workbooks} archivo(s)
              {tabular.quality_score !== null
                ? ` · calidad ${Math.round(tabular.quality_score * 100)}%`
                : ""}
              {tabular.relations > 0
                ? ` · ${tabular.relations} relación(es) candidata(s)`
                : ""}
            </li>
          </ul>
        </div>
      )}
      {improvements.length > 0 && (
        <ul className="text-sm text-muted">
          {improvements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2 pt-2">
        {actions.map((action) => (
          <Link key={action.to + action.label} to={action.to} className="btn btn-primary">
            {action.label}
          </Link>
        ))}
      </div>
    </div>
  );
}