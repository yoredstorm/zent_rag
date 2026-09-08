import { Link } from "react-router-dom";

export function ReadinessStep({
  overall,
  scores,
  labels,
  improvements,
  warning,
}: {
  overall: number;
  scores: Record<string, number>;
  labels: Record<string, string>;
  improvements: string[];
  warning: string | null;
}) {
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-text" data-testid="ready-heading">
        Your business knowledge is ready.
      </h2>
      <p className="text-sm text-muted">Connected sources, understood coverage and review items.</p>
      <p className="text-3xl font-semibold">{Math.round(overall)}%</p>
      <ul className="space-y-2 text-sm">
        {Object.entries(labels).map(([key, label]) => (
          <li key={key} className="flex justify-between">
            <span>{label}</span>
            <span>{Math.round(scores[key] ?? 0)}%</span>
          </li>
        ))}
      </ul>
      {warning && <p className="text-sm text-muted">{warning}</p>}
      {improvements.length > 0 && (
        <ul className="text-sm text-muted">
          {improvements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2 pt-2">
        <Link to="/chat" className="btn btn-primary">
          Ask Zent
        </Link>
        <Link to="/agents/new" className="btn btn-secondary">
          Build Agent
        </Link>
        <Link to="/knowledge/improvements" className="btn btn-secondary">
          Review Improvements
        </Link>
      </div>
    </div>
  );
}
