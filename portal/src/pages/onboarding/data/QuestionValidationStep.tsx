export function QuestionValidationStep({
  questions,
  answer,
  onAsk,
  onFeedback,
  onSkip,
  busy,
}: {
  questions: Array<{ id: string; text: string }>;
  answer: {
    question?: string;
    answer?: string;
    method?: string;
    sql?: string | null;
    confidence?: string;
    evidence?: string[];
    understood?: boolean;
    sources?: Array<{ id?: string; title?: string | null }>;
  } | null;
  onAsk: (text: string) => void;
  onFeedback: (verdict: string, reason?: string) => void;
  onSkip: () => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-text">Prueba Zent</h2>
      <p className="text-sm text-muted">Preguntas generadas a partir de tus datos.</p>
      <div className="flex flex-col gap-2">
        {questions.map((q) => (
          <button
            key={q.id}
            type="button"
            data-testid="generated-question"
            className="btn btn-secondary justify-start text-left"
            disabled={busy}
            onClick={() => onAsk(q.text)}
          >
            {q.text}
          </button>
        ))}
      </div>
      {answer && (
        <div className="panel space-y-2 p-4 text-sm">
          <p className="font-medium">{answer.understood === false ? "Pendiente de indexar" : "Pregunta entendida"}</p>
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
          {answer.evidence && answer.evidence.length > 0 && (
            <p className="text-xs text-muted">Evidencia: {answer.evidence.join(" · ")}</p>
          )}
          <p className="pt-2 text-sm">¿Fue correcta la respuesta?</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary" onClick={() => onFeedback("correct")}>
              Sí
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => onFeedback("incorrect", "wrong_field")}>
              No
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => onFeedback("needs_adjustment")}>
              Necesita ajuste
            </button>
          </div>
        </div>
      )}
      <button type="button" className="text-xs text-muted" onClick={onSkip}>
        Saltar preguntas
      </button>
    </div>
  );
}
