import { WIZARD_STEP_HEADINGS } from "./types";

export function AnalysisProgressStep({
  headline,
  phases,
  technical,
  showTech,
  onToggleTech,
  onContinue,
  ready,
}: {
  headline: string;
  phases: Array<{ id: string; label: string; state: string }>;
  technical?: Record<string, unknown>;
  showTech: boolean;
  onToggleTech: () => void;
  onContinue: () => void;
  ready: boolean;
}) {
  const progress =
    typeof technical?.job_progress === "number" ? (technical.job_progress as number) : null;
  const pages =
    typeof technical?.pages === "number" ? ` (${String(technical.pages)} páginas)` : "";

  return (
    <div className="max-w-xl">
      <h2 className="text-lg font-semibold text-text">{WIZARD_STEP_HEADINGS.analyze}</h2>
      <p className="mt-1 text-sm text-muted">
        {headline || "Zent está entendiendo tu fuente"}
      </p>
      <p className="mt-2 text-sm text-muted">
        {ready
          ? "Análisis listo. Continúa para revisar lo que entendió Zent."
          : "Zent sigue analizando. Continuar no avanza hasta que termine."}
      </p>
      <ul className="mt-5 space-y-2">
        {phases.map((phase) => {
          const label =
            phase.id === "content" && pages && phase.state === "done"
              ? `${phase.label}${pages}`
              : phase.label;
          return (
            <li key={phase.id} className="flex items-center gap-2 text-sm">
              <span aria-hidden>
                {phase.state === "done" ? "✓" : phase.state === "active" ? "◌" : "○"}
              </span>
              {label}
              {phase.state === "active" && <span className="text-xs text-faint">…</span>}
            </li>
          );
        })}
      </ul>
      {progress != null && (
        <div className="mt-4">
          <div className="h-1.5 w-full overflow-hidden rounded bg-soft">
            <div
              className="h-full rounded bg-accent transition-all duration-500"
              style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-faint">Indexación: {Math.round(progress)}%</p>
        </div>
      )}
      <button type="button" className="mt-4 text-xs text-accent" onClick={onToggleTech}>
        {showTech ? "Ocultar detalles técnicos" : "Detalles técnicos"}
      </button>
      {showTech && technical && (
        <pre className="mt-2 overflow-auto rounded-md bg-soft p-3 text-[11px] text-muted">
          {JSON.stringify(technical, null, 2)}
        </pre>
      )}
      <button
        type="button"
        className="btn btn-primary mt-5"
        data-testid="analyze-continue"
        disabled={!ready}
        onClick={() => {
          if (!ready) return;
          onContinue();
        }}
      >
        Continuar
      </button>
    </div>
  );
}