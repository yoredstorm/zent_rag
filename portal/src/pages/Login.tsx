import { CaretRight, CheckCircle, SignIn } from "@phosphor-icons/react";
import { AnimatePresence, motion, useAnimation, useReducedMotion } from "motion/react";
import { FormEvent, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, afterLoginPath } from "../api";
import { useAuth } from "../auth";
import { usePlatformAuth } from "../platformAuth";
import { AuthShell } from "../components/auth/AuthShell";
import { Button } from "../components/ui/Button";
import { ErrorInline, SuccessInline } from "../components/ui/states";
import { Field, Input, PasswordInput } from "../components/ui/form";

/** Ritmo de entrada: encabezado → campos → CTA → enlaces. */
const STAGGER = 0.06;

/**
 * Mensajes del backend traducidos a algo que una persona pueda leer. El código
 * crudo (`invalid_credentials Invalid email or password.`) no le dice nada a
 * quien está entrando; el resto de los errores se muestran tal cual porque ya
 * vienen redactados.
 */
const MENSAJES: Record<string, string> = {
  invalid_credentials: "Email o contraseña incorrectos. Revisá los datos e intentá de nuevo.",
  unauthorized: "Email o contraseña incorrectos. Revisá los datos e intentá de nuevo.",
  invalid_email: "Ese email no parece válido. Corregilo y probá otra vez.",
  too_many_requests: "Demasiados intentos seguidos. Esperá un momento y volvé a probar.",
  rate_limited: "Demasiados intentos seguidos. Esperá un momento y volvé a probar.",
  organization_inactive: "La organización está inactiva. Contactá al administrador de tu cuenta.",
};

function mensajeDeError(raw: string): string {
  const codigo = raw.trim().split(/[\s:]/)[0]?.toLowerCase() ?? "";
  return MENSAJES[codigo] ?? raw;
}

export default function LoginPage() {
  const { session, ready, login } = useAuth();
  const { login: platformLogin } = usePlatformAuth();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const formRef = useRef<HTMLFormElement>(null);
  const nudge = useAnimation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotMsg, setForgotMsg] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);

  const emailReady = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim());

  if (ready && session) return <Navigate to={afterLoginPath(session)} replace />;

  /** Avisa sin castigar: el error entra con un resorte y el formulario se mueve. */
  function fail(message: string, focusId?: string) {
    setError(message);
    if (focusId) formRef.current?.querySelector<HTMLInputElement>(`#${focusId}`)?.focus();
    if (!reduce) void nudge.start({ x: [0, -6, 6, -3, 0] }, { duration: 0.34, ease: "easeOut" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      fail("Completá tu email y contraseña para entrar.", email.trim() ? "password" : "email");
      return;
    }
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
          fail(
            platformErr instanceof Error
              ? platformErr.message
              : "Esta cuenta es de plataforma. Entrá por el Control Center."
          );
          return;
        }
      }
      fail(
        msg
          ? mensajeDeError(msg)
          : "No pudimos iniciar sesión. Revisá tus credenciales e intentá de nuevo."
      );
    } finally {
      setLoading(false);
    }
  }

  async function onForgot() {
    setForgotMsg("");
    setError("");
    if (!email.trim()) {
      fail("Escribí tu email y te enviamos el enlace.", "email");
      return;
    }
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
      const raw = err instanceof Error ? err.message : "";
      setError(
        raw
          ? mensajeDeError(raw)
          : "No pudimos enviar el enlace de restablecimiento."
      );
    } finally {
      setForgotLoading(false);
    }
  }

  /** Entrada escalonada: el formulario se compone en orden, sin saltos. */
  function rise(index: number) {
    return {
      initial: reduce ? { opacity: 0 } : { opacity: 0, y: 10 },
      animate: { opacity: 1, y: 0 },
      transition: {
        type: "spring" as const,
        bounce: 0,
        duration: 0.5,
        delay: reduce ? 0 : 0.06 + index * STAGGER,
      },
    };
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
      <form ref={formRef} className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        <AnimatePresence initial={false}>
          {error && (
            <motion.div
              key={error}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.99 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, y: -4, scale: 0.99 }}
              transition={{ type: "spring", bounce: 0, duration: 0.34 }}
            >
              <ErrorInline message={error} className="mb-0" />
            </motion.div>
          )}
        </AnimatePresence>

        {/* El contenido se mueve junto cuando el error aparece: el nudge hace
            visible la causa sin sacar el foco del campo. */}
        <motion.div className="flex flex-col gap-4" animate={nudge} initial={false}>
          <motion.div {...rise(0)}>
            <Field id="email" label="Email" required>
              <span className="relative block">
                <Input
                  type="email"
                  autoComplete="username"
                  placeholder="tu@empresa.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  disabled={loading}
                  className={emailReady ? "pr-8" : undefined}
                />
                {/* Validación viva: confirma el formato apenas está listo, sin
                    bloquear el envío ni adelantarse al backend. */}
                <AnimatePresence initial={false}>
                  {emailReady && (
                    <motion.span
                      key="ok"
                      className="pointer-events-none absolute top-1/2 right-2.5 inline-flex -translate-y-1/2 text-ok"
                      initial={{ opacity: 0, scale: 0.6 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.6 }}
                      transition={{ type: "spring", bounce: 0, duration: 0.3 }}
                      aria-hidden
                    >
                      <CheckCircle size={15} weight="fill" />
                    </motion.span>
                  )}
                </AnimatePresence>
              </span>
            </Field>
          </motion.div>

          <motion.div {...rise(1)}>
            <Field id="password" label="Contraseña" required>
              <PasswordInput
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
              />
            </Field>
          </motion.div>

          <motion.div {...rise(2)} className="flex flex-col gap-2">
            <Button
              type="submit"
              variant="primary"
              className="auth-cta min-h-10 w-full"
              loading={loading}
            >
              {loading ? "Entrando…" : "Continuar"}
            </Button>
            <AnimatePresence initial={false}>
              {loading && (
                <motion.div
                  key="progress"
                  className="auth-progress"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.16, ease: "easeOut" }}
                  role="status"
                  aria-label="Verificando credenciales"
                />
              )}
            </AnimatePresence>
          </motion.div>

          <motion.div {...rise(3)}>
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 text-[13px] font-medium text-muted transition-colors duration-150 hover:text-text"
              aria-expanded={forgotOpen}
              aria-controls="forgot-panel"
              onClick={() => {
                setForgotOpen((v) => !v);
                setForgotMsg("");
              }}
            >
              Olvidé mi contraseña
              <motion.span
                className="inline-flex"
                animate={{ rotate: forgotOpen ? 90 : 0 }}
                transition={{ type: "spring", bounce: 0, duration: 0.32 }}
                aria-hidden
              >
                <CaretRight size={12} weight="bold" />
              </motion.span>
            </button>
            <AnimatePresence initial={false}>
              {forgotOpen && (
                <motion.div
                  id="forgot-panel"
                  className="overflow-hidden"
                  initial={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
                  animate={reduce ? { opacity: 1 } : { height: "auto", opacity: 1 }}
                  exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
                  transition={{ type: "spring", bounce: 0, duration: 0.4 }}
                >
                  <div className="flex flex-col gap-2.5 pt-3">
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
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      </form>
    </AuthShell>
  );
}
