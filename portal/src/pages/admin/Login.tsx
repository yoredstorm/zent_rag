import { ArrowLeft, Key, ShieldCheck } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { usePlatformAuth } from "../../platformAuth";
import { AuthShell } from "../../components/auth/AuthShell";
import { AuthButton } from "../../components/auth/AuthButton";
import { emitNeuralEvent } from "../../components/auth/neuralSignal";
import { useReveal } from "../../components/auth/reveal";
import { ErrorInline } from "../../components/ui/states";
import { Field, Input, PasswordInput } from "../../components/ui/form";

/** Cuánto se sostiene la confirmación antes de entrar al Control Center. */
const SUCCESS_HOLD_MS = 620;

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
  const reveal = useReveal({ step: 0.06 });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaSession, setMfaSession] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [holdExit, setHoldExit] = useState(false);

  const succeeded = holdExit && Boolean(session);

  // Transición de éxito: la red confirma y recién después se entra.
  useEffect(() => {
    if (!holdExit || !session) return;
    const timer = window.setTimeout(
      () => navigate(redirectAfterLogin(location.state), { replace: true }),
      SUCCESS_HOLD_MS
    );
    return () => window.clearTimeout(timer);
  }, [holdExit, session, navigate, location.state]);

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
      }
    } catch (err) {
      setHoldExit(false);
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
    } catch (err) {
      setHoldExit(false);
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
            Confirmá tu{" "}
            <span className="auth-display__accent">identidad.</span>
          </>
        }
        subtitle="Ingresá el código de 6 dígitos de tu autenticador para entrar al Control Center."
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
      subtitle="Si sos dueño de una organización, entrá por el portal de clientes."
      footer={
        <div className="text-[13px]">
          <Link className="auth-link" to="/login">
            Portal de clientes
          </Link>
        </div>
      }
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
      </form>
    </AuthShell>
  );
}
