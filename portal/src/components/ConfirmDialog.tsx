import { useEffect, useRef } from "react";
import { WarningCircle, X } from "@phosphor-icons/react";
import type { ReactNode } from "react";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "default";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Diálogo de confirmación con focus trap y Escape. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  tone = "danger",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables || focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} aria-hidden />
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="relative w-full max-w-md rounded-md border border-border bg-surface p-5 shadow-pop"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            {tone === "danger" && (
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-danger/25 bg-danger-soft text-danger">
                <WarningCircle size={17} aria-hidden />
              </span>
            )}
            <h2 id="confirm-dialog-title" className="text-base font-semibold text-text">
              {title}
            </h2>
          </div>
          <button
            type="button"
            className="btn btn-ghost min-h-8 min-w-8 px-1"
            aria-label="Cerrar"
            onClick={onCancel}
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className="mt-3 text-sm leading-relaxed text-muted">{body}</div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" className="btn btn-secondary min-h-10" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={tone === "danger" ? "btn btn-danger min-h-10" : "btn btn-primary min-h-10"}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Procesando…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}