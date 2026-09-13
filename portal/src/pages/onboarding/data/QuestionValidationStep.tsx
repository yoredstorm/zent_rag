import { useState } from "react";
import { Link } from "react-router-dom";
import { WIZARD_STEP_HEADINGS } from "./types";
import { formatAskEvidence, type AskEvidenceItem } from "./wizardUx";

export function QuestionValidationStep({
  questions,
  answer,
  onAsk,
  onFeedback,
  onSkip,
  busy,
  heading,
  subtitle,
  askError,
  activeQuestion,
}: {
  questions: Array<{ id: string; text: string }>;
  answer: {
    question?: string;
    answer?: string;
    method?: string;
    sql?: string | null;
    confidence?: string;
    evidence?: AskEvidenceItem[];
    understood?: boolean;
    sources?: Array<{ id?: string; title?: string | null }>;
  } | null;
  onAsk: (text: string) => void;
  onFeedback: (verdict: string, reason?: string) => void;
  onSkip: () => void;
  busy: boolean;
  heading?: string;
  subtitle?: string;
  askError?: string | null;
  activeQuestion?: string | null;
}) {
  const [custom, setCustom] = useState("");
  const pending = Boolean(answer && answer.understood === false);
  const retryText = answer?.question || activeQuestion || "";
  const evidenceLabels = formatAskEvidence(answer?.evidence);

  function submitCustom(e: React.FormEvent) {
    e.preventDefault();
    const text = custom.trim();
    if (!text || busy) return;
    onAsk(text);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-text">{WIZARD_STEP_HEADINGS.test}</h2>
      <p className="text-sm text-muted">
        {heading || subtitle || "Preguntas generadas a partir de tu fuente."}
      </p>
      {heading && subtitle && <p className="text-sm text-muted">{subtitle}</p>}
      <div className="flex flex-col gap-2">
        {questions.map((q) => (
          <button
            key={q.id}
            type="button"
            data-testid="generated-question"
            className={`btn btn-secondary justify-start text-left min-h-11 ${
              activeQuestion === q.text ? "ring-1 ring-accent" : ""
            }`}
            disabled={busy}
            onClick={() => onAsk(q.text)}
          >
            {q.text}
          </button>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={submitCustom}>
        <input
          className="input flex-1"
          data-testid="custom-question"
          placeholder="Pregunta lo que quieras"
          value={custom}
          disabled={busy}
          onChange={(e) => setCustom(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={busy}>
          Enviar
        </button>
      </form>
      {busy && (
        <div className="panel animate-pulse space-y-2 p-4" data-testid="ask-loading">
          <p className="text-sm text-muted">Zent está buscando…</p>
          <div className="h-3 rounded bg-soft" />
          <div className="h-3 w-2/3 rounded bg-soft" />
        </div>
      )}
      {askError && (
        <p className="text-sm text-danger" role="alert">
          {askError}
        </p>
      )}
      {!busy && answer && (
        <div className="panel space-y-2 p-4 text-sm">
          <p className="font-medium">{pending ? "Pendiente de indexar" : "Pregunta entendida"}</p>
          <p>{answer.answer}</p>
          {answer.method && <p className="text-xs text-faint">Método: {answer.method}</p>}
          {answer.sql && (
            <pre className="overflow-auto rounded-md bg-soft p-2 text-[11px]">{answer.sql}</pre>
          )}
          {answer.confidence && <p className="text-xs">Confianza: {answer.confidence}</p>}
          {answer.sources && answer.sources.length > 0 && (
            <p className="text-xs text-muted">
              Fuentes: {answer.sources.map((s) => s.title || s.id).join(", ")}
            </p>
          )}
          {evidenceLabels.length > 0 && (
            <div data-testid="ask-evidence">
              <p className="text-xs text-muted">Evidencia</p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted">
                {evidenceLabels.map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            </div>
          )}
          {pending ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => retryText && onAsk(retryText)}
            >
              Reintentar
            </button>
          ) : (
            <>
              <p className="pt-2 text-sm">¿Fue correcta la respuesta?</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn btn-primary" onClick={() => onFeedback("correct")}>
                  Sí
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onFeedback("incorrect", "wrong_field")}
                >
                  No
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onFeedback("needs_adjustment")}
                >
                  Necesita ajuste
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <button type="button" className="text-xs text-muted" onClick={onSkip}>
        Saltar preguntas
      </button>
      <p className="text-sm text-muted">
        Sigue midiendo el conocimiento en Mejora.{" "}
        <Link to="/knowledge/learning" className="text-accent underline">
          Abrir Mejora
        </Link>
      </p>
    </div>
  );
}
