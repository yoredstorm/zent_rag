import { Info } from "@phosphor-icons/react";
import { Badge, IconButton, Popover, StatusBadge } from "../ui";

export function WorkflowTestHeader({
  embedded,
  status,
  dirty,
  saving,
  saveError,
}: {
  embedded: boolean;
  status: string;
  dirty: boolean;
  saving?: boolean;
  saveError?: string;
}) {
  const saveLabel = saving ? "Guardando…" : saveError ? "No se pudo guardar" : dirty ? "Se guardará antes de probar" : "";
  const saveTone = saveError ? "danger" : saving ? "info" : "warn";

  const info = (
    <div className="space-y-2 text-[12.5px] leading-relaxed text-muted">
      <p className="font-medium text-text">Qué hace este panel</p>
      <p>
        Ejecuta una prueba sobre el workflow. No lo publica ni cambia su versión. El servidor decide el
        nivel efectivo y devuelve el reporte.
      </p>
      <p>
        Una simulación no certifica proveedor real. Ejecutar el workflow con efectos es una acción
        distinta y requiere confirmación.
      </p>
    </div>
  );

  const infoButton = (
    <Popover
      trigger={<IconButton label="Qué hace esta prueba" icon={Info} iconSize={15} className="h-7 w-7 min-h-0" />}
      align="end"
      width={280}
    >
      {info}
    </Popover>
  );

  if (embedded) {
    return (
      <div className="flex flex-wrap items-center gap-2 px-3 pt-3" data-testid="wf-test-header">
        <StatusBadge status={status} />
        <span className="text-[12px] text-muted">Sin publicar</span>
        {saveLabel && <Badge tone={saveTone}>{saveLabel}</Badge>}
        <span className="ml-auto">{infoButton}</span>
      </div>
    );
  }

  return (
    <header className="panel-header flex items-start justify-between gap-3" data-testid="wf-test-header">
      <div className="min-w-0">
        <h2 className="text-h3">Probar automatización</h2>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <StatusBadge status={status} />
          <span className="text-[12px] text-muted">Sin publicar</span>
          {saveLabel && <Badge tone={saveTone}>{saveLabel}</Badge>}
        </div>
      </div>
      {infoButton}
    </header>
  );
}
