import { RocketLaunch } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { useAuth } from "../auth";
import { afterLoginPath } from "../api";
import { AuthShell } from "../components/auth/AuthShell";
import { AuthButton } from "../components/auth/AuthButton";
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
  const reduce = useReducedMotion();
  const reveal = useReveal({ step: 0.06 });
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (ready && session) return <Navigate to={afterLoginPath(session)} replace />;

  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && password !== confirm;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (password !== confirm) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setLoading(true);
    try {
      await signup(company.trim(), email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos crear el trial. Intentá de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Nuevo workspace"
      title="Crear tu workspace"
      subtitle="Empezá con un trial de Zent. Vas a configurar tu organización, conectar tus primeras fuentes y tener un agente respondiendo con tus datos."
      footer={
        <div className="text-[13px]">
          ¿Ya tenés cuenta?{" "}
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
              required
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
              required
              minLength={8}
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
              required
              minLength={8}
            />
          </Field>
        </motion.div>

        <motion.div {...reveal(4)} className="flex flex-col gap-2">
          <AuthButton type="submit" icon={RocketLaunch} loading={loading}>
            {loading ? "Creando tu workspace…" : "Empezar trial"}
          </AuthButton>
          <p className="text-xs leading-relaxed text-white/40">
            Al crear la cuenta aceptás los términos del servicio y la política de privacidad de
            Zent.
          </p>
        </motion.div>
      </form>
    </AuthShell>
  );
}
