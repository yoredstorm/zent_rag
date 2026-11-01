import { Badge, KeyValue } from "../ui";
import { classifyPlannedEffects, effectLabel } from "../../lib/workflowEffects";
import type { RunDetail } from "../WorkflowRunInspector";
import {
  cappedReasonLabel,
  LEVEL_LABEL,
  normalizeLevel,
  providerSummary,
  requestedEffectiveSentence,
} from "./workflowTestPresentation";
import type { RunOut, TestReportOut } from "./workflowTestTypes";

export function WorkflowTestVerification({
  report,
  run,
  plannedEffects,
  providerVerified,
  effectLabels = [],
}: {
  report: TestReportOut | null;
  run: RunDetail | null;
  plannedEffects?: RunOut["planned_effects"];
  providerVerified: boolean;
  effectLabels?: string[];
}) {
  if (!report && !run) {
    return (
      <p className="rounded-md border border-border bg-raised/40 px-3 py-2 text-[12px] text-muted">
        Sin datos de verificación todavía.
      </p>
    );
  }

  if (!report && run) {
    const verification = run.effect_verification ?? classifyPlannedEffects(run.planned_effects ?? plannedEffects);
    return (
      <div className="space-y-3" data-testid="wf-test-verification">
        <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
          <p className="text-[12px] font-medium text-text">Ejecución real</p>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Esta corrida no pasó por el Test Studio. No emite certificación de proveedor.
          </p>
        </div>
        <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
          <p className="text-[12px] font-medium text-text">Efectos observados</p>
          <VerificationList verification={verification} graphEffectLabels={effectLabels} />
        </div>
      </div>
    );
  }

  const effective = report ? normalizeLevel(report.effective_level) : null;
  const requested = report ? normalizeLevel(report.requested_level) : null;
  const provider = providerSummary(report);
  const verification = run?.effect_verification ?? classifyPlannedEffects(run?.planned_effects ?? plannedEffects);

  return (
    <div className="space-y-3" data-testid="wf-test-verification">
      <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
        <KeyValue
          items={[
            { key: "Solicitado", value: requested ? LEVEL_LABEL[requested] : "No disponible" },
            { key: "Ejecutado", value: effective ? LEVEL_LABEL[effective] : "No disponible" },
            { key: "Resultado", value: String(report?.result ?? "No disponible"), mono: true },
            {
              key: "Proveedor verificado",
              value: providerVerified ? "Sí, según backend" : "No",
            },
          ]}
        />
        {report && requested !== effective && (
          <p className="mt-2 text-[11.5px] leading-relaxed text-warn">
            {requestedEffectiveSentence(report)}{" "}
            {cappedReasonLabel(report.capped_reason)}
          </p>
        )}
      </div>

      <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[12px] font-medium text-text">Proveedor</p>
          <Badge tone={provider.tone}>{provider.label}</Badge>
        </div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{provider.detail}</p>
        <p className="mt-1 text-[11px] text-faint">
          Proveedor conectado, proveedor usado, reporte verificado y workflow publicado son estados
          distintos.
        </p>
      </div>

      <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
        <p className="text-[12px] font-medium text-text">Efectos planeados y verificados</p>
        <VerificationList verification={verification} graphEffectLabels={effectLabels} />
      </div>

      {report?.readiness?.reasons && report.readiness.reasons.length > 0 && (
        <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
          <p className="text-[12px] font-medium text-text">Motivos de disponibilidad</p>
          <ul className="mt-1 space-y-1 text-[11.5px] leading-relaxed text-muted">
            {report.readiness.reasons.slice(0, 6).map((reason) => (
              <li key={reason}>{cappedReasonLabel(reason)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function VerificationList({
  verification,
  graphEffectLabels = [],
}: {
  verification: ReturnType<typeof classifyPlannedEffects>;
  graphEffectLabels?: string[];
}) {
  if (verification.level === "NONE") {
    return (
      <div className="mt-1 text-[11.5px] text-muted">
        <p>Sin efectos externos planificados en el reporte.</p>
        {graphEffectLabels.length > 0 && (
          <p className="mt-0.5 text-warn">
            El grafo actual declara: {graphEffectLabels.join(", ")}. Vuelve a ejecutar para verificarlos.
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="mt-1.5 space-y-2">
      <div className="flex items-center gap-2">
        <Badge tone={verification.level === "UNVERIFIED" ? "warn" : verification.level === "DECLARED" ? "warn" : "info"}>
          {verification.level}
        </Badge>
        <span className="text-[11px] text-muted">Clasificación del reporte o del run.</span>
      </div>
      {verification.unverified.length > 0 && <EffectGroup title="Sin doble" items={verification.unverified} />}
      {verification.declared.length > 0 && <EffectGroup title="Fijados / declarados" items={verification.declared} />}
      {verification.simulated.length > 0 && <EffectGroup title="Simulados" items={verification.simulated} />}
    </div>
  );
}

function EffectGroup({
  title,
  items,
}: {
  title: string;
  items: { node_id: string; node_type?: string; label?: string }[];
}) {
  return (
    <div>
      <p className="text-[11px] font-medium text-muted">{title}</p>
      <ul className="mt-0.5 space-y-0.5">
        {items.map((item) => (
          <li key={`${title}-${item.node_id}`} className="truncate text-[11.5px] text-faint">
            <span className="text-muted">{effectLabel(item)}</span>
            {item.node_type ? ` — ${item.node_type}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
