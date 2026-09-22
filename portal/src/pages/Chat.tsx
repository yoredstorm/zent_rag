import {
  CaretDown,
  ChatCircleDots,
  Check,
  Database,
  Files,
  MagnifyingGlass,
  PaperPlaneRight,
  PencilSimple,
  Play,
  Plus,
  Quotes,
  Stop,
  ThumbsDown,
  ThumbsUp,
  Trash,
  User,
} from "@phosphor-icons/react";
import {
  FormEvent,
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import { KnowledgePillarLinks } from "../components/KnowledgePillarLinks";
import {
  Badge,
  Button,
  CodeBlock,
  Drawer,
  EmptyState,
  ErrorInline,
  IconButton,
  LoadingDots,
  Progress,
  Switch,
  Tooltip,
} from "../components/ui";
import { fmtLatency, timeAgo } from "../lib/format";
import { renderMarkdownHtml } from "../lib/markdown";
import SqlRunnerModal from "../components/SqlRunnerModal";
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
import FlowDrawer from "./chat/FlowDrawer";
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

type Source = NonNullable<StoredMessage["sources"]>[number];

function uid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function titleFrom(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "Nueva conversación";
  const t = first.content.replace(/\s+/g, " ").trim();
  return t.length > 42 ? `${t.slice(0, 42)}…` : t;
}

function flowQuestion(messages: Message[], flowFor: Message | null): string {
  if (!flowFor) return "";
  const index = messages.findIndex((message) => message.id === flowFor.id);
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (messages[cursor].role === "user") return messages[cursor].content;
  }
  return "";
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
  const [lastFailedQuery, setLastFailedQuery] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [streamPhase, setStreamPhase] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [flowFor, setFlowFor] = useState<Message | null>(null);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; message: Message } | null>(
    null,
  );
  const [developerMode, setDeveloperMode] = useState(() => {
    try {
      return window.localStorage.getItem("zent_rag_developer_mode") === "1";
    } catch {
      return false;
    }
  });
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const hintTimer = useRef<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!session) return;
    setConversations(listConversations(session.organizationId));
  }, [session]);

  useEffect(() => {
    try {
      window.localStorage.setItem("zent_rag_developer_mode", developerMode ? "1" : "0");
    } catch {
      // storage blocked
    }
  }, [developerMode]);

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

  async function startStreaming(query: string, options: { appendUserMessage?: boolean } = {}) {
    const { appendUserMessage = true } = options;
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
    setLastFailedQuery("");

    if (hintTimer.current) window.clearTimeout(hintTimer.current);
    if (destination.kind === "knowledge") {
      hintTimer.current = window.setTimeout(() => {
        setStreamPhase("Buscando más a fondo en tus datos…");
      }, 2500);
    }

    const controller = new AbortController();
    abortRef.current = controller;

    const userMessage: Message = { id: uid(), role: "user", content: query };
    const withUser = appendUserMessage ? [...messages, userMessage] : messages;
    if (appendUserMessage) {
      setMessages(withUser);
      if (conversationId) persist(withUser.map(({ id: _id, ...rest }) => rest), conversationId);
    }

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
        ragTrace: result.ragTrace ?? null,
        flow: result.flow ?? null,
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
        setError(err instanceof Error ? err.message : "No pudimos obtener una respuesta.");
        setLastFailedQuery(query);
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

  function openFlow(message: Message) {
    setCtxMenu(null);
    setFlowFor(message);
  }

  function handleMessageContextMenu(event: ReactMouseEvent, message: Message) {
    event.preventDefault();
    let target = message;
    if (message.role === "user") {
      const index = messages.findIndex((m) => m.id === message.id);
      const answer = messages.slice(index + 1).find((m) => m.role === "assistant");
      if (!answer) return;
      target = answer;
    }
    if (!target.flow && !target.ragTrace && !target.queryId && !target.sqlQuery) return;
    setCtxMenu({ x: event.clientX, y: event.clientY, message: target });
  }

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

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!session || !input.trim() || streaming) return;
    const query = input.trim();
    setInput("");
    await startStreaming(query);
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!input.trim() || streaming) return;
      const query = input.trim();
      setInput("");
      void startStreaming(query);
    }
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
  const composerDisabled = streaming || (destination.kind !== "knowledge" && !destination.id);

  const composerPlaceholder =
    destination.kind === "agent"
      ? selectedAgent
        ? `Pregunta a ${selectedAgent.name}…`
        : "Elige un agente para preguntar…"
      : destination.kind === "workflow"
        ? "Escribe el mensaje que dispara el flujo…"
        : role === "customer"
          ? "Ej. ¿Qué analgésicos tienen disponible?"
          : "Ej. ¿Cuántas ventas hubo en enero?";

  const historyList = (
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
  );

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      {/* Historial: columna en desktop, drawer en móvil */}
      <aside className="shrink-0 lg:w-[264px]">
        <div className="flex items-center gap-2 lg:hidden">
          <Button
            variant="secondary"
            leadingIcon={ChatCircleDots}
            onClick={() => setHistoryOpen(true)}
          >
            Historial
            {visibleConversations.length > 0 && <Badge tone="neutral">{visibleConversations.length}</Badge>}
          </Button>
          <span className="flex-1" />
          <Button variant="primary" size="sm" leadingIcon={Plus} onClick={newConversation}>
            Nueva
          </Button>
        </div>

        <Drawer
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          side="left"
          width={300}
          title="Conversaciones"
          description="Guardadas en este navegador."
        >
          <div className="mb-3">
            <Button variant="primary" className="w-full" leadingIcon={Plus} onClick={newConversation}>
              Nueva conversación
            </Button>
          </div>
          {historyList}
        </Drawer>

        <div className="panel hidden h-[calc(100dvh-7rem)] flex-col overflow-hidden lg:flex">
          <div className="border-b border-border p-3">
            <Button variant="primary" className="w-full" leadingIcon={Plus} onClick={newConversation}>
              Nueva conversación
            </Button>
          </div>
          {historyList}
        </div>
      </aside>

      {/* Conversación */}
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-h1">Playground</h1>
            <p className="mt-0.5 text-[12.5px] text-muted">
              Probá respuestas antes de publicarlas. Nada de lo que pase acá llega a tus usuarios.
            </p>
          </div>
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
        {destination.kind === "knowledge" ? (
          <div className="mb-3 max-w-sm">
            <Switch
              checked={developerMode}
              onCheckedChange={setDeveloperMode}
              label="Ver cómo Zent resolvió esta pregunta"
              hint="Modo desarrollador. Intent, ruta, evidencia y JEV."
            />
          </div>
        ) : null}

        {error && (
          <ErrorInline
            message={
              <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span>{error}</span>
                {lastFailedQuery && (
                  <Button
                    variant="secondary"
                    size="sm"
                    leadingIcon={Play}
                    onClick={() => void startStreaming(lastFailedQuery, { appendUserMessage: false })}
                  >
                    Reintentar
                  </Button>
                )}
              </span>
            }
          />
        )}
        {destination.kind === "knowledge" && (
          <KnowledgePillarLinks
            title="Mejora las respuestas con conocimiento"
            subtitle="Conecta fuentes, revisa semántica y mide el aprendizaje."
          />
        )}
        {destination.kind === "agent" && selectedAgent && (
          <p className="mb-4 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <span>Fuentes del agente.</span>
            <Link to={`/agents/${selectedAgent.id}`} className="font-medium text-accent hover:underline">
              Editar {selectedAgent.name}
            </Link>
          </p>
        )}
        {destination.kind === "workflow" && selectedWorkflow && (
          <p className="mb-4 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <Badge tone="warn">Modo simulación</Badge>
            <span>No dispara acciones reales.</span>
            <Link to={`/workflows/${selectedWorkflow.id}`} className="font-medium text-accent hover:underline">
              Abrir {selectedWorkflow.name}
            </Link>
          </p>
        )}

        <div className="panel flex flex-col overflow-hidden">
          <div
            ref={scrollRef}
            className="flex min-h-[320px] flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5 lg:h-[calc(100dvh-18rem)]"
          >
            {empty && (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-raised text-accent">
                  <MagnifyingGlass size={21} aria-hidden />
                </span>
                <h2 className="text-h3">
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
                <p className="max-w-md text-[13px] leading-relaxed text-muted">
                  {destination.kind === "agent" && !destination.id ? (
                    <>
                      Crea un agente o elige uno existente.{" "}
                      <Link to="/agents/new" className="font-medium text-accent hover:underline">
                        Crear agente
                      </Link>
                    </>
                  ) : destination.kind === "workflow" && !destination.id ? (
                    <>
                      Crea un flujo o elige uno existente.{" "}
                      <Link to="/workflows/new" className="font-medium text-accent hover:underline">
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
                        className="chip max-w-full cursor-pointer text-left transition-colors duration-150 hover:border-border-strong hover:text-text"
                        onClick={() => {
                          setInput(q);
                          inputRef.current?.focus();
                        }}
                      >
                        <span className="truncate">{q}</span>
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
                developerMode={developerMode}
                onFeedback={(rating) => void sendFeedback(i, rating)}
                onFeedbackReason={(reason) => void sendFeedbackReason(i, reason)}
                onFlow={openFlow}
                onContextMenu={handleMessageContextMenu}
              />
            ))}

            {streaming && (
              <div className="flex items-start gap-2.5">
                <Avatar isUser={false} />
                <div className="min-w-0 flex-1">
                  <div className="bubble bubble-assistant max-w-full">
                    {streamText ? (
                      <>
                        <div
                          className="chat-markdown whitespace-pre-wrap text-[14.5px] leading-relaxed"
                          dangerouslySetInnerHTML={renderMarkdown(streamText)}
                        />
                        <span
                          className="ml-0.5 inline-block h-4 w-[7px] translate-y-0.5 animate-blink rounded-xs bg-accent"
                          aria-hidden
                        />
                      </>
                    ) : (
                      <span className="flex items-center gap-2.5 text-muted">
                        <LoadingDots label="Generando" />
                        <span className="text-[13px]">Generando respuesta…</span>
                      </span>
                    )}
                  </div>
                  {streamPhase && (
                    <p
                      className="state-rail mt-2 flex items-center gap-2 text-[12px] text-muted"
                      data-state="running"
                      role="status"
                      aria-live="polite"
                    >
                      <MagnifyingGlass size={12} className="shrink-0" aria-hidden />
                      {streamPhase}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          <form
            className="border-t border-border bg-surface/60 p-3 sm:p-4"
            onSubmit={(e) => void send(e)}
          >
            <div className="flex items-end gap-2">
              <label className="sr-only" htmlFor="playground-composer">
                Tu pregunta
              </label>
              <textarea
                id="playground-composer"
                ref={inputRef}
                rows={1}
                className="input max-h-40 min-h-10 flex-1 resize-none py-2.5 leading-relaxed"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  const el = e.currentTarget;
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
                }}
                onKeyDown={onComposerKeyDown}
                placeholder={composerPlaceholder}
                disabled={streaming}
                aria-label="Tu pregunta"
                aria-describedby="playground-composer-hint"
              />
              {streaming ? (
                <IconButton
                  label="Detener generación"
                  icon={Stop}
                  variant="danger"
                  iconSize={17}
                  className="h-10 w-10 min-h-0"
                  onClick={stopStreaming}
                />
              ) : (
                <Button
                  type="submit"
                  variant="primary"
                  disabled={!input.trim() || composerDisabled}
                  aria-label="Enviar pregunta"
                  leadingIcon={PaperPlaneRight}
                >
                  Enviar
                </Button>
              )}
            </div>
            <p id="playground-composer-hint" className="mt-2 text-[11.5px] text-faint">
              Enter envía · Shift+Enter salto de línea.
              <span className="hidden sm:inline">
                {" "}
                Las respuestas se generan con tu información sincronizada: verificá los datos sensibles
                antes de decidir.
              </span>
            </p>
          </form>
        </div>
      </div>

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
              onClick={() => openFlow(ctxMenu.message)}
            >
              Ver flujo
            </button>
            {ctxMenu.message.sqlQuery ? (
              <button
                type="button"
                role="menuitem"
                className="w-full cursor-pointer rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-text transition-colors hover:bg-soft"
                onClick={() => {
                  const message = ctxMenu.message;
                  setCtxMenu(null);
                  void navigator.clipboard?.writeText(message.sqlQuery ?? "");
                  pushToast("info", "SQL copiado");
                }}
              >
                Copiar SQL
              </button>
            ) : null}
            <button
              type="button"
              role="menuitem"
              className="w-full cursor-pointer rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-text transition-colors hover:bg-soft"
              onClick={() => {
                const message = ctxMenu.message;
                setCtxMenu(null);
                void navigator.clipboard?.writeText(message.content);
                pushToast("info", "Respuesta copiada");
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
          role={role}
          queryId={flowFor?.queryId}
          question={flowQuestion(messages, flowFor)}
          session={session}
          onFetched={(fetched) => {
            if (!flowFor) return;
            const id = flowFor.id;
            setMessages((prev) =>
              prev.map((message) => (message.id === id ? { ...message, flow: fetched } : message)),
            );
          }}
        />
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sub-componentes                                                     */
/* ------------------------------------------------------------------ */

function Avatar({ isUser }: { isUser: boolean }) {
  return (
    <div
      className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border ${
        isUser
          ? "border-accent-line bg-accent-soft text-accent"
          : "border-border bg-raised text-faint"
      }`}
      aria-hidden
    >
      {isUser ? <User size={14} weight="fill" /> : <ChatCircleDots size={14} />}
    </div>
  );
}

/** Método de respuesta: de dónde salió el dato. */
function MethodChip({ method }: { method: string }) {
  if (method === "sql") {
    return (
      <span className="flex items-center gap-1 text-[11px] text-muted">
        <Database size={11} aria-hidden />
        Datos de tu base
      </span>
    );
  }
  if (method === "agent") {
    return (
      <span className="flex items-center gap-1 text-[11px] text-muted">
        <ChatCircleDots size={11} aria-hidden />
        Agente
      </span>
    );
  }
  if (method === "workflow") {
    return (
      <span className="flex items-center gap-1 text-[11px] text-muted">
        <Play size={11} aria-hidden />
        Flujo simulado
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] text-muted">
      <Files size={11} aria-hidden />
      Documentos
    </span>
  );
}

function RagTracePanel({ trace }: { trace: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const plan = (trace.plan && typeof trace.plan === "object" ? trace.plan : {}) as Record<string, unknown>;
  const evidence = (trace.evidence_evaluation && typeof trace.evidence_evaluation === "object"
    ? trace.evidence_evaluation
    : {}) as Record<string, unknown>;
  const grounding = (trace.grounding && typeof trace.grounding === "object"
    ? trace.grounding
    : null) as Record<string, unknown> | null;
  const rows: { label: string; value: string }[] = [
    { label: "Intent", value: String(trace.intent || plan.intent || "—") },
    { label: "Ruta", value: String(trace.source_route || "—") },
    { label: "Retrieval", value: String(trace.retrieval_strategy || "—") },
    { label: "Path", value: String(plan.path || "—") },
    { label: "top_k", value: String(trace.top_k ?? "—") },
    { label: "Confianza", value: String(trace.confidence ?? "—") },
    { label: "Evidencia", value: String(evidence.score ?? "—") },
    { label: "Reintentos", value: String(Array.isArray(trace.attempts) ? trace.attempts.length : 0) },
    { label: "Modelo", value: String(trace.generator || "—") },
    { label: "Tokens", value: `${trace.input_tokens ?? 0} / ${trace.output_tokens ?? 0}` },
    { label: "Costo", value: String(trace.total_cost ?? "—") },
    { label: "Tiempo", value: `${trace.latency_ms ?? "—"} ms` },
  ];
  if (grounding) {
    rows.push({ label: "Grounding", value: String(grounding.score ?? "—") });
  }
  if (trace.llm_skipped) {
    rows.push({ label: "LLM", value: "omitido (fast path)" });
  }
  const jev = trace.jev_decisions && typeof trace.jev_decisions === "object"
    ? Object.keys(trace.jev_decisions as object)
    : [];
  return (
    <div className="mt-2.5">
      <button
        type="button"
        className="flex cursor-pointer items-center gap-1.5 text-[11.5px] text-muted transition-colors hover:text-text"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Cómo Zent resolvió esta pregunta
        <CaretDown
          size={11}
          className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
          {rows.map((row) => (
            <div key={row.label}>
              <dt className="text-faint">{row.label}</dt>
              <dd className="text-text">{row.value}</dd>
            </div>
          ))}
          {jev.length > 0 ? (
            <div className="col-span-2">
              <dt className="text-faint">JEV</dt>
              <dd className="text-text">{jev.join(", ")}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}

/** Evidencia: las fuentes son una capacidad principal, no un link al pie. */
function SourceEvidence({ sources }: { sources: Source[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const selected = openIndex === null ? null : sources[openIndex];

  return (
    <>
      <button
        type="button"
        className="flex cursor-pointer items-center gap-1.5 text-[11.5px] text-muted transition-colors hover:text-text"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Quotes size={12} aria-hidden />
        {sources.length} {sources.length === 1 ? "fuente" : "fuentes"} recuperadas
        <CaretDown
          size={11}
          className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {sources.map((s, j) => (
            <li key={j}>
              <button
                type="button"
                onClick={() => setOpenIndex(j)}
                className="w-full cursor-pointer rounded-sm border border-border-soft bg-surface px-2.5 py-2 text-left transition-colors duration-150 hover:border-border-strong"
              >
                <span className="flex items-start gap-2">
                  <span className="mono mt-px shrink-0 text-[10px] text-faint">{j + 1}</span>
                  <span className="line-clamp-2 min-w-0 flex-1 text-[12.5px] leading-relaxed text-muted">
                    {s.text}
                  </span>
                  {s.score !== undefined && (
                    <span className="mono shrink-0 text-[10px] text-faint">
                      {(s.score * 100).toFixed(0)}%
                    </span>
                  )}
                </span>
                {s.score !== undefined && (
                  <Progress
                    value={Math.round(s.score * 100)}
                    className="mt-1.5 pl-5"
                  />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      <Drawer
        open={selected !== null}
        onOpenChange={(next) => !next && setOpenIndex(null)}
        title="Evidencia recuperada"
        description={
          selected?.score !== undefined
            ? `Relevancia ${(selected.score * 100).toFixed(0)}% sobre tu consulta`
            : undefined
        }
      >
        {selected && (
          <div className="flex flex-col gap-4">
            {selected.image && (
              <img
                src={`data:image/svg+xml;base64,${selected.image}`}
                alt="Imagen asociada a la fuente"
                className="w-full rounded-md border border-border object-cover"
              />
            )}
            <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap text-text">
              {selected.text}
            </p>
            {selected.score !== undefined && (
              <Progress
                value={Math.round(selected.score * 100)}
                label="Relevancia respecto de tu consulta"
                showValue
              />
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}

function MessageBubble({
  message,
  developerMode = false,
  onFeedback,
  onFeedbackReason,
  onFlow,
  onContextMenu,
}: {
  message: Message;
  developerMode?: boolean;
  onFeedback: (rating: "up" | "down") => void;
  onFeedbackReason: (reason: string) => void;
  onFlow: (message: Message) => void;
  onContextMenu: (event: ReactMouseEvent, message: Message) => void;
}) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const [sqlModalOpen, setSqlModalOpen] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex items-start justify-end gap-2.5">
        <div
          className="bubble bubble-user"
          onContextMenu={(event) => onContextMenu(event, message)}
        >
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
        <div
          className="bubble bubble-assistant max-w-full"
          onContextMenu={(event) => onContextMenu(event, message)}
        >
          <div
            className="chat-markdown whitespace-pre-wrap text-[14.5px] leading-relaxed"
            dangerouslySetInnerHTML={renderMarkdown(message.content)}
          />
          {message.stopped && (
            <span className="mt-1.5 inline-block rounded-xs bg-warn-soft px-1.5 py-0.5 text-[11px] text-warn">
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
            <div className="mt-2.5">
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1.5 text-xs text-muted transition-colors hover:text-text"
                aria-expanded={sqlOpen}
                onClick={() => setSqlOpen((o) => !o)}
              >
                <CaretDown
                  size={12}
                  className={`transition-transform duration-200 ${sqlOpen ? "rotate-180" : ""}`}
                  aria-hidden
                />
                Ver consulta SQL
              </button>
              {sqlOpen && (
                <CodeBlock
                  className="mt-2"
                  code={message.sqlQuery}
                  language="sql"
                  maxHeight={220}
                  actions={
                    <Button
                      variant="ghost"
                      size="sm"
                      leadingIcon={Play}
                      onClick={() => setSqlModalOpen(true)}
                    >
                      Ejecutar
                    </Button>
                  }
                />
              )}
              {sqlModalOpen && message.sqlQuery && (
                <SqlRunnerModal sql={message.sqlQuery} onClose={() => setSqlModalOpen(false)} />
              )}
            </div>
          )}

          {(message.sources?.length ?? 0) > 0 && (
            <div className="mt-2.5">
              <SourceEvidence sources={message.sources!} />
            </div>
          )}
          {developerMode && message.ragTrace ? <RagTracePanel trace={message.ragTrace} /> : null}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-1">
          {message.method && <MethodChip method={message.method} />}
          {(message.flow || message.ragTrace || message.queryId || message.sqlQuery) && (
            <button
              type="button"
              className="cursor-pointer text-[11px] text-muted underline underline-offset-2 transition-colors hover:text-text"
              onClick={() => onFlow(message)}
            >
              Ver flujo
            </button>
          )}
          {message.lazyIngested && (
            <span className="flex items-center gap-1 text-[11px] text-accent">
              <MagnifyingGlass size={11} aria-hidden />
              Indexó información nueva
            </span>
          )}
          {message.latencyMs !== undefined && message.latencyMs > 0 && (
            <span className="mono text-[11px] text-faint">{fmtLatency(message.latencyMs)}</span>
          )}
          {!message.rated ? (
            <span className="ml-auto flex items-center gap-0.5">
              <Tooltip label="Respuesta útil" side="top">
                <button
                  type="button"
                  className="cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-soft hover:text-ok"
                  aria-label="Respuesta útil"
                  onClick={() => onFeedback("up")}
                >
                  <ThumbsUp size={13} aria-hidden />
                </button>
              </Tooltip>
              <Tooltip label="Respuesta no útil" side="top">
                <button
                  type="button"
                  className="cursor-pointer rounded-xs p-1 text-faint transition-colors hover:bg-soft hover:text-danger"
                  aria-label="Respuesta no útil"
                  onClick={() => onFeedback("down")}
                >
                  <ThumbsDown size={13} aria-hidden />
                </button>
              </Tooltip>
            </span>
          ) : message.rated === "down" && message.reasonPrompt ? (
            <span className="ml-auto flex items-center gap-1">
              <label className="sr-only" htmlFor={`reason-${message.id}`}>
                Motivo
              </label>
              <select
                id={`reason-${message.id}`}
                className="input w-auto px-2 py-1 text-[11px]"
                value=""
                onChange={(e) => onFeedbackReason(e.target.value)}
              >
                <option value="" disabled>
                  ¿Por qué no fue útil?
                </option>
                <option value="wrong_answer">Respuesta incorrecta</option>
                <option value="too_long">Demasiado larga</option>
                <option value="too_slow">Demasiado lenta</option>
                <option value="confusing">Confusa</option>
                <option value="other">Otro</option>
              </select>
            </span>
          ) : (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-muted">
              <Check size={12} weight="bold" className={message.rated === "up" ? "text-ok" : "text-danger"} aria-hidden />
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
      <EmptyState
        compact
        icon={ChatCircleDots}
        title="Sin conversaciones todavía"
        body="Escribí una pregunta para empezar. Las conversaciones se guardan en este navegador."
      />
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-2">
      {groups.map((group) => (
        <div key={group.label} className="mb-2">
          <p className="eyebrow px-2 pt-2 pb-1">{group.label}</p>
          {group.items.map((conv) => {
            const active = activeId === conv.id;
            return (
              <div
                key={conv.id}
                className={`group/conversation relative mb-0.5 flex items-center gap-1 rounded-sm px-2 py-2 transition-colors duration-150 ${
                  active ? "bg-soft/70" : "hover:bg-soft/45"
                }`}
              >
                {active && (
                  <span className="absolute top-1.5 bottom-1.5 left-0 w-[2px] rounded-full bg-accent" aria-hidden />
                )}
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
                      aria-label="Nuevo nombre"
                      className="input flex-1 px-2 py-1 text-xs"
                      value={renameValue}
                      onChange={(e) => onRenameValue(e.target.value)}
                      onBlur={() => onCommitRename(conv.id)}
                    />
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      className={`min-w-0 flex-1 cursor-pointer truncate text-left text-[13px] transition-colors ${
                        active ? "font-medium text-text" : "text-muted hover:text-text"
                      }`}
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
                    <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/conversation:opacity-100 focus-within:opacity-100">
                      <IconButton
                        label="Renombrar"
                        icon={PencilSimple}
                        iconSize={13}
                        className="h-6 w-6 min-h-0"
                        onClick={() => onStartRename(conv.id, conv.title)}
                      />
                      <IconButton
                        label="Eliminar"
                        icon={Trash}
                        iconSize={13}
                        className="h-6 w-6 min-h-0 hover:text-danger"
                        onClick={() => onAskDelete(conv.id)}
                      />
                    </span>
                  </>
                )}
                {confirmDeleteId === conv.id && (
                  <div className="absolute inset-x-1 top-full z-10 mt-1 flex items-center gap-2 rounded-md border border-border bg-overlay px-2.5 py-2 shadow-pop">
                    <span className="flex-1 text-[11.5px] text-text">¿Eliminar conversación?</span>
                    <Button variant="danger" size="sm" onClick={() => onDelete(conv.id)}>
                      Eliminar
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => onAskDelete(null)}>
                      Cancelar
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
