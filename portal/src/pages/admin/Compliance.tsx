import {
  CheckCircle,
  Clock,
  LinkBreak,
  LinkSimple,
  Minus,
  ShieldCheck,
  XCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Drawer,
  ErrorInline,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  ResultCount,
  Select,
  DataTable,
  SkeletonBlock,
  Toolbar,
  type Column,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Framework = { framework: string; pass: number; fail: number; review: number; na: number; score: number; controls: number };

type Report = {
  id: string;
  organization_id: string;
  report_type: string;
  format: string;
  integrity_hash: string;
  prev_hash: string | null;
  created_at: string;
};

const REPORT_COLUMNS: Column<Report>[] = [
  {
    key: "created_at",
    header: "Fecha",
    render: (r) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(r.created_at)}</span>,
    width: "160px",
  },
  {
    key: "organization_id",
    header: "Org",
    render: (r) => (
      <span className="mono text-xs text-muted" title={r.organization_id}>
        {r.organization_id.slice(0, 8)}
      </span>
    ),
  },
  {
    key: "report_type",
    header: "Tipo",
    render: (r) => <span className="mono text-xs text-text">{r.report_type}</span>,
  },
  {
    key: "format",
    header: "Formato",
    hideBelow: "md",
    render: (r) => <span className="text-xs uppercase text-muted">{r.format}</span>,
  },
  {
    key: "integrity_hash",
    header: "Hash",
    hideBelow: "lg",
    render: (r) => (
      <span className="mono text-xs text-faint" title={r.integrity_hash}>
        {r.integrity_hash.slice(0, 12)}…
      </span>
    ),
  },
  {
    key: "chain",
    header: "Cadena",
    render: (r) =>
      r.prev_hash ? (
        <Badge tone="ok" icon={LinkSimple}>
          Encadenado
        </Badge>
      ) : (
        <Badge tone="neutral" icon={LinkBreak}>
          Raíz
        </Badge>
      ),
  },
];

export default function AdminCompliancePage() {
  const { session } = usePlatformAuth();
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Report | null>(null);

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [f, r] = await Promise.all([
        platformApi<{ frameworks: Framework[] }>(`/api/v1/platform/compliance/dashboard${q}`, { token: session.token }),
        platformApi<{ reports: Report[] }>(`/api/v1/platform/audit/reports${q}`, { token: session.token }),
      ]);
      setFrameworks(f.frameworks || []);
      setReports(r.reports || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Compliance"
        subtitle="Estado por control (SOC2 / GDPR / ISO27001) y reportes de auditoría con integridad verificable."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <Toolbar>
            <Select
              className="w-full sm:w-56"
              aria-label="Organización"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
            >
              <option value="">todas (plantilla)</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id.slice(0, 8)}
                </option>
              ))}
            </Select>
            <span className="text-xs text-muted">
              {orgId ? "Snapshots de la organización seleccionada." : "Vista plantilla: sin organización."}
            </span>
          </Toolbar>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            {frameworks.map((f) => (
              <Panel key={f.framework}>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldCheck size={15} className="text-faint" aria-hidden />
                      {f.framework.toUpperCase()}
                    </span>
                  }
                  actions={<span className="text-h2 tabular-nums">{f.score}%</span>}
                  description={`${f.controls} controles evaluados`}
                />
                <div className="panel-body flex flex-col gap-3">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="ok" icon={CheckCircle}>
                      {f.pass} pass
                    </Badge>
                    <Badge tone="danger" icon={XCircle}>
                      {f.fail} fail
                    </Badge>
                    <Badge tone="warn" icon={Clock}>
                      {f.review} review
                    </Badge>
                    <Badge tone="neutral" icon={Minus}>
                      {f.na} n/a
                    </Badge>
                  </div>
                  <Progress value={f.score} label={`Score ${f.framework.toUpperCase()}`} />
                </div>
              </Panel>
            ))}
            {frameworks.length === 0 && (
              <Panel className="lg:col-span-3">
                <p className="px-4 py-3 text-[13px] text-muted">
                  Sin snapshots de compliance para este alcance.
                </p>
              </Panel>
            )}
          </div>

          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-h2">Reportes de auditoría</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  Cada reporte está encadenado por hash con el anterior. Seleccioná una fila para inspeccionar la integridad.
                </p>
              </div>
            </div>
            <DataTable
              columns={REPORT_COLUMNS}
              rows={reports}
              rowKey={(r) => r.id}
              caption="Reportes de auditoría"
              stickyHeader
              onRowClick={(r) => setSelected(r)}
              empty={
                <p className="px-4 py-6 text-center text-[13px] text-muted">
                  Sin reportes para este alcance.
                </p>
              }
              footer={reports.length > 0 ? <ResultCount shown={reports.length} total={reports.length} noun="reportes" /> : undefined}
            />
          </section>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Integridad del reporte"
        description={selected ? `${selected.report_type} · ${selected.format.toUpperCase()}` : undefined}
        width={480}
      >
        {selected && (
          <div className="space-y-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Organización", value: selected.organization_id, mono: true },
                { key: "Creado", value: fmtDateTime(selected.created_at) },
                { key: "Encadenado", value: selected.prev_hash ? "Sí, con el reporte anterior" : "No, es el primer reporte (raíz)" },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Hash de integridad</p>
              <p className="mono break-all rounded-sm border border-border bg-control px-3 py-2 text-xs text-text">
                {selected.integrity_hash}
              </p>
            </div>
            <div>
              <p className="eyebrow mb-2">Hash previo</p>
              <p className="mono break-all rounded-sm border border-border bg-control px-3 py-2 text-xs text-muted">
                {selected.prev_hash ?? "—"}
              </p>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
