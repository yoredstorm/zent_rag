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

const DATABASE_PHRASES = [
  "Conectando al catálogo real.",
  "Leyendo tablas y columnas.",
  "Buscando claves y relaciones.",
];

export function AnalysisProgressStep({
  headline,
  phases,
  technical,
  showTech,
  onToggleTech,
  onContinue,
  onRetry,
  ready,
  percent = 0,
  glimpses = [],
  files = [],
  status = null,
  kind = null,
  learningSessionId = null,
}: {
  headline: string;
  phases: Array<{ id: string; label: string; state: string }>;
  technical?: Record<string, unknown>;
  showTech: boolean;
  onToggleTech: () => void;
  onContinue: () => void;
  onRetry?: () => void;
  ready: boolean;
  percent?: number;
  glimpses?: AnalyzeGlimpse[];
  files?: ProgressFile[];
  status?: string | null;
  kind?: string | null;
  learningSessionId?: string | null;
}) {
  const pages =
    typeof technical?.pages === "number" ? ` (${String(technical.pages)} páginas)` : "";
  const visibleGlimpses = glimpses.slice(0, 12);
  const [idleIdx, setIdleIdx] = useState(0);
  const progress = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  const jobStatus = String(technical?.job_status ?? status ?? "").toLowerCase();
  const failed =
    jobStatus === "failed" ||
    jobStatus === "dead" ||
    String(technical?.catalog_phase ?? "").toUpperCase() === "FAILED" ||
    String(status ?? "").toUpperCase() === "FAILED";
  const catalogPhase = String(technical?.catalog_phase ?? "");
  const stalled = Boolean(technical?.stalled);
  const errorMessage = String(
    technical?.job_error ?? technical?.catalog_error ?? ""
  ).trim();
  const errorHint = String(technical?.error_hint ?? "").trim();
  const processed = Number(technical?.records_processed ?? 0);
  const phrases = kind === "database" ? DATABASE_PHRASES : IDLE_PHRASES;

  useEffect(() => {
    if (ready || visibleGlimpses.length) return;
    const id = window.setInterval(() => {
      setIdleIdx((i) => (i + 1) % phrases.length);
    }, 2000);
    return () => window.clearInterval(id);
  }, [ready, visibleGlimpses.length, phrases.length]);

  const live = ready
    ? "Ya entendí lo suficiente. Revisa cuando quieras."
    : visibleGlimpses.length
      ? visibleGlimpses[visibleGlimpses.length - 1].text
      : phrases[idleIdx];

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
          {failed
            ? "La ingesta no terminó"
            : stalled
              ? "La ingesta está sin avance"
              : ready
                ? "Listo para revisar"
                : "En proceso"}
        </p>
        {failed ? (
          <div className="mt-1 space-y-2 text-xs leading-relaxed" role="alert">
            <p className="text-danger">
              {errorMessage ||
                "El job falló. Revisa la conexión y vuelve a intentar."}
            </p>
            {errorHint && <p className="text-muted">{errorHint}</p>}
            {onRetry && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={onRetry}
                data-testid="analyze-retry"
              >
                Reintentar análisis
              </button>
            )}
          </div>
        ) : stalled ? (
          <div className="mt-1 space-y-2 text-xs leading-relaxed">
            <p className="text-warning">
              El job no reporta avance reciente. Puedes esperar o reintentar.
            </p>
            {onRetry && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={onRetry}
                data-testid="analyze-retry"
              >
                Reintentar análisis
              </button>
            )}
          </div>
        ) : (
          <>
            {percent > 0 && (
              <div className="mt-2">
                <div className="flex items-center justify-between text-xs text-muted">
                  <span data-testid="analyze-percent">{progress}%</span>
                  {catalogPhase && <span>{catalogPhase}</span>}
                </div>
                <div
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-border"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                  aria-label="Avance de la ingesta"
                >
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-500"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
            <p className="mt-1 text-xs leading-relaxed text-muted">
              {ready
                ? "El procesamiento terminó. Revisa lo encontrado antes de continuar."
                : percent > 0
                  ? `Avance real del job${processed > 0 ? ` · ${processed} registros` : ""}.`
                  : "Conectando y preparando la lectura. Las fases de abajo son señales reales."}
            </p>
          </>
        )}
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
