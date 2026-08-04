import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

type RolePrompt = {
  system_prompt: string;
  custom_instructions: string;
  is_customized: boolean;
};

type PromptStatus = {
  roles: Record<string, RolePrompt>;
};

export default function PromptsPage() {
  const { session } = useAuth();
  const [role, setRole] = useState<"admin" | "customer">("admin");
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [testQuery, setTestQuery] = useState("¿Cuáles son los productos disponibles?");
  const [testAnswer, setTestAnswer] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    api<PromptStatus>("/api/v1/admin/prompt", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then((data) => {
        const r = data.roles[role];
        if (r) {
          setPrompt(r.system_prompt);
          setInstructions(r.custom_instructions || "");
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
  }, [session, role]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api("/api/v1/admin/prompt", {
        method: "PUT",
        token: session.token,
        tenantId: session.tenantId,
        body: JSON.stringify({
          system_prompt: prompt,
          custom_instructions: instructions,
          role,
        }),
      });
      setMsg("Prompt guardado");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  async function testPrompt() {
    if (!session) return;
    setError("");
    setTestAnswer("Ejecutando…");
    try {
      const data = await api<{ answer: string }>("/api/v1/admin/prompt/test", {
        method: "POST",
        token: session.token,
        tenantId: session.tenantId,
        body: JSON.stringify({
          query: testQuery,
          system_prompt: prompt,
          custom_instructions: instructions,
          role,
        }),
      });
      setTestAnswer(data.answer);
    } catch (err) {
      setTestAnswer("");
      setError(err instanceof Error ? err.message : "Test falló");
    }
  }

  return (
    <div>
      <h1>Prompts</h1>
      <p className="muted">System prompt por rol (admin / customer).</p>
      {error && <p className="error">{error}</p>}
      {msg && <p className="success">{msg}</p>}
      <form className="panel" onSubmit={save}>
        <div className="field">
          <label htmlFor="role">Rol</label>
          <select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value as "admin" | "customer")}
          >
            <option value="admin">admin</option>
            <option value="customer">customer</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="prompt">System prompt</label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="instr">Custom instructions</label>
          <textarea
            id="instr"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </div>
        <button className="btn" type="submit">
          Guardar
        </button>
      </form>
      <div className="panel">
        <h2>Test (sin cache)</h2>
        <div className="field">
          <label htmlFor="tq">Query</label>
          <input
            id="tq"
            value={testQuery}
            onChange={(e) => setTestQuery(e.target.value)}
          />
        </div>
        <button className="btn secondary" type="button" onClick={testPrompt}>
          Probar
        </button>
        {testAnswer && (
          <pre className="mono" style={{ whiteSpace: "pre-wrap", marginTop: "1rem" }}>
            {testAnswer}
          </pre>
        )}
      </div>
    </div>
  );
}
