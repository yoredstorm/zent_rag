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
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
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

function renderMarkdown(text: string) {
  return renderMarkdownHtml(text);
}

type SourceItem = { text: string; image?: string; score?: number };

type Message = StoredMessage & { id: string };

type StreamMeta = {
  sources: SourceItem[];
  sqlQuery: string | null;
  method: string;
  lazyIngested: boolean;
  queryId: string;
  conversationId: string;
  usage: { total_tokens: number };
  latencyMs: number;
};

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
  const [role, setRole] = useState<"admin" | "customer">("admin");
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
    const conv: Conversation = {
      id,
      title: existing?.title || titleFrom(messagesToSave),
      updatedAt: Date.now(),
      messages: messagesToSave,
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
    setStreaming(true);
    setStreamText("");
    setStreamPhase("Buscando en tus datos…");
    setError("");

    if (hintTimer.current) window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => {
      setStreamPhase("Buscando más a fondo en tus datos…");
    }, 2500);

    const controller = new AbortController();
    abortRef.current = controller;

    const body: Record<string, unknown> = { query, role };
    if (conversationId) body.conversation_id = conversationId;

    const userMessage: Message = { id: uid(), role: "user", content: query };
    const withUser = [...messages, userMessage];
    setMessages(withUser);
    if (conversationId) persist(withUser.map(({ id: _id, ...rest }) => rest), conversationId);

    let buffer = "";
    let acc = "";
    let meta: StreamMeta | null = null;

    try {
      const res = await fetch("/api/v1/rag/query/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
          "X-Organization-Id": session.organizationId,
          "X-User-Role": role,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        let message = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          message = data.detail || data.message || message;
        } catch {
          // mantiene el código HTTP
        }
        throw new Error(message);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      const processEvent = (event: string, data: string) => {
        if (event === "delta") {
          const text = JSON.parse(data).text as string;
          acc += text;
          setStreamText(acc);
          setStreamPhase("");
        } else if (event === "sources") {
          const payload = JSON.parse(data) as {
            sources: ({ content?: string; score?: number; image_base64?: string | null } | string)[];
            method: string;
            sql_query: string | null;
            lazy_ingested: boolean;
          };
          const sources: SourceItem[] =
            payload.method === "sql"
              ? []
              : (payload.sources || [])
                  .filter(
                    (s): s is { content?: string; score?: number; image_base64?: string | null } =>
                      typeof s === "object" && s !== null
                  )
                  .slice(0, 6)
                  .map((s) => ({
                    text: (s.content || "").slice(0, 240),
                    image: s.image_base64 || undefined,
                    score: s.score,
                  }));
          meta = {
            sources,
            sqlQuery: payload.sql_query ?? null,
            method: payload.method,
            lazyIngested: payload.lazy_ingested ?? false,
            queryId: "",
            conversationId: conversationId ?? "",
            usage: { total_tokens: 0 },
            latencyMs: 0,
          };
        } else if (event === "done") {
          const payload = JSON.parse(data) as {
            conversation_id: string;
            query_id: string;
            usage: { total_tokens: number };
            latency_ms: number;
          };
          if (meta) {
            meta.queryId = payload.query_id;
            meta.conversationId = payload.conversation_id;
            meta.usage = payload.usage ?? meta.usage;
            meta.latencyMs = payload.latency_ms ?? 0;
          }
        } else if (event === "error") {
          throw new Error((JSON.parse(data) as { message: string }).message);
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let event = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7).trim();
            else if (line.startsWith("data: ")) data += line.slice(6);
          }
          if (data) processEvent(event, data);
        }
      }

      if (!meta) {
        throw new Error("El servidor cerró la conexión sin enviar una respuesta");
      }
      const finalMeta = meta as StreamMeta;

      const assistantMessage: Message = {
        id: uid(),
        role: "assistant",
        content: acc,
        sources: finalMeta.sources.length > 0 ? finalMeta.sources : undefined,
        sqlQuery: finalMeta.sqlQuery ?? null,
        method: finalMeta.method,
        lazyIngested: finalMeta.lazyIngested,
        queryId: finalMeta.queryId,
        userQuery: query,
        latencyMs: finalMeta.latencyMs,
      };
      const finalMessages = [...withUser, assistantMessage];
      setMessages(finalMessages);
      setConversationId(finalMeta.conversationId);
      setStreaming(false);
      setStreamText("");
      persist(
        finalMessages.map(({ id: _id, ...rest }) => rest),
        finalMeta.conversationId
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        const m = meta as StreamMeta | null;
        const partial: Message = {
          id: uid(),
          role: "assistant",
          content: acc,
          stopped: true,
          method: m?.method ?? "rag",
          sources: (m?.sources?.length ?? 0) > 0 ? m!.sources : undefined,
          sqlQuery: m?.sqlQuery ?? null,
          lazyIngested: m?.lazyIngested ?? false,
          userQuery: query,
        };
        const finalMessages = [...withUser, partial];
        setMessages(finalMessages);
        if (m?.conversationId || conversationId) {
          const id = m?.conversationId || conversationId!;
          setConversationId(id);
          persist(finalMessages.map(({ id: _id, ...rest }) => rest), id);
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
      const next = messages.map((m, i) => (i === index ? { ...m, rated: rating } : m));
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

  const groups = useMemo(() => groupByDay(conversations), [conversations]);
  const empty = messages.length === 0 && !streaming;

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
          <h1 className="text-xl font-semibold tracking-tight text-text">
            Pregúntale a tus datos
          </h1>
          <div className="flex items-center gap-2">
            <label className="text-xs text-faint" htmlFor="role">
              Vista
            </label>
            <div className="field w-auto">
              <select
                id="role"
                className="w-auto! cursor-pointer"
                value={role}
                onChange={(e) => setRole(e.target.value as "admin" | "customer")}
                title={
                  role === "admin"
                    ? "Vista equipo: acceso a métricas y datos internos"
                    : "Vista cliente: catálogo y productos"
                }
              >
                <option value="admin">Equipo</option>
                <option value="customer">Cliente</option>
              </select>
            </div>
          </div>
        </div>

        <ErrorInline message={error} />

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
                  Escribe una pregunta para empezar
                </h2>
                <p className="max-w-sm text-[13px] leading-relaxed text-muted">
                  Pregunta sobre ventas, productos o métricas de tu negocio. El asistente
                  usa tus datos sincronizados y puede consultar tu base en tiempo real.
                </p>
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
              </div>
            )}

            {messages.map((m, i) => (
              <MessageBubble
                key={m.id}
                message={m}
                onFeedback={(rating) => void sendFeedback(i, rating)}
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
                role === "customer"
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
                disabled={!input.trim()}
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
}: {
  message: Message;
  onFeedback: (rating: "up" | "down") => void;
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
            <div className="mt-2 rounded-xs border border-border/70 bg-black/20">
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
