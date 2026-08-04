import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

type Message = { role: "user" | "assistant"; content: string; sources?: string[] };

type RagResponse = {
  answer: string;
  conversation_id: string;
  sources: { content: string; score: number }[];
  latency_ms: number;
  method: string;
};

export default function ChatPage() {
  const { session } = useAuth();
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
          content: `${data.answer}\n\n(${data.method}, ${Math.round(data.latency_ms)} ms)`,
          sources: data.sources?.slice(0, 3).map((s) => s.content.slice(0, 180)),
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en chat");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1>Chat demo</h1>
      <p className="muted">Consulta RAG autenticada con tu token.</p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <label className="muted" htmlFor="role">
          Rol
        </label>
        <select
          id="role"
          value={role}
          onChange={(e) => setRole(e.target.value as "admin" | "customer")}
        >
          <option value="admin">admin</option>
          <option value="customer">customer</option>
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
              {m.content}
              {m.sources && m.sources.length > 0 && (
                <div className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
                  Sources: {m.sources.join(" · ")}
                </div>
              )}
            </div>
          ))}
          {messages.length === 0 && (
            <p className="muted">Escribe una pregunta para empezar.</p>
          )}
        </div>
        <form className="row" onSubmit={send}>
          <input
            style={{ flex: 1, minWidth: "200px" }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Pregunta…"
            disabled={loading}
          />
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "…" : "Enviar"}
          </button>
        </form>
      </div>
    </div>
  );
}
