import {
  CaretDown,
  ChatCircleDots,
  Copy,
  Database,
  Files,
  MagnifyingGlass,
  PaperPlaneRight,
  PencilSimple,
  Play,
  Plus,
  Stop,
  ThumbsDown,
  ThumbsUp,
  Trash,
  User,
  X,
} from "@phosphor-icons/react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import { KnowledgePillarLinks } from "../components/KnowledgePillarLinks";
import { ErrorInline, LoadingDots } from "../components/ui";
import SqlRunnerModal from "../components/SqlRunnerModal";
import { fmtLatency, timeAgo } from "../lib/format";
import { renderMarkdownHtml } from "../lib/markdown";
import {
  deleteConversation,
  groupByDay,
  listConversations,
  loadConversation,
  renameConversation,
  upsertConversation,
  type Conversation,
  type StoredMessage,
} from "../chatHistory";
import { PlaygroundTargetBar } from "./chat/PlaygroundTargetBar";
import {
  conversationMatches,
  parsePlaygroundSearch,
  playgroundSearchParams,
  readLastUsed,
  resolvePlaygroundTarget,
  sameTarget,
  writeLastUsed,
  type PlaygroundAgent,
  type PlaygroundTarget,
  type PlaygroundWorkflow,
} from "./chat/playgroundTargets";
import { runPlaygroundTurn } from "./chat/runPlaygroundTurn";

function renderMarkdown(text: string) {
  return renderMarkdownHtml(text);
}

type Message = StoredMessage & { id: string; reasonPrompt?: boolean };

function uid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function titleFrom(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "Nueva conversación";
  const t = first.content.replace(/\s+/g, " ").trim();
  return t.length > 42 ? `${t.slice(0, 42)}…` : t;
}

export default function ChatPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [role, setRole] = useState<"admin" | "customer">("admin");
  const [destination, setDestination] = useState<PlaygroundTarget>(() => {
    return parsePlaygroundSearch(searchParams) || readLastUsed() || { kind: "knowledge", id: "" };
  });
  const [agents, setAgents] = useState<PlaygroundAgent[]>([]);
  const [workflows, setWorkflows] = useState<PlaygroundWorkflow[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [streamPhase, setStreamPhase] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const hintTimer = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!session) return;
    setConversations(listConversations(session.organizationId));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setCatalogLoading(true);
    Promise.all([
      api<{ agents: PlaygroundAgent[] }>("/api/v1/agents", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ agents: [] as PlaygroundAgent[] })),
      api<{ workflows: PlaygroundWorkflow[] }>("/api/v1/workflows", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ workflows: [] as PlaygroundWorkflow[] })),
    ])
      .then(([agentRes, wfRes]) => {
        if (cancelled) return;
        const nextAgents = agentRes.agents || [];
        const nextWorkflows = wfRes.workflows || [];
        setAgents(nextAgents);
        setWorkflows(nextWorkflows);
        const resolved = resolvePlaygroundTarget({
          fromUrl: parsePlaygroundSearch(searchParams),
          lastUsed: readLastUsed(),
          agents: nextAgents,
          workflows: nextWorkflows,
        });
        setDestination(resolved);
        writeLastUsed(resolved);
        const nextParams = playgroundSearchParams(resolved);
        if (searchParams.toString() !== nextParams.toString()) {
          setSearchParams(nextParams, { replace: true });
        }
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Solo al montar / cambiar sesión: la URL la escribe el usuario o applyDestination.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const destinationRef = useRef(destination);
  useEffect(() => {
    destinationRef.current = destination;
  }, [destination]);

  function applyDestination(next: PlaygroundTarget) {
    if (sameTarget(destination, next)) return;
    if (abortRef.current) abortRef.current.abort();
    setMessages([]);
    setConversationId(null);
    setStreaming(false);
    setStreamText("");
    setError("");
    setDestination(next);
    writeLastUsed(next);
    setSearchParams(playgroundSearchParams(next), { replace: true });
  }

  const scrollToBottom = useCallback((force = false) => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (force || nearBottom) el.scrollTop = el.scrollHeight;
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamText, scrollToBottom]);

  function persist(messagesToSave: StoredMessage[], id: string) {
    if (!session) return;
    const existing = loadConversation(session.organizationId, id);
    const current = destinationRef.current;
    const conv: Conversation = {
      id,
      title: existing?.title || titleFrom(messagesToSave),
      // `upsertConversation` estampa el timestamp real al guardar.
      updatedAt: existing?.updatedAt ?? 0,
      messages: messagesToSave,
      target: current.kind,
      targetId: current.id,
    };
    setConversations(upsertConversation(session.organizationId, conv));
  }

  function openConversation(id: string) {
    if (!session) return;
    if (abortRef.current) abortRef.current.abort();
    const conv = loadConversation(session.organizationId, id);
    if (!conv) return;
    setMessages(conv.messages.map((m) => ({ ...m, id: uid() })));
    setConversationId(id);
    setStreaming(false);
    setStreamText("");
    setError("");
    setHistoryOpen(false);
    window.setTimeout(() => scrollToBottom(true), 50);
  }

  function newConversation() {
    if (abortRef.current) abortRef.current.abort();
    setMessages([]);
    setConversationId(null);
    setStreaming(false);
    setStreamText("");
    setError("");
    setHistoryOpen(false);
    inputRef.current?.focus();
  }

  async function startStreaming(query: string) {
    if (!session) return;
    if (destination.kind === "agent" && !destination.id) {
      setError("Elige un agente para probar.");
      return;
    }
    if (destination.kind === "workflow" && !destination.id) {
      setError("Elige un flujo para probar.");
      return;
    }
    if (destination.kind === "agent") {
      const agent = agents.find((a) => a.id === destination.id);
      if (agent && !agent.is_active) {
        setError("Actívalo para probar.");
        return;
      }
    }

    setStreaming(true);
    setStreamText("");
    setStreamPhase(
      destination.kind === "agent"
        ? "Ejecutando agente…"
        : destination.kind === "workflow"
          ? "Simulando el flujo…"
          : "Buscando en tus datos…",
    );
    setError("");

    if (hintTimer.current) window.clearTimeout(hintTimer.current);
    if (destination.kind === "knowledge") {
      hintTimer.current = window.setTimeout(() => {
        setStreamPhase("Buscando más a fondo en tus datos…");
      }, 2500);
    }

    const controller = new AbortController();
    abortRef.current = controller;

    const userMessage: Message = { id: uid(), role: "user", content: query };
    const withUser = [...messages, userMessage];
    setMessages(withUser);
    if (conversationId) persist(withUser.map(({ id: _id, ...rest }) => rest), conversationId);

    try {
      const result = await runPlaygroundTurn({
        target: destination,
        query,
        role,
        conversationId,
        session,
        hooks: {
          onDelta: (text) => {
            setStreamText(text);
            setStreamPhase("");
          },
          onPhase: setStreamPhase,
          signal: controller.signal,
        },
      });

      const assistantMessage: Message = {
        id: uid(),
        role: "assistant",
        content: result.text,
        sources: result.sources,
        sqlQuery: result.sqlQuery ?? null,
        method: result.method,
        lazyIngested: result.lazyIngested,
        queryId: result.queryId,
        userQuery: query,
        latencyMs: result.latencyMs,
      };
      const finalMessages = [...withUser, assistantMessage];
      setMessages(finalMessages);
      const persistId = result.conversationId || conversationId || uid();
      setConversationId(persistId);
      setStreaming(false);
      setStreamText("");
      persist(
        finalMessages.map(({ id: _id, ...rest }) => rest),
        persistId,
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        const partial: Message = {
          id: uid(),
          role: "assistant",
          content: streamText,
          stopped: true,
          method:
            destination.kind === "agent" ? "agent" : destination.kind === "workflow" ? "workflow" : "rag",
          userQuery: query,
        };
        const finalMessages = [...withUser, partial];
        setMessages(finalMessages);
        if (conversationId) {
          persist(finalMessages.map(({ id: _id, ...rest }) => rest), conversationId);
        }
        pushToast("info", "Generación detenida");
      } else {
        setError(err instanceof Error ? err.message : "No se pudo obtener una respuesta");
        pushToast("error", "La consulta falló", err instanceof Error ? err.message : undefined);
      }
    } finally {
      setStreaming(false);
      setStreamText("");
      setStreamPhase("");
      if (hintTimer.current) window.clearTimeout(hintTimer.current);
      abortRef.current = null;
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!session || !input.trim() || streaming) return;
    const query = input.trim();
    setInput("");
    await startStreaming(query);
  }

  async function sendFeedback(index: number, rating: "up" | "down") {
    if (!session) return;
    const msg = messages[index];
    if (!msg || msg.role !== "assistant" || msg.rated) return;
    try {
      await api("/api/v1/eval/feedback", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          query: msg.userQuery || "",
          answer: msg.content,
          rating,
          method: msg.method || "rag",
          query_id: msg.queryId,
          conversation_id: conversationId,
          role,
          lazy_ingested: msg.lazyIngested ?? false,
        }),
      });
      const next = messages.map((m, i) => (i === index ? { ...m, rated: rating, reasonPrompt: rating === "down" } : m));
      setMessages(next);
      if (conversationId) {
        persist(next.map(({ id: _id, ...rest }) => rest), conversationId);
      }
      pushToast(
        "success",
        rating === "up" ? "Gracias por tu feedback" : "Feedback registrado",
        "Nos ayuda a mejorar las respuestas."
      );
    } catch (err) {
      pushToast(
        "error",
        "No se pudo enviar el feedback",
        err instanceof Error ? err.message : undefined
      );
    }
  }

  async function sendFeedbackReason(index: number, reason: string) {
    if (!session) return;
    const msg = messages[index];
    if (!msg || msg.role !== "assistant") return;
    try {
      await api("/api/v1/feedback", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ rating: "down", reason, trace_id: msg.queryId || undefined }),
      });
      const next = messages.map((m, i) => (i === index ? { ...m, reasonPrompt: false } : m));
      setMessages(next);
      if (conversationId) persist(next.map(({ id: _id, ...rest }) => rest), conversationId);
      pushToast("success", "Motivo registrado", "Gracias por ayudarnos a mejorar.");
    } catch (err) {
      pushToast("error", "No se pudo registrar el motivo", err instanceof Error ? err.message : undefined);
    }
  }

  function handleDelete(id: string) {
    if (!session) return;
    setConversations(deleteConversation(session.organizationId, id));
    setConfirmDeleteId(null);
    if (conversationId === id) newConversation();
    pushToast("info", "Conversación eliminada");
  }

  function commitRename(id: string) {
    if (!session || !renameValue.trim()) {
      setRenamingId(null);
      return;
    }
    setConversations(renameConversation(session.organizationId, id, renameValue.trim()));
    setRenamingId(null);
  }

  const visibleConversations = useMemo(
    () => conversations.filter((c) => conversationMatches(c, destination)),
    [conversations, destination],
  );
  const groups = useMemo(() => groupByDay(visibleConversations), [visibleConversations]);
  const empty = messages.length === 0 && !streaming;
  const selectedAgent = agents.find((a) => a.id === destination.id);
  const selectedWorkflow = workflows.find((w) => w.id === destination.id);

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      {/* ------------------------------------------------------------- */}
      {/* Historial (drawer en mobile, columna en desktop)               */}
      {/* ------------------------------------------------------------- */}
      <aside className="shrink-0 lg:w-[260px]">
        <div className="flex items-center justify-between lg:hidden">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setHistoryOpen(true)}
          >
            <ChatCircleDots size={16} aria-hidden />
            Historial
          </button>
        </div>
        <div
          className={`fixed inset-0 z-40 lg:hidden ${
            historyOpen ? "block" : "hidden"
          }`}
          role="dialog"
          aria-label="Historial de conversaciones"
        >
          <div
            className="absolute inset-0 animate-fade-in bg-black/60"
            onClick={() => setHistoryOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 flex w-[300px] animate-page-in flex-col border-r border-border bg-surface shadow-pop">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold text-text">Conversaciones</h2>
              <button
                type="button"
                className="cursor-pointer rounded-xs p-1 text-faint hover:bg-soft hover:text-text"
                aria-label="Cerrar historial"
                onClick={() => setHistoryOpen(false)}
              >
                <X size={16} aria-hidden />
              </button>
            </div>
            <ConversationList
              groups={groups}
              activeId={conversationId}
              renamingId={renamingId}
              renameValue={renameValue}
              confirmDeleteId={confirmDeleteId}
              onOpen={openConversation}
              onStartRename={(id, title) => {
                setRenamingId(id);
                setRenameValue(title);
              }}
              onRenameValue={setRenameValue}
              onCommitRename={commitRename}
              onAskDelete={setConfirmDeleteId}
              onDelete={handleDelete}
            />
          </div>
        </div>

        <div className="panel hidden h-[calc(100dvh-7rem)] flex-col overflow-hidden lg:flex">
          <div className="border-b border-border p-3">
            <button
              type="button"
              className="btn btn-primary w-full"
              onClick={newConversation}
            >
              <Plus size={15} aria-hidden />
              Nueva conversación
            </button>
          </div>
          <ConversationList
            groups={groups}
            activeId={conversationId}
            renamingId={renamingId}
            renameValue={renameValue}
            confirmDeleteId={confirmDeleteId}
            onOpen={openConversation}
            onStartRename={(id, title) => {
              setRenamingId(id);
              setRenameValue(title);
            }}
            onRenameValue={setRenameValue}
            onCommitRename={commitRename}
            onAskDelete={setConfirmDeleteId}
            onDelete={handleDelete}
          />
        </div>
      </aside>

      {/* ------------------------------------------------------------- */}
      {/* Chat principal                                                 */}
      {/* ------------------------------------------------------------- */}
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-semibold tracking-tight text-text">Playground</h1>
          <PlaygroundTargetBar
            target={destination}
            agents={agents}
            workflows={workflows}
            loading={catalogLoading}
            role={role}
            onRole={setRole}
            onChange={applyDestination}
          />
        </div>

        <ErrorInline message={error} />
        {destination.kind === "knowledge" && (
          <KnowledgePillarLinks
            title="Mejora las respuestas con conocimiento"
            subtitle="Conecta fuentes, revisa semántica y mide el aprendizaje."
          />
        )}
        {destination.kind === "agent" && selectedAgent && (
          <p className="mb-4 text-xs text-muted">
            Fuentes del agente.{" "}
            <Link to={`/agents/${selectedAgent.id}`} className="text-accent hover:underline">
              Editar {selectedAgent.name}
            </Link>
          </p>
        )}
        {destination.kind === "workflow" && selectedWorkflow && (
          <p className="mb-4 text-xs text-muted">
            Simulación: no dispara acciones reales.{" "}
            <Link to={`/workflows/${selectedWorkflow.id}`} className="text-accent hover:underline">
              Abrir {selectedWorkflow.name}
            </Link>
          </p>
        )}

        <div className="panel flex flex-col overflow-hidden">
          <div
            ref={scrollRef}
            className="flex min-h-[320px] flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5 lg:h-[calc(100dvh-17rem)]"
          >
            {empty && (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-soft text-accent">
                  <MagnifyingGlass size={24} aria-hidden />
                </div>
                <h2 className="text-base font-medium text-text">
                  {destination.kind === "agent" && !destination.id
                    ? "Elige un agente para probar"
                    : destination.kind === "workflow" && !destination.id
                      ? "Elige un flujo para probar"
                      : destination.kind === "agent" && selectedAgent
                        ? `Pregunta a ${selectedAgent.name}`
                        : destination.kind === "workflow" && selectedWorkflow
                          ? `Prueba el flujo ${selectedWorkflow.name}`
                          : "Escribe una pregunta para empezar"}
                </h2>
                <p className="max-w-sm text-[13px] leading-relaxed text-muted">
                  {destination.kind === "agent" && !destination.id ? (
                    <>
                      Crea un agente o elige uno existente.{" "}
                      <Link to="/agents/new" className="text-accent hover:underline">
                        Crear agente
                      </Link>
                    </>
                  ) : destination.kind === "workflow" && !destination.id ? (
                    <>
                      Crea un flujo o elige uno existente.{" "}
                      <Link to="/workflows/new" className="text-accent hover:underline">
                        Crear flujo
                      </Link>
                    </>
                  ) : destination.kind === "agent" ? (
                    selectedAgent?.config?.purpose ||
                    selectedAgent?.description ||
                    "Usa las instrucciones y fuentes de este agente, sin desplegarlo."
                  ) : destination.kind === "workflow" ? (
                    "La corrida es una simulación: no envía correos ni llama APIs de verdad."
                  ) : (
                    "Pregunta sobre ventas, productos o métricas de tu negocio. El asistente usa tus datos sincronizados y puede consultar tu base en tiempo real."
                  )}
                </p>
                {destination.kind === "knowledge" && (
                  <div className="mt-1 flex flex-wrap justify-center gap-2">
                    {[
                      "¿Cuáles son los productos disponibles?",
                      "¿Cuántas ventas hubo este mes?",
                      "Recomiéndame un analgésico",
                    ].map((q) => (
                      <button
                        key={q}
                        type="button"
                        className="cursor-pointer rounded-full border border-border bg-soft px-3 py-1.5 text-xs text-muted transition-colors duration-150 hover:border-accent/40 hover:text-text"
                        onClick={() => {
                          setInput(q);
                          inputRef.current?.focus();
                        }}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {messages.map((m, i) => (
              <MessageBubble
                key={m.id}
                message={m}
                onFeedback={(rating) => void sendFeedback(i, rating)}
                    onFeedbackReason={(reason) => void sendFeedbackReason(i, reason)}
              />
            ))}

            {streaming && (
              <div className="flex items-start gap-2.5">
                <Avatar isUser={false} />
                <div className="bubble bubble-assistant min-w-[60%]">
                  {streamText ? (
                    <div
                      className="chat-markdown whitespace-pre-wrap text-[14.5px] leading-relaxed"
                      dangerouslySetInnerHTML={renderMarkdown(streamText)}
                    />
                  ) : (
                    <LoadingDots />
                  )}
                  {streamText && (
                    <span
                      className="ml-0.5 inline-block h-4 w-[7px] translate-y-0.5 animate-blink rounded-xs bg-accent"
                      aria-hidden
                    />
                  )}
                  {streamPhase && (
                    <p className="mt-2 flex items-center gap-1.5 text-[11.5px] text-faint">
                      <MagnifyingGlass size={12} aria-hidden />
                      {streamPhase}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          <form
            className="flex items-end gap-2 border-t border-border bg-surface/60 p-3 sm:p-4"
            onSubmit={(e) => void send(e)}
          >
            <input
              ref={inputRef}
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text transition-colors duration-200 outline-none placeholder:text-faint hover:border-border-strong focus:border-accent"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                destination.kind === "agent"
                  ? selectedAgent
                    ? `Pregunta a ${selectedAgent.name}…`
                    : "Elige un agente para preguntar…"
                  : destination.kind === "workflow"
                    ? "Escribe el mensaje que dispara el flujo…"
                    : role === "customer"
                      ? "Ej. ¿Qué analgésicos tienen disponible?"
                      : "Ej. ¿Cuántas ventas hubo en enero?"
              }
              disabled={streaming}
              aria-label="Tu pregunta"
            />
            {streaming ? (
              <button
                type="button"
                className="btn btn-danger shrink-0 px-3"
                onClick={stopStreaming}
                aria-label="Detener generación"
              >
                <Stop size={17} weight="fill" aria-hidden />
              </button>
            ) : (
              <button
                className="btn btn-primary shrink-0 px-4"
                type="submit"
                disabled={!input.trim() || (destination.kind !== "knowledge" && !destination.id)}
                aria-label="Enviar pregunta"
              >
                <PaperPlaneRight size={17} aria-hidden />
                Enviar
              </button>
            )}
          </form>
        </div>

        <p className="mt-3 text-center text-[11.5px] text-faint">
          Las respuestas se generan con tu información sincronizada. Verifica los datos
          sensibles antes de decidir.
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sub-componentes                                                     */
/* ------------------------------------------------------------------ */

function Avatar({ isUser }: { isUser: boolean }) {
  return (
    <div
      className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
        isUser
          ? "border-accent/30 bg-accent-soft text-accent"
          : "border-border bg-soft text-faint"
      }`}
      aria-hidden
    >
      {isUser ? <User size={14} weight="fill" /> : <ChatCircleDots size={14} />}
    </div>
  );
}

function MessageBubble({
  message,
  onFeedback,
  onFeedbackReason,
}: {
  message: Message;
  onFeedback: (rating: "up" | "down") => void;
  onFeedbackReason: (reason: string) => void;
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [sqlOpen, setSqlOpen] = useState(false);
  const [sqlModalOpen, setSqlModalOpen] = useState(false);
  const { pushToast } = useToast();

  async function copySql() {
    if (!message.sqlQuery) return;
    try {
      await navigator.clipboard.writeText(message.sqlQuery);
      pushToast("success", "SQL copiado");
    } catch {
      pushToast("error", "No se pudo copiar");
    }
  }

  if (message.role === "user") {
    return (
      <div className="flex items-start justify-end gap-2.5">
        <div className="bubble bubble-user">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <Avatar isUser />
      </div>
    );
  }

  const productImages = (message.sources ?? []).filter((s) => s.image);

  return (
    <div className="flex items-start gap-2.5">
      <Avatar isUser={false} />
      <div className="min-w-0 flex-1">
        <div className="bubble bubble-assistant max-w-full">
          <div
            className="chat-markdown whitespace-pre-wrap text-[14.5px] leading-relaxed"
            dangerouslySetInnerHTML={renderMarkdown(message.content)}
          />
          {message.stopped && (
            <span className="mt-1 inline-block rounded-xs bg-warn-soft px-1.5 py-0.5 text-[11px] text-warn">
              Generación detenida
            </span>
          )}

          {productImages.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {productImages.slice(0, 3).map((s, j) => (
                <img
                  key={j}
                  src={`data:image/svg+xml;base64,${s.image}`}
                  alt="Imagen de producto"
                  title={s.text.slice(0, 80)}
                  className="h-16 w-16 rounded-sm border border-border object-cover transition-transform duration-150 hover:scale-105"
                  loading="lazy"
                />
              ))}
            </div>
          )}

          {message.sqlQuery && (
            <div className="mt-2 rounded-xs border border-border/70 bg-[var(--zent-code-bg)]">
              <div className="flex items-center gap-1 px-2.5 py-1.5">
                <button
                  type="button"
                  className="flex cursor-pointer items-center gap-1.5 text-xs text-muted transition-colors hover:text-text"
                  aria-expanded={sqlOpen}
                  onClick={() => setSqlOpen((o) => !o)}
                >
                  <CaretDown
                    size={12}
                    className={`transition-transform ${sqlOpen ? "rotate-180" : ""}`}
                    aria-hidden
                  />
                  Ver consulta SQL
                </button>
                <span className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    className="cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-raised hover:text-text"
                    aria-label="Copiar SQL"
                    title="Copiar SQL"
                    onClick={() => void copySql()}
                  >
                    <Copy size={12} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className="flex cursor-pointer items-center gap-1 rounded-xs px-1.5 py-1 text-[11px] text-accent transition-colors hover:bg-raised"
                    onClick={() => setSqlModalOpen(true)}
                  >
                    <Play size={11} weight="fill" aria-hidden />
                    Ejecutar
                  </button>
                </span>
              </div>
              {sqlOpen && (
                <pre className="overflow-x-auto border-t border-border/50 px-3 py-2.5 font-mono text-[12px] leading-relaxed text-accent">
                  {message.sqlQuery}
                </pre>
              )}
            </div>
          )}

          {sqlModalOpen && message.sqlQuery && (
            <SqlRunnerModal
              sql={message.sqlQuery}
              onClose={() => setSqlModalOpen(false)}
            />
          )}

          {(message.sources?.length ?? 0) > 0 && (
            <div className="mt-2">
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1 text-[11.5px] text-faint transition-colors hover:text-muted"
                aria-expanded={sourcesOpen}
                onClick={() => setSourcesOpen((o) => !o)}
              >
                <Files size={12} aria-hidden />
                {message.sources!.length} fuentes recuperadas
                <CaretDown
                  size={11}
                  className={`transition-transform ${sourcesOpen ? "rotate-180" : ""}`}
                  aria-hidden
                />
              </button>
              {sourcesOpen && (
                <ul className="mt-1.5 flex flex-col gap-1">
                  {message.sources!.map((s, j) => (
                    <li key={j} className="source-chip flex-col items-start gap-0.5">
                      <span className="line-clamp-2 text-left" title={s.text}>
                        {s.text}
                      </span>
                      {s.score !== undefined && (
                        <span className="mono text-[10px] text-faint">
                          relevancia {(s.score * 100).toFixed(0)}%
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="mt-1 flex items-center gap-2 pl-1">
          {message.method && (
            <span className="flex items-center gap-1 text-[11px] text-faint">
              {message.method === "sql" ? (
                <>
                  <Database size={11} aria-hidden /> Datos de tu base
                </>
              ) : (
                <>
                  <Files size={11} aria-hidden /> Documentos
                </>
              )}
            </span>
          )}
          {message.lazyIngested && (
            <span className="flex items-center gap-1 text-[11px] text-accent">
              <MagnifyingGlass size={11} aria-hidden />
              Indexó información nueva
            </span>
          )}
          {message.latencyMs !== undefined && message.latencyMs > 0 && (
            <span className="mono text-[11px] text-faint">
              {fmtLatency(message.latencyMs)}
            </span>
          )}
          {!message.rated ? (
            <span className="ml-auto flex items-center gap-1">
              <button
                type="button"
                className="cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-soft hover:text-ok"
                aria-label="Respuesta útil"
                onClick={() => onFeedback("up")}
              >
                <ThumbsUp size={13} aria-hidden />
              </button>
              <button
                type="button"
                className="cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-soft hover:text-danger"
                aria-label="Respuesta no útil"
                onClick={() => onFeedback("down")}
              >
                <ThumbsDown size={13} aria-hidden />
              </button>
            </span>
          ) : message.rated === "down" && message.reasonPrompt ? (
            <span className="ml-auto flex items-center gap-1">
              <select
                className="rounded-md border border-border bg-soft px-2 py-1 text-[11px]"
                value=""
                onChange={(e) => onFeedbackReason(e.target.value)}
              >
                <option value="" disabled>¿Por qué no fue útil?</option>
                <option value="wrong_answer">Respuesta incorrecta</option>
                <option value="too_long">Demasiado larga</option>
                <option value="too_slow">Demasiado lenta</option>
                <option value="confusing">Confusa</option>
                <option value="other">Otro</option>
              </select>
            </span>
          ) : (
            <span className="ml-auto text-[11px] text-faint">
              {message.rated === "up" ? "Marcada como útil" : "Marcada como no útil"}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function ConversationList({
  groups,
  activeId,
  renamingId,
  renameValue,
  confirmDeleteId,
  onOpen,
  onStartRename,
  onRenameValue,
  onCommitRename,
  onAskDelete,
  onDelete,
}: {
  groups: { label: string; items: Conversation[] }[];
  activeId: string | null;
  renamingId: string | null;
  renameValue: string;
  confirmDeleteId: string | null;
  onOpen: (id: string) => void;
  onStartRename: (id: string, title: string) => void;
  onRenameValue: (v: string) => void;
  onCommitRename: (id: string) => void;
  onAskDelete: (id: string | null) => void;
  onDelete: (id: string) => void;
}) {
  if (groups.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
        <ChatCircleDots size={22} className="text-faint" aria-hidden />
        <p className="text-[13px] text-muted">Aún no tienes conversaciones.</p>
        <p className="text-[11.5px] text-faint">
          Las conversaciones se guardan en este navegador.
        </p>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-2">
      {groups.map((group) => (
        <div key={group.label} className="mb-2">
          <p className="px-2 pt-2 pb-1 text-[10.5px] font-semibold tracking-[0.08em] text-faint uppercase">
            {group.label}
          </p>
          {group.items.map((conv) => (
            <div
              key={conv.id}
              className={`group/conversation mb-0.5 flex items-center gap-1 rounded-md px-2 py-2 transition-colors duration-150 ${
                activeId === conv.id ? "bg-accent-soft" : "hover:bg-soft"
              }`}
            >
              {renamingId === conv.id ? (
                <form
                  className="flex flex-1 gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    onCommitRename(conv.id);
                  }}
                >
                  <input
                    autoFocus
                    className="flex-1 rounded-xs border border-border bg-soft px-2 py-1 text-xs text-text outline-none focus:border-accent"
                    value={renameValue}
                    onChange={(e) => onRenameValue(e.target.value)}
                    onBlur={() => onCommitRename(conv.id)}
                  />
                </form>
              ) : (
                <>
                  <button
                    type="button"
                    className="min-w-0 flex-1 cursor-pointer truncate text-left text-[13px] text-muted transition-colors hover:text-text"
                    title={conv.title}
                    onClick={() => onOpen(conv.id)}
                  >
                    {conv.title}
                  </button>
                  <span
                    className="mono shrink-0 text-[10px] text-faint"
                    title={new Date(conv.updatedAt).toLocaleString()}
                  >
                    {timeAgo(new Date(conv.updatedAt).toISOString())}
                  </span>
                  <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/conversation:opacity-100">
                    <button
                      type="button"
                      className="cursor-pointer rounded-xs p-1 text-faint hover:bg-raised hover:text-text"
                      aria-label="Renombrar conversación"
                      onClick={() => onStartRename(conv.id, conv.title)}
                    >
                      <PencilSimple size={12} aria-hidden />
                    </button>
                    <button
                      type="button"
                      className="cursor-pointer rounded-xs p-1 text-faint hover:bg-raised hover:text-danger"
                      aria-label="Eliminar conversación"
                      onClick={() => onAskDelete(confirmDeleteId === conv.id ? null : conv.id)}
                    >
                      <Trash size={12} aria-hidden />
                    </button>
                  </span>
                  {confirmDeleteId === conv.id && (
                    <span className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        className="cursor-pointer rounded-xs bg-danger-soft px-1.5 py-0.5 text-[10px] text-danger"
                        onClick={() => onDelete(conv.id)}
                      >
                        Eliminar
                      </button>
                      <button
                        type="button"
                        className="cursor-pointer rounded-xs px-1 py-0.5 text-[10px] text-faint hover:text-text"
                        aria-label="Cancelar eliminación"
                        onClick={() => onAskDelete(null)}
                      >
                        <X size={10} aria-hidden />
                      </button>
                    </span>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
