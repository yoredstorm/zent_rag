import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function SignupPage() {
  const { session, signup } = useAuth();
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (session) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await signup(company.trim(), email.trim() || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear trial");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Crear trial</h1>
        <p>Onboarding B2B — genera tenant, plan trial y API token.</p>
        <div className="field">
          <label htmlFor="company">Nombre de empresa</label>
          <input
            id="company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            required
            minLength={1}
          />
        </div>
        <div className="field">
          <label htmlFor="email">Email (opcional)</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        {error && <p className="error">{error}</p>}
        <button className="btn" type="submit" disabled={loading}>
          {loading ? "Creando…" : "Empezar trial"}
        </button>
        <p className="muted" style={{ marginTop: "1rem" }}>
          ¿Ya tienes token? <Link to="/login">Iniciar sesión</Link>
        </p>
      </form>
    </div>
  );
}
