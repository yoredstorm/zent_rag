import { Link } from "react-router-dom";
import type { ReadyAction } from "./types";

const DEFAULT_ACTIONS: ReadyAction[] = [
  { label: "Pregúntale a Zent", to: "/chat" },
  { label: "Crear agente", to: "/agents/new" },
  { label: "Revisar mejoras", to: "/knowledge/improvements" },
];

export function ReadinessStep({
  overall,
  scores,
  labels,
  improvements,
  warning,
  readyHeadline,
  readySubtitle,
  readyActions,
}: {
  overall: number;
  scores: Record<string, number>;
  labels: Record<string, string>;
  improvements: string[];
  warning: string | null;
  readyHeadline?: string;
  readySubtitle?: string;
  readyActions?: ReadyAction[];
}) {
  const actions = readyActions && readyActions.length > 0 ? readyActions : DEFAULT_ACTIONS;
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-text" data-testid="ready-heading">
        {readyHeadline || "Tu conocimiento está listo."}
      </h2>
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