/**
 * WorkflowHealthBar — resumen legible + checklist de readiness encima del
 * canvas (misión §19-§20). Solo lectura: no bloquea el motor; marca lo que
 * falta antes de publicar con lenguaje de negocio.
 */
import { CaretDown, CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Button, Popover } from "../ui";

type Check = {
  key: string;
  label: string;
  status: "ok" | "warning" | "error";
  message: string;
  hint?: string | null;
};

type Readiness = {
  ready: boolean;
  checks: Check[];
  errors: number;
  warnings: number;
};

type Summary = { text: string; when: string; steps: string[] };

type Props = {
  workflowId: string;
  /** Cambia cuando el grafo se guarda para refrescar el checklist. */
  refreshKey?: string | number;
  /** `chip`: indicador compacto de cabecera con el detalle en un popover. */
  variant?: "bar" | "chip";
};

function Icon({ status }: { status: Check["status"] }) {
  if (status === "ok") return <CheckCircle size={13} weight="fill" className="text-ok" aria-hidden />;
  if (status === "warning") return <Warning size={13} weight="fill" className="text-warn" aria-hidden />;
  return <XCircle size={13} weight="fill" className="text-danger" aria-hidden />;
}

export function WorkflowHealthBar({ workflowId, refreshKey, variant = "bar" }: Props) {
  const { session } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!session || !workflowId) return;
    let alive = true;
    Promise.all([
      api<Summary>(`/api/v1/workflows/${workflowId}/summary`, {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => null),
      api<Readiness>(`/api/v1/workflows/${workflowId}/readiness`, {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => null),
    ]).then(([s, r]) => {
      if (!alive) return;
      setSummary(s);
      setReadiness(r);
    });
    return () => {
      alive = false;
    };
  }, [session, workflowId, refreshKey]);

  if (!summary && !readiness) return null;
  const problems = (readiness?.checks ?? []).filter((c) => c.status !== "ok");
  const problemCount = (readiness?.errors ?? 0) + (readiness?.warnings ?? 0);
  const blocked = (readiness?.errors ?? 0) > 0;
  const readinessLabel = blocked
    ? "Requiere configuración"
    : (readiness?.warnings ?? 0) > 0
      ? "Revisión requerida"
      : readiness?.ready
        ? "Listo para publicar"
        : "Borrador incompleto";
  const needsMarketplace = problems.some((p) => (p.hint || "").includes("Marketplace"));

  if (variant === "chip") {
    const tone = blocked ? "text-danger" : problemCount > 0 ? "text-warn" : "text-ok";
    const ChipIcon = blocked ? XCircle : problemCount > 0 ? Warning : CheckCircle;
    return (
      <Popover
        align="start"
        width={420}
        trigger={
          <button
            type="button"
            className="inline-flex h-8 max-w-[14rem] cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 text-[12px] text-muted outline-none hover:border-border-strong hover:text-text focus-visible:ring-2 focus-visible:ring-accent"
            data-testid="wf-health-chip"
            aria-label={`Estado de preparación: ${readinessLabel}${problemCount ? `, ${problemCount} pendientes` : ""}`}
          >
            <ChipIcon size={14} weight="fill" className={`shrink-0 ${tone}`} aria-hidden />
            <span className="hidden truncate 2xl:inline">{readinessLabel}</span>
            {problemCount > 0 && <span className="tabular-nums">{problemCount}</span>}
          </button>
        }
      >
        <div className="space-y-2.5" data-testid="wf-health">
          {summary?.text && (
            <p className="text-[12px] leading-relaxed text-muted" data-testid="wf-summary-text">
              {summary.text}
            </p>
          )}
          {readiness && (
            <p className={`text-[12px] font-medium ${blocked ? "text-danger" : "text-text"}`} data-testid="wf-readiness-score">
              {readinessLabel}
            </p>
          )}
          <ul className="space-y-1.5" data-testid="wf-readiness-list">
            {(readiness?.checks ?? []).map((check) => (
              <li key={check.key} className="flex items-start gap-2 text-[12px] leading-relaxed" data-testid={`wf-check-${check.key}`}>
                <span className="mt-0.5 shrink-0">
                  <Icon status={check.status} />
                </span>
                <span className="min-w-0">
                  <span className="text-text">{check.label}</span>
                  {check.status !== "ok" && <span className="block text-muted">{check.message}</span>}
                  {check.status !== "ok" && check.hint && <span className="block text-faint">{check.hint}</span>}
                </span>
              </li>
            ))}
          </ul>
          {needsMarketplace && (
            <a href="/marketplace" className="text-[12px] text-accent underline-offset-2 hover:underline" data-testid="wf-readiness-resolve">
              Resolver en Marketplace
            </a>
          )}
        </div>
      </Popover>
    );
  }

  return (
    <section
      className="shrink-0 rounded-lg border border-border bg-surface px-3 py-2 shadow-panel"
      data-testid="wf-health"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-[14rem] flex-1 text-[12px] leading-relaxed text-muted" data-testid="wf-summary-text">
          {summary?.text}
        </p>
        {readiness && (
          <span
            className={`text-[11px] ${blocked ? "font-medium text-danger" : "text-muted"}`}
            data-testid="wf-readiness-score"
          >
            {readinessLabel}
          </span>
        )}
        <div className="flex flex-wrap items-center gap-1.5" data-testid="wf-readiness-chips">
          {(readiness?.checks ?? []).map((check) => (
            <span
              key={check.key}
              className="inline-flex items-center gap-1.5 rounded-sm bg-soft px-2 py-1 text-[11px] text-muted"
              title={`${check.label}: ${check.message}`}
              data-testid={`wf-check-${check.key}`}
            >
              <Icon status={check.status} />
              {check.label}
            </span>
          ))}
        </div>
        {problemCount > 0 ? (
          <>
            {needsMarketplace && (
              <a
                href="/marketplace"
                className="text-[11px] text-accent underline-offset-2 hover:underline"
                data-testid="wf-readiness-resolve"
              >
                Resolver en Marketplace
              </a>
            )}
            <Button
              variant="ghost"
              size="sm"
              leadingIcon={CaretDown}
              className="text-[11px] text-warn"
              data-testid="wf-readiness-toggle"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              {readiness?.errors ? `${readiness.errors} por resolver` : `${readiness?.warnings} por revisar`}
            </Button>
          </>
        ) : (
          readiness && (
            <span data-testid="wf-readiness-ready">
              <Badge tone="ok" icon={CheckCircle}>
                Listo para publicar
              </Badge>
            </span>
          )
        )}
      </div>

      {open && problems.length > 0 && (
        <ul className="mt-2 space-y-1.5 border-t border-border pt-2.5" data-testid="wf-readiness-list">
          {problems.map((check) => (
            <li key={check.key} className="flex items-start gap-2 text-[12px] leading-relaxed">
              <span className="mt-0.5 shrink-0">
                <Icon status={check.status} />
              </span>
              <span className="text-text">{check.message}</span>
              {check.hint && <span className="text-faint">{check.hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
