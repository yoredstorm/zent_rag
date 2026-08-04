import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function LoginPage() {
  const { session, loginWithToken } = useAuth();
  const [token, setToken] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState("");

  if (session) return <Navigate to="/" replace />;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!token.trim() || !tenantId.trim()) {
      setError("Token y tenant_id son obligatorios");
      return;
    }
    loginWithToken(token.trim(), tenantId.trim());
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Entrar</h1>
        <p>Usa tu Bearer token `rag_live_…` y el tenant_id.</p>
        <div className="field">
          <label htmlFor="token">API token</label>
          <input
            id="token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="rag_live_…"
            required
          />
        </div>
        <div className="field">
          <label htmlFor="tenant">Tenant ID</label>
          <input
            id="tenant"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            required
          />
        </div>
        {error && <p className="error">{error}</p>}
        <button className="btn" type="submit">
          Continuar
        </button>
        <p className="muted" style={{ marginTop: "1rem" }}>
          ¿Nuevo? <Link to="/signup">Crear trial</Link>
        </p>
      </form>
    </div>
  );
}
