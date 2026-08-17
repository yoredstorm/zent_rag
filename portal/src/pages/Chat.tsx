import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: { text: string; image?: string }[];
  sqlQuery?: string | null;
  method?: string;
  lazyIngested?: boolean;
  queryId?: string;
  userQuery?: string;
  rated?: "up" | "down";
};

type RagResponse = {
  answer: string;
  conversation_id: string;
  query_id: string;
  sources: { content: string; score: number; image_base64?: string | null }[];
  latency_ms: number;
  method: string;
  sql_query?: string | null;
  lazy_ingested?: boolean;
};

function renderContent(text: string) {
  const urlRegex = /(https?:\/\/[^\s<]+)/g;
  const parts = text.split(urlRegex);
  return parts.map((p, i) =>
    urlRegex.test(p) ? (
      <a key={i} href={p} target="_blank" rel="noopener noreferrer">{p}</a>
    ) : (
      p
    )
  );
}

export default function ChatPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [role, setRole] = useState<"admin" | "customer">("admin");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHint, setLoadingHint] = useState("");

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!session || !input.trim()) return;
    const query = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: query }]);
    setLoading(true);
    setLoadingHint("");
    setError("");
    const hintTimer = window.setTimeout(() => {
      setLoadingHint("Buscando más a fondo en tus datos…");
    }, 2500);
    try {
      const body: Record<string, unknown> = { query, role };
      if (conversationId) body.conversation_id = conversationId;
      const data = await api<RagResponse>("/api/v1/rag/query", {
        method: "POST",
        token: session.token,
        tenantId: session.tenantId,
        headers: { "X-User-Role": role },
        body: JSON.stringify(body),
      });
      setConversationId(data.conversation_id);
      const sourceItems =
        data.method === "sql"
          ? []
          : (data.sources || []).slice(0, 4).map((s) => ({
              text: s.content.slice(0, 180),
              image: s.image_base64 || undefined,
            }));
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.answer,
          sources: sourceItems.length > 0 ? sourceItems : undefined,
          sqlQuery: data.sql_query ?? null,
          method: data.method,
          lazyIngested: data.lazy_ingested ?? false,
          queryId: data.query_id,
          userQuery: query,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo obtener una respuesta");
    } finally {
      window.clearTimeout(hintTimer);
      setLoadingHint("");
      setLoading(false);
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
        tenantId: session.tenantId,
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
      setMessages((prev) =>
        prev.map((m, i) => (i === index ? { ...m, rated: rating } : m))
      );
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

  const productImages = (sources?: { text: string; image?: string }[]) => {
    if (!sources) return null;
    const withImages = sources.filter((s) => s.image);
    if (withImages.length === 0) return null;
    return (
      <div className="product-images">
        {withImages.slice(0, 3).map((s, j) => (
          <img
            key={j}
            src={`data:image/svg+xml;base64,${s.image}`}
            alt="Producto"
            className="product-thumb"
            title={s.text.slice(0, 80)}
          />
        ))}
      </div>
    );
  };

  return (
    <div>
      <h1>Pregúntale a tus datos</h1>
      <p className="muted">
        Haz preguntas en lenguaje natural sobre tu negocio. Las respuestas se basan en
        tu información sincronizada.
      </p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <label className="muted" htmlFor="role">
          Vista
        </label>
        <select
          id="role"
          value={role}
          onChange={(e) => setRole(e.target.value as "admin" | "customer")}
        >
          <option value="admin">Equipo</option>
          <option value="customer">Cliente</option>
        </select>
        <button
          className="btn secondary"
          type="button"
          onClick={() => {
            setMessages([]);
            setConversationId(null);
          }}
        >
          Nueva conversación
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="panel">
        <div className="chat">
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              <div>{renderContent(m.content)}</div>
              {m.role === "assistant" && m.method !== "sql" && productImages(m.sources)}
              {m.role === "assistant" && m.method && (
                <div className="muted" style={{ marginTop: "0.35rem", fontSize: "0.75rem" }}>
                  {m.method === "sql" ? "Datos de tu base" : "Documentos"}
                </div>
              )}
              {m.role === "assistant" && m.lazyIngested && (
                <div className="muted" style={{ marginTop: "0.15rem", fontSize: "0.75rem" }}>
                  🔍 Se indexó información nueva para responder esto
                </div>
              )}
              {m.sqlQuery && (
                <details className="sql-details">
                  <summary>Ver consulta SQL</summary>
                  <pre className="mono sql-pre">{m.sqlQuery}</pre>
                </details>
              )}
              {m.method !== "sql" && m.sources && m.sources.length > 0 && (
                <div className="source-chips">
                  {m.sources.map((s, j) => (
                    <span key={j} className="source-chip" title={s.text}>
                      {s.text.length > 80 ? `${s.text.slice(0, 80)}…` : s.text}
                    </span>
                  ))}
                </div>
              )}
              {m.role === "assistant" && (
                <div className="feedback-row">
                  <button
                    type="button"
                    className="feedback-btn"
                    disabled={!!m.rated}
                    aria-label="Respuesta útil"
                    onClick={() => void sendFeedback(i, "up")}
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    className="feedback-btn"
                    disabled={!!m.rated}
                    aria-label="Respuesta no útil"
                    onClick={() => void sendFeedback(i, "down")}
                  >
                    👎
                  </button>
                  {m.rated && (
                    <span className="muted" style={{ fontSize: "0.75rem" }}>
                      Gracias
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="bubble assistant">
              <span className="loading" aria-label="Cargando" />
              {loadingHint && (
                <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.35rem" }}>
                  {loadingHint}
                </div>
              )}
            </div>
          )}
          {messages.length === 0 && !loading && (
            <p className="muted">Escribe una pregunta para empezar.</p>
          )}
        </div>
        <form className="row" onSubmit={send}>
          <input
            style={{ flex: 1, minWidth: "200px" }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ej. ¿Qué analgésicos tienen disponible?"
            disabled={loading}
          />
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Pensando…" : "Enviar"}
          </button>
        </form>
      </div>
    </div>
  );
}