import { useEffect, useState } from "react";
import { UploadQueueList } from "../../../components/UploadQueueList";
import { rowsFromJobFiles } from "../../../lib/uploadQueue";
import { WizardLearningPanel } from "../../../components/knowledgeSession/WizardLearningPanel";
import { WIZARD_STEP_HEADINGS, type ProgressFile } from "./types";
import type { AnalyzeGlimpse } from "./wizardUx";

const IDLE_PHRASES = [
  "Leyendo el archivo…",
  "Buscando nombres y fechas…",
  "Separando lo importante…",
];

export function AnalysisProgressStep({
  headline,
  phases,
  technical,
  showTech,
  onToggleTech,
  onContinue,
  ready,
  glimpses = [],
  files = [],
  learningSessionId = null,
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
  learningSessionId?: string | null;
}) {
  const pages =
    typeof technical?.pages === "number" ? ` (${String(technical.pages)} páginas)` : "";
  const visibleGlimpses = glimpses.slice(0, 12);
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
      <div
        className="mt-6 rounded-md border border-border bg-soft px-4 py-3"
        role="status"
        data-testid="analyze-ring"
      >
        <p className="text-sm font-medium text-text">
          {ready ? "Listo para revisar" : "En proceso"}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          {ready
            ? "El procesamiento terminó. Revisa lo encontrado antes de continuar."
            : "No mostramos un porcentaje: el backend no expone avance por etapas. Las fases de abajo reflejan señales reales."}
        </p>
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
      {learningSessionId && (
        <div className="mt-4">
          <WizardLearningPanel sessionId={learningSessionId} />
        </div>
      )}
      {files.length > 0 && (
        <UploadQueueList
          rows={rowsFromJobFiles(files)}
          testId="analyze-files"
          className="mt-5 max-w-xl"
        />
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
