/**
 * WorkflowHealthBar — resumen legible + checklist de readiness encima del
 * canvas (misión §19-§20). Solo lectura: no bloquea el motor; marca lo que
 * falta antes de publicar con lenguaje de negocio.
 */
import { CaretDown, CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Button } from "../ui";

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
  if (status === "ok") return <CheckCircle size={13} weight="fill" className="text-ok" aria-hidden />;
  if (status === "warning") return <Warning size={13} weight="fill" className="text-warn" aria-hidden />;
  return <XCircle size={13} weight="fill" className="text-danger" aria-hidden />;
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
    <section
      className="shrink-0 rounded-lg border border-border bg-surface px-3 py-2 shadow-panel"
      data-testid="wf-health"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-[14rem] flex-1 text-[12px] leading-relaxed text-muted" data-testid="wf-summary-text">
          {summary?.text}
        </p>
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
