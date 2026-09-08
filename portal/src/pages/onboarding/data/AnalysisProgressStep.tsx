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
  return (
    <div className="max-w-xl">
      <h2 className="text-lg font-semibold text-text">{headline || "Zent está entendiendo tus datos"}</h2>
      <ul className="mt-5 space-y-2">
        {phases.map((phase) => (
          <li key={phase.id} className="flex items-center gap-2 text-sm">
            <span aria-hidden>
              {phase.state === "done" ? "✓" : phase.state === "active" ? "◌" : "○"}
            </span>
            {phase.label}
          </li>
        ))}
      </ul>
      <button type="button" className="mt-4 text-xs text-accent" onClick={onToggleTech}>
        {showTech ? "Ocultar detalles técnicos" : "Technical details"}
      </button>
      {showTech && technical && (
        <pre className="mt-2 overflow-auto rounded-md bg-soft p-3 text-[11px] text-muted">
          {JSON.stringify(technical, null, 2)}
        </pre>
      )}
      <button type="button" className="btn btn-primary mt-5" data-testid="analyze-continue" disabled={!ready} onClick={onContinue}>
        Continuar
      </button>
    </div>
  );
}
