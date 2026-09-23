import {
  Broom,
  ChatCircle,
  PaperPlaneRight,
  Play,
  TreeStructure,
} from "@phosphor-icons/react";
import {
  FormEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Session } from "../../api";
import FlowDrawer from "../../pages/chat/FlowDrawer";
import { Badge, Button, IconButton, LoadingDots, Panel, PanelHeader, Textarea } from "../ui";
import { SUGGESTED_QUESTIONS, type KnowledgeSource } from "./types";

export type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  sources?: string[];
  emptyHint?: boolean;
  error?: string;
  flow?: Record<string, unknown> | null;
  /** Run del agente: referencia de ejecución para "Ver flujo" y memoria. */
  runId?: string;
  /** Pregunta que originó el turno (contexto para memoria y replay). */
  question?: string;
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
  agentName,
  model,
  onInput,
  onSubmit,
  onSuggest,
  onClear,
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
  agentName?: string;
  model?: string;
  onInput: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  /** Ejecuta una pregunta sugerida: es una acción explícita del usuario. */
  onSuggest?: (question: string) => void;
  onClear?: () => void;
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
  const selectedSources = sources.filter((source) => selectedIds.includes(source.id));

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

  const facts = [
    selectedSources.length
      ? `${selectedSources.length} fuente${selectedSources.length === 1 ? "" : "s"}`
      : "",
    model ? model : "",
  ].filter(Boolean);

  return (
    <Panel className="flex h-full min-h-[22rem] flex-col">
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            <Play size={15} className="text-accent" aria-hidden />
            Probar
          </span>
        }
        description="Hablá con el agente. Ajustá propósito o fuentes y volvé a preguntar."
        actions={
          <>
            <Badge tone={inactive ? "neutral" : "ok"} dot>
              {inactive ? "En pausa" : "Activo"}
            </Badge>
            {turns.length > 0 && onClear ? (
              <IconButton
                label="Limpiar conversación de prueba"
                icon={Broom}
                iconSize={15}
                onClick={onClear}
              />
            ) : null}
          </>
        }
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
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-md border border-accent-line bg-accent-soft text-accent">
              <ChatCircle size={19} weight="regular" aria-hidden />
            </div>
            <p className="mt-1 text-sm font-medium text-text">
              {agentName ? `Preguntale a ${agentName}` : "Hacé una pregunta de prueba"}
            </p>
            <p className="max-w-sm text-[13px] leading-relaxed text-muted text-pretty">
              Responde con el propósito y las fuentes configuradas, y muestra en qué se apoyó.
            </p>
            {facts.length ? (
              <p className="text-xs text-faint">{facts.join(" · ")}</p>
            ) : null}
            {onSuggest && !inactive && (
              <div className="mt-3 flex w-full max-w-sm flex-col gap-1.5">
                {SUGGESTED_QUESTIONS.map((question) => (
                  <button
                    key={question}
                    type="button"
                    disabled={playing}
                    onClick={() => onSuggest(question)}
                    className="cursor-pointer rounded-md border border-border bg-raised px-3 py-2 text-left text-[12.5px] text-muted transition-colors duration-150 hover:border-border-strong hover:text-text disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {question}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {turns.map((turn, index) => (
          <article
            key={`${turn.role}-${index}`}
            className={`bubble ${turn.role === "user" ? "bubble-user ml-auto" : "bubble-assistant"}`}
            onContextMenu={(event) => handleContextMenu(event, turn)}
          >
            <p className="whitespace-pre-wrap">{turn.text}</p>
            {turn.role === "assistant" && (turn.sources?.length ?? 0) > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border-soft pt-2">
                <span className="text-[11px] text-faint">Fuentes</span>
                {turn.sources!.map((id) => (
                  <Badge key={id} tone="neutral" title={nameById.get(id) || id}>
                    {nameById.get(id) || `${id.slice(0, 8)}…`}
                  </Badge>
                ))}
              </div>
            )}
            {turn.emptyHint && (
              <p className="mt-2 text-xs text-muted">
                No encontró nada en las fuentes elegidas. Probá otra pregunta o revisá que estén
                indexadas.
              </p>
            )}
            {turn.error && <p className="mt-2 text-xs text-danger">{turn.error}</p>}
            {turn.role === "assistant" && turn.flow && (
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  leadingIcon={TreeStructure}
                  onClick={() => setFlowFor(turn)}
                >
                  Ver flujo
                </Button>
              </div>
            )}
          </article>
        ))}
        {playing && (
          <div className="flex items-center gap-2 text-xs text-muted" role="status">
            <LoadingDots label="El agente está respondiendo" />
            {status || "El agente está respondiendo…"}
          </div>
        )}
        {!playing && status && (
          <p className="state-rail text-xs text-muted" data-state="ready" role="status">
            {status}
          </p>
        )}
      </div>

      <form ref={formRef} className="border-t border-border p-3" onSubmit={onSubmit}>
        <div className="flex items-end gap-2">
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
          <IconButton
            type="submit"
            label="Probar"
            icon={PaperPlaneRight}
            variant="primary"
            loading={playing}
            disabled={blocked}
          />
        </div>
        <p className="mt-1.5 text-[11px] text-faint">
          Enter envía · Shift+Enter salto de línea
          {disabledReason ? ` · ${disabledReason}` : ""}
        </p>
      </form>

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
          runId={flowFor?.runId}
          method="agent"
          question={flowFor?.question}
          session={session}
        />
      ) : null}
    </Panel>
  );
}
