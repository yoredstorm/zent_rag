import { ArrowRight, Lightning, Warning } from "@phosphor-icons/react";
import { Button } from "../ui";

export function WorkflowTestFooter({
  ctaLabel,
  ctaDisabled,
  busy,
  hasInput,
  effectLabels,
  onTest,
  onRealRun,
}: {
  ctaLabel: string;
  ctaDisabled: boolean;
  busy: boolean;
  hasInput: boolean;
  effectLabels: string[];
  onTest: () => void;
  onRealRun: () => void;
}) {
  return (
    <footer className="space-y-2 border-t border-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <Button
        variant="primary"
        className="min-h-11 w-full"
        loading={busy}
        trailingIcon={ArrowRight}
        disabled={ctaDisabled}
        onClick={onTest}
        data-testid="wf-test"
        aria-label={ctaLabel}
      >
        {ctaLabel}
      </Button>

      <details className="group" data-testid="wf-more-actions">
        <summary className="flex cursor-pointer items-center gap-1.5 text-[11.5px] font-medium text-muted select-none">
          <Warning size={13} aria-hidden />
          Más acciones
        </summary>
        <div className="mt-2 space-y-1.5">
          <Button
            variant="danger"
            size="sm"
            leadingIcon={Lightning}
            disabled={busy || !hasInput}
            onClick={onRealRun}
            data-testid="wf-run"
          >
            Ejecutar workflow con efectos reales
          </Button>
          <p className="text-[11px] leading-relaxed text-faint">
            No es una prueba. Ejecuta la operación real y puede disparar efectos externos. Requiere
            permiso, confirmación y no se puede deshacer desde esta pantalla.
          </p>
          {effectLabels.length > 0 && (
            <p className="text-[11px] leading-relaxed text-warn">
              {effectLabels.length} nodo(s) con efectos: {effectLabels.join(", ")}.
            </p>
          )}
        </div>
      </details>
    </footer>
  );
}
