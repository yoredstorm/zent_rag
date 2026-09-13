/**
 * WorkflowHealthBar — resumen legible + checklist de readiness encima del
 * canvas (misión §19-§20). Solo lectura: no bloquea el motor; marca lo que
 * falta antes de publicar con lenguaje de negocio.
 */
import { CaretDown, CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";

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
};

function Icon({ status }: { status: Check["status"] }) {
  if (status === "ok") return <CheckCircle size={13} className="text-ok" aria-hidden />;
  if (status === "warning") return <Warning size={13} className="text-warn" aria-hidden />;
  return <XCircle size={13} className="text-danger" aria-hidden />;
}

export function WorkflowHealthBar({ workflowId, refreshKey }: Props) {
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
  const problems = readiness?.checks.filter((c) => c.status !== "ok") ?? [];
  const problemCount = (readiness?.errors ?? 0) + (readiness?.warnings ?? 0);

  return (
    <section className="shrink-0 rounded-lg border border-border bg-surface px-3 py-2" data-testid="wf-health">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-[14rem] flex-1 text-[11px] text-muted" data-testid="wf-summary-text">
          {summary?.text}
        </p>
        <div className="flex items-center gap-1.5" data-testid="wf-readiness-chips">
          {(readiness?.checks ?? []).map((check) => (
            <span
              key={check.key}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-soft px-1.5 py-0.5 text-[9px] text-muted"
              title={`${check.label}: ${check.message}`}
              data-testid={`wf-check-${check.key}`}
            >
              <Icon status={check.status} />
              {check.label}
            </span>
          ))}
        </div>
        {problemCount > 0 ? (
          <button
            type="button"
            className="btn btn-ghost min-h-7 gap-1 px-1.5 text-[10px] text-warn"
            data-testid="wf-readiness-toggle"
            onClick={() => setOpen((v) => !v)}
          >
            <CaretDown size={11} aria-hidden />
            {readiness?.errors ? `${readiness.errors} por resolver` : `${readiness?.warnings} por revisar`}
          </button>
        ) : (
          readiness && (
            <span className="badge badge-ok" data-testid="wf-readiness-ready">
              Listo para publicar
            </span>
          )
        )}
      </div>

      {open && problems.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-border pt-2" data-testid="wf-readiness-list">
          {problems.map((check) => (
            <li key={check.key} className="flex items-start gap-1.5 text-[10px]">
              <span className="mt-0.5">
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
