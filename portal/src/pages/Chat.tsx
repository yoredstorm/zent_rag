import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  sqlQuery?: string | null;
  method?: string;
  queryId?: string;
  userQuery?: string;
  rated?: "up" | "down";
};

type RagResponse = {
  answer: string;
  conversation_id: string;
  query_id: string;
  sources: { content: string; score: number }[];
  latency_ms: number;
  method: string;
  sql_query?: string | null;
};

export default function ChatPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [role, setRole] = useState<"admin" | "customer">("admin");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!session || !input.trim()) return;
    const query = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: query }]);
    setLoading(true);
    setError("");
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
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.answer,
          sources: data.sources?.slice(0, 3).map((s) => s.content.slice(0, 180)),
          sqlQuery: data.sql_query ?? null,
          method: data.method,
          queryId: data.query_id,
          userQuery: query,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo obtener una respuesta");
    } finally {
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
              <div>{m.content}</div>
              {m.role === "assistant" && m.method && (
                <div className="muted" style={{ marginTop: "0.35rem", fontSize: "0.75rem" }}>
                  {m.method === "sql" ? "Datos de tu base" : "Documentos"}
                </div>
              )}
              {m.sqlQuery && (
                <details className="sql-details">
                  <summary>Ver consulta SQL</summary>
                  <pre className="mono sql-pre">{m.sqlQuery}</pre>
                </details>
              )}
              {m.sources && m.sources.length > 0 && (
                <div className="source-chips">
                  {m.sources.map((s, j) => (
                    <span key={j} className="source-chip" title={s}>
                      {s.length > 80 ? `${s.slice(0, 80)}…` : s}
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
            placeholder="Ej. ¿Cuántas ventas hubo este mes?"
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
