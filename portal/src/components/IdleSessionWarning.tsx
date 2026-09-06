import { useIdleWarning } from "../lib/session";

/**
 * Aviso de sesión inactiva (FASE 06). Cualquier actividad (o el botón)
 * resetea el contador; si llega a 0, se ejecuta el logout.
 */
export function IdleSessionWarning({
  minutes,
  onLogout,
}: {
  minutes: number;
  onLogout: () => void;
}) {
  const { remaining, show } = useIdleWarning(minutes, onLogout);
  if (!show) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="alertdialog" aria-modal="true" aria-label="Sesión inactiva">
      <div className="absolute inset-0 bg-black/60" aria-hidden />
      <div className="relative w-full max-w-sm rounded-md border border-border bg-surface p-5 shadow-pop">
        <h2 className="text-base font-semibold text-text">Sesión inactiva</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Tu sesión expirará por inactividad en <span className="mono font-medium text-text">{Math.max(remaining, 0)}s</span>.
          Continúa trabajando para mantenerla activa.
        </p>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            className="btn btn-primary min-h-10"
            onClick={() => {
              // Cualquier interacción resetea el contador de actividad.
            }}
          >
            Continuar
          </button>
        </div>
      </div>
    </div>
  );
}