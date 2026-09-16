import {
  CheckCircle,
  Clock,
  Fingerprint,
  Info,
  Minus,
  Question,
  Scales,
  SealCheck,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
  type Tone,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { organizations_governing: number; audit_entries: number; decisions_by_status: { status: string; count: number }[]; certifications: { certification: string; count: number }[]; recent_audit: { actor: string; action: string; detail: string; created_at: string }[] };

/** Estado de una decisión de gobierno: pendiente / aprobada / rechazada. */
const DECISION_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  pending: { label: "Pendiente", tone: "warn", icon: Clock },
  approved: { label: "Aprobada", tone: "ok", icon: CheckCircle },
  rejected: { label: "Rechazada", tone: "danger", icon: XCircle },
  escalated: { label: "Escalada", tone: "info", icon: Info },
  revoked: { label: "Revocada", tone: "neutral", icon: Minus },
};

function DecisionStatusBadge({ status }: { status: string }) {
  const meta = DECISION_STATUS_META[status] ?? {
    label: status || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

export default function AdminGovernancePage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/governance/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const decisionsTotal = (dash?.decisions_by_status ?? []).reduce((n, d) => n + d.count, 0);
  const certsTotal = (dash?.certifications ?? []).reduce((n, c) => n + c.count, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="AI Governance"
        subtitle="Juntas de gobierno en todas las organizaciones: políticas, decisiones y auditoría."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid cols={4}>
            <Metric label="Orgs con políticas" value={dash?.organizations_governing ?? 0} hint="Gobierno activo" />
            <Metric label="Entradas de auditoría" value={dash?.audit_entries ?? 0} size="md" />
            <Metric label="Decisiones" value={decisionsTotal} size="md" hint={(dash?.decisions_by_status ?? []).length ? `${(dash?.decisions_by_status ?? []).length} estados en uso` : undefined} />
            <Metric label="Certificaciones" value={certsTotal} size="md" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="flex flex-col gap-4">
              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <Scales size={15} className="text-faint" aria-hidden />
                      Decisiones por estado
                    </span>
                  }
                />
                <ul className="divide-y divide-border-soft">
                  {(dash?.decisions_by_status ?? []).map((d) => (
                    <li key={d.status} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <DecisionStatusBadge status={d.status} />
                      <span className="mono text-xs text-faint tabular-nums">{d.count}</span>
                    </li>
                  ))}
                  {(dash?.decisions_by_status ?? []).length === 0 && (
                    <li className="px-4 py-3 text-[13px] text-muted">Sin decisiones.</li>
                  )}
                </ul>
              </Panel>

              <Panel>
                <PanelHeader title="Certificaciones vigentes" />
                <ul className="divide-y divide-border-soft">
                  {(dash?.certifications ?? []).map((c) => (
                    <li key={c.certification} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <span className="flex min-w-0 items-center gap-2 text-xs text-text">
                        <SealCheck size={13} className="shrink-0 text-ok" aria-hidden />
                        <span className="truncate" title={c.certification}>
                          {c.certification}
                        </span>
                      </span>
                      <span className="mono shrink-0 text-xs text-faint tabular-nums">{c.count}</span>
                    </li>
                  ))}
                  {(dash?.certifications ?? []).length === 0 && (
                    <li className="px-4 py-3 text-[13px] text-muted">Sin certificaciones.</li>
                  )}
                </ul>
              </Panel>
            </div>

            <Panel className="lg:col-span-2">
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <Fingerprint size={15} className="text-faint" aria-hidden />
                    Auditoría reciente
                  </span>
                }
                description="Últimas acciones registradas por el gobierno."
              />
              {(dash?.recent_audit ?? []).length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted">Sin actividad de auditoría.</p>
              ) : (
                <ul className="px-4 py-1">
                  {(dash?.recent_audit ?? []).map((a, i) => (
                    <li
                      key={`${a.actor}-${a.created_at}-${i}`}
                      className="state-rail flex items-center gap-3 py-2.5"
                      data-state="ready"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                          <span className="text-[13px] font-medium text-text">{a.actor}</span>
                          <span className="mono text-xs text-muted">{a.action}</span>
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-faint" title={a.detail}>
                          {a.detail || "—"}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs text-faint tabular-nums">{fmtDateTime(a.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
