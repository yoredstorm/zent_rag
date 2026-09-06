import { ShieldCheck, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { STEP_UP_REQUIRED_EVENT } from "../lib/errors";
import { usePlatformAuth } from "../platformAuth";
import { Spinner } from "./ui";

/**
 * FASE 08 — Step-up: cuando una operación crítica devuelve 403
 * `step_up_required`, este modal pide el código TOTP y renueva la sesión
 * (la página se recarga para reintentar la operación con assurance fresca).
 */
export function StepUpModal() {
  const { stepUp } = usePlatformAuth();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    function onStepUpRequired() {
      setOpen(true);
      setError("");
      setCode("");
    }
    window.addEventListener(STEP_UP_REQUIRED_EVENT, onStepUpRequired);
    return () => window.removeEventListener(STEP_UP_REQUIRED_EVENT, onStepUpRequired);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  async function confirm() {
    if (!code.trim()) return;
    setBusy(true);
    setError("");
    try {
      await stepUp(code.trim());
      // Recarga para reintentar la operación con la sesión elevada.
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Código inválido");
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="alertdialog" aria-modal="true" aria-label="Confirmar con MFA">
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} aria-hidden />
      <div className="relative w-full max-w-sm rounded-md border border-border bg-surface p-5 shadow-pop">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-accent/25 bg-accent-soft text-accent">
              <ShieldCheck size={17} aria-hidden />
            </span>
            <div>
              <h2 className="text-base font-semibold text-text">Confirmación MFA</h2>
              <p className="mt-1 text-[13px] text-muted">
                Esta operación es crítica. Ingresa el código de tu autenticador para continuar.
              </p>
            </div>
          </div>
          <button type="button" className="btn btn-ghost min-h-8 min-w-8 px-1" aria-label="Cerrar" onClick={() => setOpen(false)}>
            <X size={16} aria-hidden />
          </button>
        </div>
        <label className="mt-4 block">
          <span className="mb-1 block text-[13px] text-muted">Código TOTP</span>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
            className="w-full rounded-md border border-border bg-soft px-3 py-2 font-mono text-lg tracking-[0.4em] text-text outline-none focus:border-accent"
            placeholder="••••••"
          />
        </label>
        {error && <p className="mt-2 text-[13px] text-danger" role="alert">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn btn-secondary min-h-10" onClick={() => setOpen(false)}>
            Cancelar
          </button>
          <button type="button" className="btn btn-primary min-h-10" disabled={!code.trim() || busy} onClick={() => void confirm()}>
            {busy ? <Spinner size={14} /> : "Confirmar"}
          </button>
        </div>
      </div>
    </div>
  );
}