import { SignIn } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, afterLoginPath } from "../api";
import { useAuth } from "../auth";
import { usePlatformAuth } from "../platformAuth";
import { AuthShell } from "../components/auth/AuthShell";
import { Button } from "../components/ui/Button";
import { ErrorInline, SuccessInline } from "../components/ui/states";
import { Field, Input, PasswordInput } from "../components/ui/form";

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
  const [forgotLoading, setForgotLoading] = useState(false);

  if (ready && session) return <Navigate to={afterLoginPath(session)} replace />;

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
              : "Esta cuenta es de plataforma. Entrá por el Control Center."
          );
          return;
        }
      }
      setError(msg || "No pudimos iniciar sesión. Revisá tus credenciales e intentá de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  async function onForgot() {
    setForgotMsg("");
    setError("");
    setForgotLoading(true);
    try {
      await api("/api/v1/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setForgotMsg(
        "Si el email existe, generamos un enlace de restablecimiento. En desarrollo el token queda en los logs del servidor."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos enviar el enlace de restablecimiento.");
    } finally {
      setForgotLoading(false);
    }
  }

  return (
    <AuthShell
      title="Entrar a Zent"
      subtitle="Plataforma de IA empresarial. Iniciá sesión con el email y la contraseña de tu cuenta."
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-[13px] text-muted">
          <span>
            ¿Nuevo en Zent?{" "}
            <Link className="font-medium text-accent hover:underline" to="/signup">
              Crear trial
            </Link>
          </span>
          <Link className="font-medium text-muted hover:text-text" to="/admin/login">
            Control Center
          </Link>
        </div>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        <ErrorInline message={error} className="mb-0" />

        <Field label="Email" required>
          <Input
            id="email"
            type="email"
            autoComplete="username"
            placeholder="tu@empresa.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </Field>

        <Field label="Contraseña" required>
          <PasswordInput
            id="password"
            autoComplete="current-password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>

        <Button type="submit" variant="primary" className="min-h-10 w-full" loading={loading}>
          {loading ? "Entrando…" : "Continuar"}
        </Button>

        <div>
          <button
            type="button"
            className="text-[13px] font-medium text-muted transition-colors duration-150 hover:text-text"
            aria-expanded={forgotOpen}
            onClick={() => {
              setForgotOpen((v) => !v);
              setForgotMsg("");
            }}
          >
            Olvidé mi contraseña
          </button>
          {forgotOpen && (
            <div className="mt-3 flex flex-col gap-2.5 animate-rise">
              <p className="text-[12.5px] leading-relaxed text-muted">
                Te enviamos un enlace de restablecimiento al email de la cuenta.
              </p>
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                loading={forgotLoading}
                onClick={() => void onForgot()}
                leadingIcon={SignIn}
              >
                Enviar enlace
              </Button>
              <SuccessInline message={forgotMsg} className="mb-0" />
            </div>
          )}
        </div>
      </form>
    </AuthShell>
  );
}
