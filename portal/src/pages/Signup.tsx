import { RocketLaunch } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Spinner } from "../components/ui";

function passwordStrength(pw: string): { label: string; pct: number; color: string } {
  if (pw.length === 0) return { label: "", pct: 0, color: "bg-border" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 1) return { label: "Débil", pct: 25, color: "bg-danger" };
  if (score <= 3) return { label: "Aceptable", pct: 60, color: "bg-warn" };
  return { label: "Fuerte", pct: 100, color: "bg-ok" };
}

export default function SignupPage() {
  const { session, ready, signup } = useAuth();
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (ready && session) return <Navigate to="/" replace />;

  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && password !== confirm;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres");
      return;
    }
    if (password !== confirm) {
      setError("Las contraseñas no coinciden");
      return;
    }
    setLoading(true);
    try {
      await signup(company.trim(), email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear trial");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <div className="w-full max-w-[400px]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-accent/30 bg-accent-soft shadow-glow">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M4 6.5 12 3l8 3.5v6.2c0 4.6-3.2 7.8-8 9.3-4.8-1.5-8-4.7-8-9.3V6.5Z"
                stroke="var(--color-accent)"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path
                d="m8.5 12.5 2.4 2.4 4.6-4.9"
                stroke="var(--color-accent)"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-text">Crear trial</h1>
            <p className="mt-1 text-sm text-muted">
              Crea tu cuenta con email y contraseña para empezar.
            </p>
          </div>
        </div>

        <form className="panel space-y-4 p-6" onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="company">Nombre de empresa</label>
            <input
              id="company"
              placeholder="Mi empresa S.A.C."
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="tu@empresa.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Contraseña</label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              placeholder="Mínimo 8 caracteres"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
            {password.length > 0 && (
              <div className="flex items-center gap-2" aria-live="polite">
                <div className="progress-track h-1 flex-1">
                  <div
                    className={`progress-fill ${strength.color}`}
                    style={{ width: `${strength.pct}%` }}
                  />
                </div>
                <span className="text-[11px] text-faint">{strength.label}</span>
              </div>
            )}
          </div>
          <div className="field">
            <label htmlFor="confirm">Confirmar contraseña</label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              placeholder="Repite la contraseña"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={8}
              aria-invalid={mismatch}
            />
            {mismatch && <p className="field-error">Las contraseñas no coinciden</p>}
          </div>
          {error && <p className="field-error" role="alert">{error}</p>}
          <button className="btn btn-primary w-full py-2.5" type="submit" disabled={loading}>
            {loading ? (
              <>
                <Spinner size={15} /> Creando…
              </>
            ) : (
              <>
                <RocketLaunch size={17} aria-hidden /> Empezar trial
              </>
            )}
          </button>
          <p className="text-center text-[13px] text-muted">
            ¿Ya tienes cuenta?{" "}
            <Link className="font-medium text-accent hover:underline" to="/login">
              Iniciar sesión
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
