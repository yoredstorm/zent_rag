import { useEffect, useState } from "react";
import { WIZARD_STEP_HEADINGS, type ProgressFile } from "./types";
import { analyzePercent, type AnalyzeGlimpse } from "./wizardUx";

const IDLE_PHRASES = [
  "Leyendo el archivo…",
  "Buscando nombres y fechas…",
  "Separando lo importante…",
];

function fileStatusLabel(file: ProgressFile): string {
  const status = file.job_status;
  if (status === "completed") return "Listo";
  if (status === "failed" || status === "dead") return "Error";
  if (typeof file.job_progress === "number") return `${file.job_progress}%`;
  if (status === "running") return "Indexando…";
  return "En cola";
}

export function AnalysisProgressStep({
  headline,
  phases,
  technical,
  showTech,
  onToggleTech,
  onContinue,
  ready,
  percent,
  glimpses = [],
  files = [],
  status,
}: {
  headline: string;
  phases: Array<{ id: string; label: string; state: string }>;
  technical?: Record<string, unknown>;
  showTech: boolean;
  onToggleTech: () => void;
  onContinue: () => void;
  ready: boolean;
  percent?: number;
  glimpses?: AnalyzeGlimpse[];
  files?: ProgressFile[];
  status?: string | null;
}) {
  const jobProgress =
    typeof technical?.job_progress === "number" ? (technical.job_progress as number) : null;
  const pages =
    typeof technical?.pages === "number" ? ` (${String(technical.pages)} páginas)` : "";
  const visibleGlimpses = glimpses.slice(0, 12);
  const displayPercent = ready
    ? 100
    : typeof percent === "number"
      ? percent
      : analyzePercent({ phases, status, jobProgress });
  const [idleIdx, setIdleIdx] = useState(0);

  useEffect(() => {
    if (ready || visibleGlimpses.length) return;
    const id = window.setInterval(() => {
      setIdleIdx((i) => (i + 1) % IDLE_PHRASES.length);
    }, 2000);
    return () => window.clearInterval(id);
  }, [ready, visibleGlimpses.length]);

  const live = ready
    ? "Ya entendí lo suficiente. Revisa cuando quieras."
    : visibleGlimpses.length
      ? visibleGlimpses[visibleGlimpses.length - 1].text
      : IDLE_PHRASES[idleIdx];

  return (
    <div className="max-w-xl">
      <h2 className="text-lg font-semibold text-text">{WIZARD_STEP_HEADINGS.analyze}</h2>
      <p className="mt-1 text-sm text-muted">
        {headline || "Zent está entendiendo tu fuente"}
      </p>
      <div className="mt-6 flex justify-center sm:justify-start">
        <div
          className="analyze-ring"
          role="progressbar"
          aria-label="Progreso del análisis"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={displayPercent}
          data-testid="analyze-ring"
          style={{ ["--p" as string]: displayPercent }}
        >
          <div className="analyze-ring-inner">{displayPercent}%</div>
        </div>
      </div>
      <p className="mt-3 text-sm text-text" aria-live="polite" data-testid="analyze-live">
        {live}
      </p>
      {visibleGlimpses.length > 0 && (
        <div className="analyze-cloud mt-4" data-testid="analyze-cloud">
          {visibleGlimpses.map((glimpse, index) => (
            <span
              key={glimpse.id}
              className="panel analyze-chip"
              style={{ animationDelay: `${index * 60}ms` }}
            >
              {glimpse.text}
            </span>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <ul className="mt-5 flex max-h-40 flex-col gap-1 overflow-y-auto text-xs" data-testid="analyze-files">
          {files.map((file) => (
            <li
              key={`${file.filename}-${file.job_id ?? ""}`}
              className="flex items-center justify-between gap-3"
            >
              <span className="min-w-0 truncate text-muted">{file.filename}</span>
              <span className="mono shrink-0 text-faint">{fileStatusLabel(file)}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="mt-6 space-y-1.5 text-xs text-faint">
        {phases.map((phase) => {
          const label =
            phase.id === "content" && pages && phase.state === "done"
              ? `${phase.label}${pages}`
              : phase.label;
          return (
            <li key={phase.id} className="flex items-center gap-2">
              <span aria-hidden>
                {phase.state === "done" ? "✓" : phase.state === "active" ? "◌" : "○"}
              </span>
              {label}
              {phase.state === "active" && <span>…</span>}
            </li>
          );
        })}
      </ul>
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
        className="btn btn-primary mt-5 min-h-11"
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
