import { ArrowsLeftRight } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Progress,
  SectionHeader,
  Select,
  SkeletonTable,
  StatusBadge,
  Toolbar,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Migration = {
  id: string;
  organization_id: string;
  kind: string;
  direction: string;
  status: string;
  rows_total: number;
  rows_valid: number;
  rows_applied: number;
  rows_failed: number;
  created_at: string;
};
type Dash = {
  total: number;
  by_status: Record<string, number>;
  by_kind: Record<string, number>;
  rows_applied_total: number;
  rows_failed_total: number;
};

/** Estados propios de migración que no están en el vocabulario compartido. */
function normalizeMigrationStatus(status: string): string {
  if (status === "applied" || status === "exported") return "completed";
  return status;
}

export default function AdminMigrationsPage() {
  const { session } = usePlatformAuth();
  const [migrations, setMigrations] = useState<Migration[]>([]);
  const [dash, setDash] = useState<Dash | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [detail, setDetail] = useState<Migration | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [m, d] = await Promise.all([
        platformApi<{ migrations: Migration[] }>(`/api/v1/platform/migrations${q}`, {
          token: session.token,
        }),
        platformApi<Dash>("/api/v1/platform/migrations/dashboard", { token: session.token }),
      ]);
      setMigrations(m.migrations || []);
      setDash(d);
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
        const o = await platformApi<{ organizations: { id: string }[] }>(
          "/api/v1/platform/organizations",
          { token: session.token }
        );
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  const applied = dash?.rows_applied_total ?? 0;
  const failedRows = dash?.rows_failed_total ?? 0;
  const totalRows = applied + failedRows;
  const appliedPct = totalRows ? (applied / totalRows) * 100 : 0;
  const byStatus = Object.entries(dash?.by_status ?? {});

  return (
    <div className="space-y-6">
      <PageHeader
        title="Migraciones de datos"
        subtitle="Historial global, estados y re-versión de agentes."
      />
      <ErrorInline message={error} />
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={6} />
        </Panel>
      ) : (
        <>
          <Panel className={`p-4 ${failedRows > 0 ? "border-warn/40" : ""}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Filas procesadas</p>
                <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
                  {totalRows.toLocaleString()}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {failedRows > 0
                    ? `${failedRows.toLocaleString()} fila(s) fallaron. Abrí el detalle de cada migración para ver el impacto antes de reintentar.`
                    : "Ninguna fila falló en las migraciones registradas."}
                </p>
                {byStatus.length > 0 && (
                  <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-faint">
                    {byStatus.map(([status, count]) => (
                      <span key={status} className="flex items-center gap-1.5">
                        <StatusBadge status={normalizeMigrationStatus(status)} />
                        <span className="tabular-nums">{count}</span>
                      </span>
                    ))}
                  </p>
                )}
              </div>
              <div className="min-w-[220px] flex-1 sm:max-w-sm">
                <Progress
                  value={appliedPct}
                  tone={failedRows > 0 ? "warn" : "ok"}
                  label="Filas aplicadas sobre el total procesado"
                  showValue
                />
              </div>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric size="md" label="Migraciones" value={(dash?.total ?? 0).toLocaleString()} />
            <Metric size="md" label="Filas aplicadas" value={applied.toLocaleString()} tone="ok" />
            <Metric
              size="md"
              label="Filas fallidas"
              value={failedRows.toLocaleString()}
              tone={failedRows > 0 ? "danger" : "default"}
            />
            <Metric
              size="md"
              label="Estados distintos"
              value={byStatus.length.toLocaleString()}
              hint="Reportados por el dashboard"
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Historial"
              description="Cada fila abre el detalle de la migración: kind, dirección y conteo de filas."
              className="mb-3"
            />
            <Toolbar className="mb-3">
              <Field label="Organización" className="w-full sm:w-56">
                <Select
                  value={orgId}
                  placeholder="Todas las organizaciones"
                  onChange={(e) => setOrgId(e.target.value)}
                >
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.id.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              </Field>
            </Toolbar>
            <Panel className="overflow-x-auto">
              {migrations.length === 0 ? (
                <EmptyState
                  icon={ArrowsLeftRight}
                  compact
                  title="Sin migraciones"
                  body={
                    orgId
                      ? "La organización elegida no registra migraciones de datos."
                      : "Todavía no se ejecutaron migraciones de datos."
                  }
                  hint="Las migraciones se crean desde el flujo de importación/exportación de cada tenant."
                />
              ) : (
                <table className="table min-w-[960px]">
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Organización</th>
                      <th>Dirección</th>
                      <th>Kind</th>
                      <th>Estado</th>
                      <th className="text-right">Válidas</th>
                      <th className="text-right">Aplicadas</th>
                      <th className="text-right">Fallidas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {migrations.map((m) => (
                      <tr
                        key={m.id}
                        className="cursor-pointer"
                        onClick={() => setDetail(m)}
                      >
                        <td className="text-xs text-muted tabular-nums">
                          {new Date(m.created_at).toLocaleString("es-PE")}
                        </td>
                        <td className="mono text-xs text-faint" title={m.organization_id}>
                          {m.organization_id.slice(0, 8)}
                        </td>
                        <td className="text-xs text-muted">{m.direction}</td>
                        <td className="text-xs text-muted">{m.kind}</td>
                        <td>
                          <StatusBadge status={normalizeMigrationStatus(m.status)} />
                        </td>
                        <td className="text-right tabular-nums">{m.rows_valid.toLocaleString()}</td>
                        <td className="text-right tabular-nums text-ok">{m.rows_applied.toLocaleString()}</td>
                        <td
                          className={`text-right tabular-nums ${m.rows_failed > 0 ? "text-danger" : "text-muted"}`}
                        >
                          {m.rows_failed.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </section>
        </>
      )}

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => !open && setDetail(null)}
        title={detail ? `Migración ${detail.kind}` : "Migración"}
        description={detail ? `ID ${detail.id}` : undefined}
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={normalizeMigrationStatus(detail.status)} />
              <span className="mono text-xs text-faint">{detail.direction}</span>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Organización", value: detail.organization_id, mono: true },
                { key: "Kind", value: detail.kind, mono: true },
                { key: "Dirección", value: detail.direction, mono: true },
                { key: "Creada", value: new Date(detail.created_at).toLocaleString("es-PE"), mono: true },
                { key: "Filas válidas", value: detail.rows_valid.toLocaleString() },
                { key: "Filas totales", value: detail.rows_total.toLocaleString() },
                { key: "Filas aplicadas", value: detail.rows_applied.toLocaleString() },
                { key: "Filas fallidas", value: detail.rows_failed.toLocaleString() },
              ]}
            />
            <Progress
              value={detail.rows_total ? (detail.rows_applied / detail.rows_total) * 100 : 0}
              tone={detail.rows_failed > 0 ? "warn" : "ok"}
              label="Progreso de aplicación"
              showValue
            />
          </div>
        )}
      </Drawer>
    </div>
  );
}
