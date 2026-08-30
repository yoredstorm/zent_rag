import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { usePlatformAuth } from "../../platformAuth";
import { Spinner } from "../../components/ui";

export default function AdminLoginPage() {
  const { session, login } = usePlatformAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (session) return <Navigate to="/admin" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <form className="panel w-full max-w-[400px] space-y-4 p-6" onSubmit={onSubmit}>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text">
            Control Center
          </h1>
          <p className="mt-1 text-sm text-muted">
            Acceso de platform admin. Un dueño de organización no entra aquí.
          </p>
        </div>
        {error && (
          <p className="rounded-md border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        <div className="field">
          <label htmlFor="admin-email">Email</label>
          <input
            id="admin-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="admin-password">Contraseña</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <button type="submit" className="btn btn-primary w-full min-h-11" disabled={loading}>
          {loading ? <Spinner /> : "Entrar"}
        </button>
      </form>
    </div>
  );
}
