import { FormEvent, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { usePlatformAuth } from "../../platformAuth";
import { Spinner } from "../../components/ui";

function redirectAfterLogin(state: unknown): string {
  const from =
    typeof state === "object" && state != null && "from" in state
      ? String((state as { from: unknown }).from)
      : "";
  if (from.startsWith("/control-center") && !from.includes("/login")) return from;
  return "/control-center";
}

export default function AdminLoginPage() {
  const { session, login, loginMfa } = usePlatformAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaSession, setMfaSession] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (session) return <Navigate to={redirectAfterLogin(location.state)} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const mfa = await login(email.trim(), password);
      if (mfa?.mfaRequired && mfa.mfaSession) {
        setMfaSession(mfa.mfaSession);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitMfa(e: FormEvent) {
    e.preventDefault();
    if (!mfaCode.trim()) return;
    setError("");
    setLoading(true);
    try {
      await loginMfa(mfaSession, mfaCode.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Código inválido");
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
            Acceso de platform admin. URL: /admin/login. Un dueño de organización no entra aquí.
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
        <p className="text-center text-[13px] text-muted">
          <Link className="font-medium text-accent hover:underline" to="/login">
            Portal de clientes
          </Link>
        </p>
      </form>

      {mfaSession && (
        <form className="panel w-full max-w-[400px] space-y-4 p-6" onSubmit={onSubmitMfa}>
          <div>
            <h2 className="text-base font-semibold text-text">Verificación MFA</h2>
            <p className="mt-1 text-sm text-muted">
              Ingresa el código de 6 dígitos de tu autenticador.
            </p>
          </div>
          {error && (
            <p className="rounded-md border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          <div className="field">
            <label htmlFor="admin-mfa">Código TOTP</label>
            <input
              id="admin-mfa"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="123456"
              required
            />
          </div>
          <button type="submit" className="btn btn-primary w-full min-h-11" disabled={loading || !mfaCode.trim()}>
            {loading ? <Spinner /> : "Verificar"}
          </button>
        </form>
      )}
    </div>
  );
}
