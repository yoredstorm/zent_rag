import { RocketLaunch } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { useAuth } from "../auth";
import { afterLoginPath } from "../api";
import { AuthShell } from "../components/auth/AuthShell";
import { AuthButton } from "../components/auth/AuthButton";
import { DIVE_MS, DIVE_REDUCED_MS, armEntry, disarmEntry } from "../components/auth/entryTransit";
import { useDiveEffect } from "../components/auth/useDiveEffect";
import { emitNeuralEvent } from "../components/auth/neuralSignal";
import { useReveal } from "../components/auth/reveal";
import { Field, Input, PasswordInput } from "../components/ui/form";
import { Progress } from "../components/ui/states";

function passwordStrength(pw: string): { label: string; pct: number; tone: "danger" | "warn" | "ok" } {
  if (pw.length === 0) return { label: "", pct: 0, tone: "danger" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 1) return { label: "Débil", pct: 25, tone: "danger" };
  if (score <= 3) return { label: "Aceptable", pct: 60, tone: "warn" };
  return { label: "Fuerte", pct: 100, tone: "ok" };
}

export default function SignupPage() {
  const { session, ready, signup } = useAuth();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const { quiet } = useDiveEffect();
  const reveal = useReveal({ step: 0.06 });
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [holdExit, setHoldExit] = useState(false);

  const succeeded = holdExit && Boolean(session);
  const busy = loading || succeeded;
  // La travesía neuronal manda el tiempo: se entra cuando el zoom termina.
  const holdMs = quiet ? DIVE_REDUCED_MS : DIVE_MS;

  useEffect(() => {
    if (!holdExit || !session) return;
    const timer = window.setTimeout(
      () => navigate(afterLoginPath(session), { replace: true }),
      holdMs
    );
    return () => window.clearTimeout(timer);
  }, [holdExit, session, navigate, holdMs]);

  if (ready && session && !holdExit) return <Navigate to={afterLoginPath(session)} replace />;

  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && password !== confirm;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      emitNeuralEvent({ type: "error" });
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (password !== confirm) {
      emitNeuralEvent({ type: "error" });
      setError("Las contraseñas no coinciden.");
      return;
    }
    setLoading(true);
    setHoldExit(true);
    emitNeuralEvent({ type: "submit" });
    try {
      await signup(company.trim(), email.trim(), password);
      emitNeuralEvent({ type: "success" });
      armEntry({ reduced: quiet });
      emitNeuralEvent({ type: "dive" });
    } catch (err) {
      setHoldExit(false);
      disarmEntry();
      emitNeuralEvent({ type: "error" });
      setError(err instanceof Error ? err.message : "No pudimos crear el trial. Intenta de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      kicker="Nuevo workspace"
      eyebrow="Alta de cuenta"
      title={
        <>
          Crea tu{" "}
          <span className="auth-display__accent">workspace.</span>
        </>
      }
      subtitle="Trial de Zent: conecta tus primeras fuentes y ten un agente respondiendo con tus datos."
      footer={
        <div className="text-[13px]">
          ¿Ya tienes cuenta?{" "}
          <Link className="auth-link" to="/login">
            Iniciar sesión
          </Link>
        </div>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        {error && (
          <motion.p
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.34 }}
            className="auth-alert rounded-xl border px-3 py-2.5 text-sm"
            role="alert"
          >
            {error}
          </motion.p>
        )}

        <motion.div {...reveal(0)}>
          <Field label="Nombre de empresa" required hint="Así va a aparecer en tu workspace.">
            <Input
              id="company"
              placeholder="Mi empresa S.A.C."
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
              autoFocus
              disabled={busy}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(1)}>
          <Field label="Email" required>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="tu@empresa.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onFocus={() => emitNeuralEvent({ type: "focus", zone: "email" })}
              onBlur={() => emitNeuralEvent({ type: "focus", zone: null })}
              required
              disabled={busy}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(2)}>
          <Field label="Contraseña" required>
            <PasswordInput
              id="password"
              autoComplete="new-password"
              placeholder="Mínimo 8 caracteres"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onFocus={() => emitNeuralEvent({ type: "focus", zone: "password" })}
              onBlur={() => emitNeuralEvent({ type: "focus", zone: null })}
              required
              minLength={8}
              disabled={busy}
            />
            {password.length > 0 && (
              <div className="mt-0.5 flex items-center gap-2" aria-live="polite">
                <Progress
                  value={strength.pct}
                  tone={strength.tone}
                  className="flex-1"
                  label="Seguridad de la contraseña"
                />
                <span className="text-[11px] text-white/45">{strength.label}</span>
              </div>
            )}
          </Field>
        </motion.div>

        <motion.div {...reveal(3)}>
          <Field
            label="Confirmar contraseña"
            required
            error={mismatch ? "Las contraseñas no coinciden" : undefined}
          >
            <PasswordInput
              id="confirm"
              autoComplete="new-password"
              placeholder="Repetí la contraseña"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              onFocus={() => emitNeuralEvent({ type: "focus", zone: "password" })}
              onBlur={() => emitNeuralEvent({ type: "focus", zone: null })}
              required
              minLength={8}
              disabled={busy}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(4)} className="flex flex-col gap-2">
          <AuthButton type="submit" icon={RocketLaunch} loading={loading && !succeeded}>
            {succeeded ? "Workspace listo" : loading ? "Creando tu workspace…" : "Empezar trial"}
          </AuthButton>
          <p className="text-xs leading-relaxed text-white/40">
            Al crear la cuenta aceptas los términos del servicio y la política de privacidad de
            Zent.
          </p>
        </motion.div>
      </form>
    </AuthShell>
  );
}
