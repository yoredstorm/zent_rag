import { ArrowLeft, Key, ShieldCheck } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { AuthShell } from "../../components/auth/AuthShell";
import { AuthButton } from "../../components/auth/AuthButton";
import { DIVE_MS, DIVE_REDUCED_MS, armEntry, disarmEntry } from "../../components/auth/entryTransit";
import { useDiveEffect } from "../../components/auth/useDiveEffect";
import { emitNeuralEvent } from "../../components/auth/neuralSignal";
import { useReveal } from "../../components/auth/reveal";
import { ErrorInline } from "../../components/ui/states";
import { Field, Input, PasswordInput } from "../../components/ui/form";

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
  const navigate = useNavigate();
  const { quiet } = useDiveEffect();
  const reveal = useReveal({ step: 0.06 });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaSession, setMfaSession] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [holdExit, setHoldExit] = useState(false);
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    platformApi<{ enabled?: boolean }>("/api/v1/auth/platform/oidc/config")
      .then((config) => setSsoEnabled(Boolean(config.enabled)))
      .catch(() => setSsoEnabled(false));
  }, []);

  const succeeded = holdExit && Boolean(session);
  // La travesía neuronal manda el tiempo: se entra cuando el zoom termina.
  const holdMs = quiet ? DIVE_REDUCED_MS : DIVE_MS;

  // Transición de éxito: la red confirma y recién después se entra.
  useEffect(() => {
    if (!holdExit || !session) return;
    const timer = window.setTimeout(
      () => navigate(redirectAfterLogin(location.state), { replace: true }),
      holdMs
    );
    return () => window.clearTimeout(timer);
  }, [holdExit, session, navigate, location.state, holdMs]);

  if (session && !holdExit) return <Navigate to={redirectAfterLogin(location.state)} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    setHoldExit(true);
    emitNeuralEvent({ type: "submit" });
    try {
      const mfa = await login(email.trim(), password);
      if (mfa?.mfaRequired && mfa.mfaSession) {
        // Todavía no hay sesión: el segundo paso decide.
        setHoldExit(false);
        setMfaSession(mfa.mfaSession);
        setPassword("");
        emitNeuralEvent({ type: "focus", zone: null });
      } else {
        emitNeuralEvent({ type: "success" });
        armEntry({ reduced: quiet });
        emitNeuralEvent({ type: "dive" });
      }
    } catch (err) {
      setHoldExit(false);
      disarmEntry();
      emitNeuralEvent({ type: "error" });
      setError(err instanceof Error ? err.message : "No pudimos iniciar sesión.");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitMfa(e: FormEvent) {
    e.preventDefault();
    if (!mfaCode.trim()) return;
    setError("");
    setLoading(true);
    setHoldExit(true);
    emitNeuralEvent({ type: "submit" });
    try {
      await loginMfa(mfaSession, mfaCode.trim());
      emitNeuralEvent({ type: "success" });
      armEntry({ reduced: quiet });
      emitNeuralEvent({ type: "dive" });
    } catch (err) {
      setHoldExit(false);
      disarmEntry();
      emitNeuralEvent({ type: "error" });
      setError(err instanceof Error ? err.message : "El código no es válido o ya expiró.");
    } finally {
      setLoading(false);
    }
  }

  if (mfaSession) {
    return (
      <AuthShell
        variant="platform"
        kicker="Control Center"
        eyebrow="Verificación en dos pasos"
        title={
          <>
            Confirma tu{" "}
            <span className="auth-display__accent">identidad.</span>
          </>
        }
        subtitle="Ingresa el código de 6 dígitos de tu autenticador para entrar al Control Center."
        footer={
          <button
            type="button"
            className="auth-toggle inline-flex items-center gap-1.5 text-[13px]"
            onClick={() => {
              setMfaSession("");
              setMfaCode("");
              setError("");
              emitNeuralEvent({ type: "focus", zone: null });
            }}
          >
            <ArrowLeft size={14} weight="light" aria-hidden />
            Volver al inicio de sesión
          </button>
        }
      >
        <form className="flex flex-col gap-4" onSubmit={onSubmitMfa} noValidate>
          <ErrorInline message={error} className="auth-alert mb-0" />
          <motion.div {...reveal(0)}>
            <Field label="Código TOTP" required hint="Se renueva cada 30 segundos.">
              <Input
                id="admin-mfa"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/[^0-9]/g, ""))}
                placeholder="123456"
                className="mono text-center text-lg tracking-[0.4em]"
                required
                autoFocus
                disabled={succeeded}
              />
            </Field>
          </motion.div>
          <motion.div {...reveal(1)}>
            <AuthButton
              type="submit"
              icon={ShieldCheck}
              loading={loading && !succeeded}
              disabled={!mfaCode.trim()}
            >
              {succeeded ? "Acceso concedido" : "Verificar"}
            </AuthButton>
          </motion.div>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      variant="platform"
      kicker="Control Center"
      eyebrow="Acceso restringido"
      title={
        <>
          Acceso de{" "}
          <span className="auth-display__accent">plataforma.</span>
        </>
      }
      subtitle="Acceso exclusivo del personal de Omnio."
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        <ErrorInline message={error} className="auth-alert mb-0" />

        <motion.div {...reveal(0)}>
          <Field label="Email" required>
            <Input
              id="admin-email"
              type="email"
              autoComplete="username"
              placeholder="admin@zent.dev"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onFocus={() => emitNeuralEvent({ type: "focus", zone: "email" })}
              onBlur={() => emitNeuralEvent({ type: "focus", zone: null })}
              required
              autoFocus
              disabled={succeeded}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(1)}>
          <Field label="Contraseña" required>
            <PasswordInput
              id="admin-password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onFocus={() => emitNeuralEvent({ type: "focus", zone: "password" })}
              onBlur={() => emitNeuralEvent({ type: "focus", zone: null })}
              required
              disabled={succeeded}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(2)}>
          <AuthButton type="submit" icon={Key} loading={loading && !succeeded}>
            {succeeded ? "Acceso concedido" : "Entrar"}
          </AuthButton>
        </motion.div>

        {ssoEnabled && (
          <motion.div {...reveal(3)} className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="text-xs text-faint">o</span>
              <span className="h-px flex-1 bg-border" />
            </div>
            <a
              href="/api/v1/auth/platform/oidc/start"
              className="flex min-h-10 w-full items-center justify-center rounded-md border border-border bg-surface px-4 text-[13px] font-medium text-text transition-colors hover:border-border-strong hover:bg-soft"
            >
              Continuar con Zitadel
            </a>
            <p className="text-center text-[11px] text-faint">
              Usá tu cuenta de Omnio. No hace falta contraseña de Zent.
            </p>
          </motion.div>
        )}
      </form>
    </AuthShell>
  );
}
