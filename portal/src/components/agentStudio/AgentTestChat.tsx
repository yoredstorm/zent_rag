import { PaperPlaneRight, Play } from "@phosphor-icons/react";
import { FormEvent } from "react";
import { EmptyState, Spinner } from "../ui";
import type { KnowledgeSource } from "./types";

export type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  emptyHint?: boolean;
  error?: string;
};

export function AgentTestChat({
  turns,
  input,
  status,
  playing,
  inactive,
  disabledReason,
  sources,
  selectedIds,
  onInput,
  onSubmit,
  onActivate,
}: {
  turns: ChatTurn[];
  input: string;
  status: string;
  playing: boolean;
  inactive: boolean;
  disabledReason?: string;
  sources: KnowledgeSource[];
  selectedIds: string[];
  onInput: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onActivate?: () => void;
}) {
  const nameById = new Map(sources.map((s) => [s.id, s.name]));
  const waitingOnIndex = sources.some(
    (source) => selectedIds.includes(source.id) && !source.document_count,
  );

  return (
    <section className="flex h-full min-h-[22rem] flex-col rounded-md border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
          <Play size={15} className="text-accent" aria-hidden />
          Probar
        </h2>
        <p className="mt-0.5 text-xs text-muted">Habla con el agente. Ajusta propósito o fuentes y vuelve a preguntar.</p>
      </header>

      {waitingOnIndex && (
        <div className="border-b border-warn/30 bg-warn-soft px-4 py-3 text-sm text-text" role="status" data-testid="chat-wait-index">
          Espera a que termine el indexado; ahora mismo no hay nada que buscar.
        </div>
      )}
      {inactive && (
        <div className="border-b border-warn/30 bg-warn-soft px-4 py-3 text-sm text-text" role="status">
          Actívalo para probar.
          {onActivate && (
            <button type="button" className="btn btn-secondary ml-3 min-h-9 px-3 text-xs" onClick={onActivate}>
              Activar
            </button>
          )}
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {turns.length === 0 && (
          <EmptyState
            icon={Play}
            title="Haz una pregunta de prueba"
            body="El agente usa el propósito y las fuentes de la izquierda."
          />
        )}
        {turns.map((turn, index) => (
          <article
            key={`${turn.role}-${index}`}
            className={`rounded-md px-3 py-2.5 text-sm leading-relaxed ${
              turn.role === "user" ? "ml-8 bg-soft text-text" : "mr-4 border border-border bg-raised text-text"
            }`}
          >
            <p className="whitespace-pre-wrap">{turn.text}</p>
            {turn.role === "assistant" && (turn.sources?.length ?? 0) > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {turn.sources!.map((id) => (
                  <li key={id} className="badge badge-ok">
                    {nameById.get(id) || id.slice(0, 8)}
                  </li>
                ))}
              </ul>
            )}
            {turn.emptyHint && (
              <p className="mt-2 text-xs text-muted">
                No encontró nada en las fuentes elegidas. Prueba otra pregunta o revisa que estén indexadas.
              </p>
            )}
            {turn.error && <p className="mt-2 text-xs text-danger">{turn.error}</p>}
          </article>
        ))}
        {status && <p className="text-sm text-muted">{status}</p>}
      </div>

      <form className="flex gap-2 border-t border-border p-3" onSubmit={onSubmit}>
        <label className="block min-w-0 flex-1">
          <span className="sr-only">Pregunta de prueba</span>
          <input
            className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
            placeholder="Pregunta al agente…"
            value={input}
            onChange={(e) => onInput(e.target.value)}
            disabled={playing || inactive}
          />
        </label>
        <button
          className="btn btn-primary min-h-11"
          type="submit"
          disabled={playing || inactive || !input.trim() || Boolean(disabledReason)}
        >
          {playing ? <Spinner size={14} /> : <PaperPlaneRight size={15} aria-hidden />}
          Probar
        </button>
      </form>
      {disabledReason && <p className="px-3 pb-3 text-xs text-muted">{disabledReason}</p>}
    </section>
  );
}
