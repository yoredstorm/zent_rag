// =============================================================================
// KnowledgeQuestionCard — pregunta de negocio con evidencia y respuesta (22)
// =============================================================================
import { Question, ThumbsDown, Clock } from "@phosphor-icons/react";
import { useState } from "react";
import {
  priorityTone,
  type KnowledgeQuestion,
} from "../../lib/knowledgeLearning";

const OTHER_VALUES = new Set(["other", "otro", "otra", "otros", "otras"]);

export type QuestionAnswerPayload = {
  answer: string;
  structured_answer: Record<string, unknown>;
  choice?: string;
};

function buildStructured(
  question: KnowledgeQuestion,
  choice: string,
  freeText: string,
  selectedValues: string[]
): QuestionAnswerPayload {
  const schema = question.answer_schema || {};
  const kind = String(schema.kind || "free_form");
  const isOther = OTHER_VALUES.has(choice.trim().toLowerCase());
  const meaning = isOther ? freeText.trim() : choice;

  if (kind === "enum_mapping") {
    const mapping: Record<string, string> = {};
    for (const value of selectedValues) mapping[value] = meaning;
    return { answer: meaning, structured_answer: { mapping }, choice };
  }
  if (kind === "role_choice") {
    return { answer: meaning, structured_answer: { role: choice }, choice };
  }
  if (kind === "boolean") {
    const field = String(schema.field || "value");
    if (choice === "partial") {
      return { answer: meaning, structured_answer: { [field]: "partial" }, choice };
    }
    const truthy = ["yes", "true", "1", "si", "sí"].includes(choice.toLowerCase());
    return { answer: meaning, structured_answer: { [field]: truthy }, choice };
  }
  return {
    answer: meaning,
    structured_answer: {
      concept: question.title.slice(0, 200),
      definition: meaning || freeText,
    },
    choice,
  };
}

export function KnowledgeQuestionCard({
  question,
  index,
  total,
  busy = false,
  onAnswer,
  onSkip,
  onDefer,
}: {
  question: KnowledgeQuestion;
  index: number;
  total: number;
  busy?: boolean;
  onAnswer: (payload: QuestionAnswerPayload) => void;
  onSkip: (reason: string) => void;
  onDefer: () => void;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const [freeText, setFreeText] = useState("");
  const enumValues: string[] = Array.isArray(question.answer_schema?.values)
    ? (question.answer_schema.values as unknown[]).map(String)
    : [];
  const [selectedValues, setSelectedValues] = useState<string[]>(
    enumValues.length ? enumValues : []
  );
  const confidencePct =
    question.confidence_before !== null
      ? Math.round((question.confidence_before ?? 0) * 100)
      : null;
  const impactKeys = Object.keys(question.impact || {});
  const isOther = choice !== null && OTHER_VALUES.has(choice.trim().toLowerCase());

  function toggleValue(value: string) {
    setSelectedValues((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    );
  }

  return (
    <article className="panel" data-testid="question-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`badge ${priorityTone(question.priority)}`}>
          {question.priority}
        </span>
        <span className="text-[11px] uppercase tracking-wide text-faint">
          Pregunta {index + 1} de {total}
        </span>
        {confidencePct !== null && (
          <span className="text-[11px] text-faint">
            Confianza antes de responder: {confidencePct}%
          </span>
        )}
        {impactKeys.length > 0 && (
          <span className="text-[11px] text-faint">
            Impacto: {impactKeys.join(", ")}
          </span>
        )}
      </div>

      <h3 className="mt-2 flex items-start gap-2 text-sm font-semibold text-text">
        <Question size={16} weight="fill" className="mt-0.5 shrink-0 text-accent" aria-hidden />
        {question.title}
      </h3>
      {question.body && (
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{question.body}</p>
      )}

      {question.evidence.length > 0 && (
        <div className="mt-3 rounded-md border border-border bg-soft/40 p-2.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">
            Zent encontró
          </p>
          <ul className="mt-1 space-y-0.5 text-[12px] text-muted">
            {question.evidence.slice(0, 6).map((item) => (
              <li key={item}>• {item}</li>
            ))}
          </ul>
        </div>
      )}

      {enumValues.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-faint">
            Valores detectados (selecciona a cuáles aplica tu respuesta):
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {enumValues.map((value) => {
              const option = question.options.find((item) => item.value === value);
              const selected = selectedValues.includes(value);
              return (
                <button
                  key={value}
                  type="button"
                  className={`btn min-h-7 px-2 py-0.5 text-[11px] ${
                    selected ? "btn-secondary" : "btn-ghost"
                  }`}
                  aria-pressed={selected}
                  onClick={() => toggleValue(value)}
                >
                  <span className="font-mono">{value}</span>
                  {typeof option?.occurrence_count === "number" &&
                    option.occurrence_count > 0 && (
                      <span className="ml-1 text-faint">
                        {option.occurrence_count.toLocaleString("es-PE")}
                      </span>
                    )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {question.options.length === 0 && (
          <p className="text-[12px] text-faint">
            Escribe la interpretación correcta para que Zent la recuerde.
          </p>
        )}
        {question.options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`btn min-h-8 px-3 text-[12px] ${
              choice === option.label ? "btn-primary" : "btn-secondary"
            }`}
            data-testid={`question-option-${option.value}`}
            aria-pressed={choice === option.label}
            disabled={busy}
            onClick={() => setChoice(option.label)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {(choice === null || isOther) && (
        <textarea
          className="field mt-3 min-h-16 w-full"
          placeholder="Respuesta para Zent (se guarda como conocimiento validado)"
          aria-label="Respuesta libre"
          value={freeText}
          onChange={(event) => setFreeText(event.target.value)}
        />
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn btn-primary min-h-9"
          data-testid="question-answer"
          disabled={busy || choice === null || (isOther && !freeText.trim())}
          onClick={() =>
            onAnswer(buildStructured(question, choice ?? "", freeText, selectedValues))
          }
        >
          Responder
        </button>
        <button
          type="button"
          className="btn btn-secondary min-h-9"
          data-testid="question-skip"
          disabled={busy}
          onClick={() => onSkip("no lo sé")}
        >
          <ThumbsDown size={14} aria-hidden />
          No lo sé
        </button>
        <button
          type="button"
          className="btn btn-ghost min-h-9"
          data-testid="question-defer"
          disabled={busy}
          onClick={onDefer}
        >
          <Clock size={14} aria-hidden />
          Preguntar después
        </button>
      </div>
    </article>
  );
}
