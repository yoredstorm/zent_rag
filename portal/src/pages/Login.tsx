import { SignIn } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { usePlatformAuth } from "../platformAuth";
import { Spinner } from "../components/ui";

export default function LoginPage() {
  const { session, ready, login } = useAuth();
  const { login: platformLogin } = usePlatformAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotMsg, setForgotMsg] = useState("");

  if (ready && session) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email.trim(), password);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("platform_login_required") || msg.includes("/admin/login")) {
        try {
          await platformLogin(email.trim(), password);
          navigate("/admin", { replace: true });
          return;
        } catch (platformErr) {
          setError(
            platformErr instanceof Error
              ? platformErr.message
              : "Entra en /admin/login (Control Center)"
          );
          return;
        }
      }
      setError(msg || "Error al iniciar sesión");
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
            <h1 className="text-xl font-semibold tracking-tight text-text">
              Entrar a Zent<span className="text-accent">RAG</span>
            </h1>
            <p className="mt-1 text-sm text-muted">
              Inicia sesión con el email y contraseña de tu trial.
            </p>
          </div>
        </div>

        <form className="panel space-y-4 p-6" onSubmit={onSubmit}>
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
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="field-error" role="alert">{error}</p>}
          <button className="btn btn-primary w-full py-2.5" type="submit" disabled={loading}>
            {loading ? (
              <>
                <Spinner size={15} /> Entrando…
              </>
            ) : (
              <>
                <SignIn size={17} aria-hidden /> Continuar
              </>
            )}
          </button>
          <p className="text-center text-[13px] text-muted">
            <button
              type="button"
              className="font-medium text-accent hover:underline"
              onClick={() => {
                setForgotOpen((v) => !v);
                setForgotMsg("");
              }}
            >
              Olvidé mi contraseña
            </button>
          </p>
          {forgotOpen && (
            <div className="space-y-2">
              <button
                type="button"
                className="btn btn-secondary w-full min-h-11"
                onClick={() => {
                  setForgotMsg("");
                  api("/api/v1/auth/forgot-password", {
                    method: "POST",
                    body: JSON.stringify({ email: email.trim() }),
                  })
                    .then(() =>
                      setForgotMsg(
                        "Si el email existe, generamos un enlace de reset. En desarrollo el token va en logs/respuesta."
                      )
                    )
                    .catch((err) =>
                      setError(err instanceof Error ? err.message : "Error")
                    );
                }}
              >
                Enviar reset
              </button>
              {forgotMsg && <p className="text-center text-xs text-muted">{forgotMsg}</p>}
            </div>
          )}
          <p className="text-center text-[13px] text-muted">
            ¿Nuevo?{" "}
            <Link className="font-medium text-accent hover:underline" to="/signup">
              Crear trial
            </Link>
            {" · "}
            <Link className="font-medium text-accent hover:underline" to="/admin/login">
              Control Center
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
