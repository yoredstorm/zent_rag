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

      <div className="space-y-1.5" data-testid="wf-real-actions">
        <Button
          variant="danger"
          size="sm"
          leadingIcon={Lightning}
          className="w-full"
          disabled={busy || !hasInput}
          onClick={onRealRun}
          data-testid="wf-run"
        >
          Ejecutar con efectos reales
        </Button>
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-faint">
          <Warning size={12} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            No es una prueba. Aplica cambios reales, pide confirmación y no se puede deshacer desde
            esta pantalla.
          </span>
        </p>
        {effectLabels.length > 0 && (
          <p className="text-[11px] leading-relaxed text-warn">
            {effectLabels.length} nodo(s) con efectos: {effectLabels.join(", ")}.
          </p>
        )}
      </div>
    </footer>
  );
}
