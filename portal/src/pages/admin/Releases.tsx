import { GitCommit } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Drawer,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  SectionHeader,
  SkeletonTable,
  StatusBadge,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Release = {
  id: string;
  agent_id: string;
  agent_name: string;
  version_id: string;
  version_number: number;
  channel: string;
  traffic_pct: number;
  status: string;
  health_score: number | null;
  created_at: string;
  promoted_at: string | null;
  rolled_back_at: string | null;
};
type Dash = {
  agents: {
    agent_id: string;
    agent_name: string;
    releases: number;
    canary: { version: number; status: string; health: number | null } | null;
    stable: { version: number; status: string; health: number | null } | null;
    last_status: string;
  }[];
  total_releases: number;
};

/** "promoted" no está en el vocabulario compartido: se muestra como producción. */
function normalizeReleaseStatus(status: string): string {
  if (status === "promoted") return "production";
  return status;
}

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("es-PE") : "—";
}

export default function AdminReleasesPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [releases, setReleases] = useState<Release[]>([]);
  const [detail, setDetail] = useState<Release | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [d, r] = await Promise.all([
        platformApi<Dash>("/api/v1/platform/releases/dashboard", { token: session.token }),
        platformApi<{ releases: Release[] }>("/api/v1/platform/releases", { token: session.token }),
      ]);
      setDash(d);
      setReleases(r.releases || []);
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

  const canaryActive = releases.filter((r) => r.channel === "canary" && r.status === "running");
  const paused = releases.filter((r) => r.status === "paused");
  const rolledBack = releases.filter((r) => r.status === "rolled_back");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Releases"
        subtitle="Canales canary/stable, health-gate y promoción gradual con rollbacks."
      />
      <ErrorInline message={error} />
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={6} />
        </Panel>
      ) : (
        <>
          <Panel className={`p-4 ${paused.length > 0 ? "border-warn/40" : ""}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Canary en curso</p>
                <p
                  className={`mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums ${
                    canaryActive.length > 0 ? "text-text" : "text-muted"
                  }`}
                >
                  {canaryActive.length}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {paused.length > 0
                    ? `${paused.length} release(s) pausadas: el health-gate frenó la promoción. Revisá el health antes de retomar.`
                    : canaryActive.length > 0
                      ? `${canaryActive.length} release(s) en canary con tráfico parcial. El health-gate decide la promoción a stable.`
                      : "Sin releases en canary: todos los agentes están sobre su versión stable."}
                </p>
              </div>
              <p className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-faint">
                <span className="flex items-center gap-1.5">
                  <Badge tone="warn" dot>
                    Canary
                  </Badge>
                  <span className="tabular-nums">{releases.filter((r) => r.channel === "canary").length}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <Badge tone="ok" dot>
                    Stable
                  </Badge>
                  <span className="tabular-nums">{releases.filter((r) => r.channel === "stable").length}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <StatusBadge status="rolled_back" />
                  <span className="tabular-nums">{rolledBack.length}</span>
                </span>
              </p>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric size="md" label="Agentes con releases" value={(dash?.agents.length ?? 0).toLocaleString()} />
            <Metric size="md" label="Releases totales" value={(dash?.total_releases ?? 0).toLocaleString()} />
            <Metric
              size="md"
              label="Canary activos"
              value={canaryActive.length.toLocaleString()}
              tone={canaryActive.length > 0 ? "warn" : "default"}
            />
            <Metric
              size="md"
              label="Revertidas"
              value={rolledBack.length.toLocaleString()}
              tone={rolledBack.length > 0 ? "danger" : "default"}
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Agentes"
              description="Versión canary y stable vigente por agente, con el último estado registrado."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              {(dash?.agents ?? []).length === 0 ? (
                <EmptyState
                  icon={GitCommit}
                  compact
                  title="Sin releases"
                  body="Ningún agente registró releases todavía."
                  hint="Los releases se crean al publicar una versión de agente."
                />
              ) : (
                <table className="table min-w-[880px]">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th>Canary</th>
                      <th>Stable</th>
                      <th className="text-right">Releases</th>
                      <th>Último estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(dash?.agents ?? []).map((a) => (
                      <tr key={a.agent_id}>
                        <td className="font-medium">{a.agent_name}</td>
                        <td>
                          {a.canary ? (
                            <span className="flex flex-wrap items-center gap-2">
                              <Badge tone="warn" dot>
                                Canary
                              </Badge>
                              <span className="tabular-nums">
                                v{a.canary.version} · {a.canary.health != null ? `${a.canary.health}%` : "—"}
                              </span>
                            </span>
                          ) : (
                            <span className="text-faint">—</span>
                          )}
                        </td>
                        <td>
                          {a.stable ? (
                            <span className="flex flex-wrap items-center gap-2">
                              <Badge tone="ok" dot>
                                Stable
                              </Badge>
                              <span className="tabular-nums">
                                v{a.stable.version} · {a.stable.health != null ? `${a.stable.health}%` : "—"}
                              </span>
                            </span>
                          ) : (
                            <span className="text-faint">—</span>
                          )}
                        </td>
                        <td className="text-right tabular-nums">{a.releases.toLocaleString()}</td>
                        <td>
                          <StatusBadge status={normalizeReleaseStatus(a.last_status)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="Historial de releases"
              description="Cada fila abre el detalle con fechas de promoción y rollback."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              {releases.length === 0 ? (
                <EmptyState
                  icon={GitCommit}
                  compact
                  title="Sin releases"
                  body="Todavía no se publicó ninguna versión de agente."
                />
              ) : (
                <table className="table min-w-[960px]">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th>Versión</th>
                      <th>Canal</th>
                      <th className="text-right">Tráfico</th>
                      <th className="text-right">Health</th>
                      <th>Estado</th>
                      <th>Promovido</th>
                      <th>Rollback</th>
                    </tr>
                  </thead>
                  <tbody>
                    {releases.map((r) => (
                      <tr key={r.id} className="cursor-pointer" onClick={() => setDetail(r)}>
                        <td className="font-medium">{r.agent_name}</td>
                        <td className="tabular-nums">v{r.version_number}</td>
                        <td>
                          <Badge tone={r.channel === "canary" ? "warn" : r.channel === "stable" ? "ok" : "neutral"} dot>
                            {r.channel}
                          </Badge>
                        </td>
                        <td className="text-right tabular-nums">{r.traffic_pct}%</td>
                        <td className="text-right tabular-nums">
                          {r.health_score != null ? `${r.health_score}%` : "—"}
                        </td>
                        <td>
                          <StatusBadge status={normalizeReleaseStatus(r.status)} />
                        </td>
                        <td className="text-xs text-muted tabular-nums">{formatDateTime(r.promoted_at)}</td>
                        <td className="text-xs text-muted tabular-nums">{formatDateTime(r.rolled_back_at)}</td>
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
        title={detail ? `${detail.agent_name} · v${detail.version_number}` : "Release"}
        description={detail ? `ID ${detail.id}` : undefined}
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={normalizeReleaseStatus(detail.status)} />
              <Badge tone={detail.channel === "canary" ? "warn" : detail.channel === "stable" ? "ok" : "neutral"} dot>
                {detail.channel}
              </Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Agente", value: detail.agent_name },
                { key: "Agent ID", value: detail.agent_id, mono: true },
                { key: "Versión", value: `v${detail.version_number}` },
                { key: "Version ID", value: detail.version_id, mono: true },
                { key: "Tráfico", value: `${detail.traffic_pct}%` },
                { key: "Health", value: detail.health_score != null ? `${detail.health_score}%` : "—" },
                { key: "Creado", value: formatDateTime(detail.created_at), mono: true },
                { key: "Promovido", value: formatDateTime(detail.promoted_at), mono: true },
                { key: "Rollback", value: formatDateTime(detail.rolled_back_at), mono: true },
              ]}
            />
          </div>
        )}
      </Drawer>
    </div>
  );
}
