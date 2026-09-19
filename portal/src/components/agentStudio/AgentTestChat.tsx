import { PaperPlaneRight, Play } from "@phosphor-icons/react";
import {
  FormEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Session } from "../../api";
import FlowDrawer from "../../pages/chat/FlowDrawer";
import { Button, EmptyState, Panel, PanelHeader, Textarea } from "../ui";
import type { KnowledgeSource } from "./types";

export type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  emptyHint?: boolean;
  error?: string;
  flow?: Record<string, unknown> | null;
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
  session,
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
  session?: Session | null;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [flowFor, setFlowFor] = useState<ChatTurn | null>(null);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; turn: ChatTurn } | null>(
    null,
  );
  const nameById = new Map(sources.map((s) => [s.id, s.name]));
  const waitingOnIndex = sources.some(
    (source) => selectedIds.includes(source.id) && !source.document_count,
  );
  const blocked = playing || inactive || !input.trim() || Boolean(disabledReason);

  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [ctxMenu]);

  function handleContextMenu(event: ReactMouseEvent, turn: ChatTurn) {
    if (turn.role !== "assistant") return;
    if (!turn.flow) return;
    event.preventDefault();
    setCtxMenu({ x: event.clientX, y: event.clientY, turn });
  }

  return (
    <Panel className="flex h-full min-h-[22rem] flex-col">
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            <Play size={15} className="text-accent" aria-hidden />
            Probar
          </span>
        }
        description="Habla con el agente. Ajusta propósito o fuentes y vuelve a preguntar."
      />

      {waitingOnIndex && (
        <p
          className="border-b border-warn/25 bg-warn-soft px-4 py-2.5 text-[13px] leading-relaxed text-warn"
          role="status"
          data-testid="chat-wait-index"
        >
          Espera a que termine el indexado; ahora mismo no hay nada que buscar.
        </p>
      )}
      {inactive && (
        <div
          className="flex flex-wrap items-center gap-3 border-b border-warn/25 bg-warn-soft px-4 py-2.5 text-[13px] text-warn"
          role="status"
        >
          Actívalo para probar.
          {onActivate && (
            <Button size="sm" onClick={onActivate}>
              Activar
            </Button>
          )}
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {turns.length === 0 && (
          <EmptyState
            icon={Play}
            title="Haz una pregunta de prueba"
            body="El agente usa el propósito y las fuentes de la configuración."
            compact
          />
        )}
        {turns.map((turn, index) => (
          <article
            key={`${turn.role}-${index}`}
            className={`bubble ${turn.role === "user" ? "bubble-user ml-auto" : "bubble-assistant"}`}
            onContextMenu={(event) => handleContextMenu(event, turn)}
          >
            <p className="whitespace-pre-wrap">{turn.text}</p>
            {turn.role === "assistant" && (turn.sources?.length ?? 0) > 0 && (
              <div className="mt-2 border-t border-border-soft pt-2">
                <p className="eyebrow">Fuentes usadas</p>
                <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-xs text-muted">
                  {turn.sources!.map((id) => (
                    <li key={id}>{nameById.get(id) || id.slice(0, 8)}</li>
                  ))}
                </ol>
              </div>
            )}
            {turn.emptyHint && (
              <p className="mt-2 text-xs text-muted">
                No encontró nada en las fuentes elegidas. Prueba otra pregunta o revisa que estén indexadas.
              </p>
            )}
            {turn.error && <p className="mt-2 text-xs text-danger">{turn.error}</p>}
            {turn.role === "assistant" && turn.flow && (
              <button
                type="button"
                className="mt-2 cursor-pointer text-[11px] text-muted underline underline-offset-2 transition-colors hover:text-text"
                onClick={() => setFlowFor(turn)}
              >
                Ver flujo
              </button>
            )}
          </article>
        ))}
        {status && (
          <p
            className="state-rail text-xs text-muted"
            data-state={playing ? "running" : "ready"}
            role="status"
          >
            {status}
          </p>
        )}
      </div>

      <form ref={formRef} className="flex items-end gap-2 border-t border-border p-3" onSubmit={onSubmit}>
        <label className="block min-w-0 flex-1">
          <span className="sr-only">Pregunta de prueba</span>
          <Textarea
            className="min-h-9 resize-none py-2"
            rows={1}
            placeholder="Pregunta al agente…"
            value={input}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (!blocked) formRef.current?.requestSubmit();
              }
            }}
            disabled={playing || inactive}
          />
        </label>
        <Button type="submit" variant="primary" leadingIcon={PaperPlaneRight} loading={playing} disabled={blocked}>
          Probar
        </Button>
      </form>
      {disabledReason && <p className="px-3 pb-3 text-xs text-muted">{disabledReason}</p>}

      {ctxMenu && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setCtxMenu(null)}
          onContextMenu={(event) => {
            event.preventDefault();
            setCtxMenu(null);
          }}
        >
          <div
            className="absolute z-50 min-w-40 rounded-md border border-border bg-surface p-1 shadow-lg"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
            role="menu"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="w-full cursor-pointer rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-text transition-colors hover:bg-soft"
              onClick={() => {
                setFlowFor(ctxMenu.turn);
                setCtxMenu(null);
              }}
            >
              Ver flujo
            </button>
            <button
              type="button"
              role="menuitem"
              className="w-full cursor-pointer rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-text transition-colors hover:bg-soft"
              onClick={() => {
                void navigator.clipboard?.writeText(ctxMenu.turn.text);
                setCtxMenu(null);
              }}
            >
              Copiar respuesta
            </button>
          </div>
        </div>
      )}

      {session ? (
        <FlowDrawer
          open={flowFor !== null}
          onOpenChange={(open) => {
            if (!open) setFlowFor(null);
          }}
          flow={(flowFor?.flow as Record<string, unknown> | null) ?? null}
          role="admin"
          session={session}
        />
      ) : null}
    </Panel>
  );
}
