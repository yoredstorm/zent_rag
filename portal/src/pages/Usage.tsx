import {
  ArrowClockwise,
  ChartLineUp,
  Coins,
  Lightning,
  ListBullets,
  Timer,
  Warning,
  WarningCircle,
} from "@phosphor-icons/react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "../components/ui";
import { fmtCurrency, fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

const UsageChart = lazy(() => import("../components/UsageChart"));

type Usage = {
  totals: {
    requests: number;
    tokens: number;
    avg_latency_ms: number;
    errors?: number;
    estimated_cost?: number;
  };
  daily: { day: string; requests: number; tokens: number; avg_latency_ms: number }[];
  recent: {
    id: number;
    total_tokens: number;
    latency_ms: number;
    model: string | null;
    created_at: string;
  }[];
  top_users?: { user_id: string; requests: number }[];
};

/** Skeleton con la forma final: foco + métricas + tabla. */
function UsageSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <div className="flex flex-col gap-3 p-4 sm:p-5">
            <Skeleton className="h-3 w-36" />
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-4 w-56" />
            <Skeleton className="mt-2 h-[240px] rounded-md" />
          </div>
        </Panel>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[104px] rounded-lg" />
          ))}
        </div>
      </div>
      <Skeleton className="h-[220px] rounded-lg" />
    </div>
  );
}

export default function UsagePage() {
  const { session } = useAuth();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await api<Usage>("/api/v1/billing/usage?days=30", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setUsage(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const daily = usage?.daily ?? [];

  return (
    <div>
      <PageHeader
        title="Analítica"
        subtitle="Entiende cómo tu workspace usa la IA: consultas, tokens y latencia de los últimos 30 días."
      />

      {loading ? (
        <UsageSkeleton />
      ) : !usage ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos cargar la analítica"
            body={error || "La API no devolvió datos de uso."}
            action={
              <Button variant="secondary" leadingIcon={ArrowClockwise} onClick={() => void load()}>
                Reintentar
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          {error && <ErrorInline message={error} />}

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Foco: el volumen real de los últimos 30 días manda sobre el resto */}
            <Panel className="lg:col-span-2">
              <div className="p-4 sm:p-5">
                <p className="eyebrow">Consultas · últimos 30 días</p>
                <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <p className="text-display tabular-nums">{fmtNum(usage.totals.requests)}</p>
                  <p className="text-[13px] text-muted">consultas registradas en tu workspace</p>
                </div>
              </div>
              <div className="border-t border-border-soft p-4">
                {daily.length === 0 ? (
                  <EmptyState
                    icon={ChartLineUp}
                    title="Sin actividad aún"
                    body="Todavía no hay consultas registradas en los últimos 30 días."
                    hint="Cuando uses un agente o el Playground, la serie diaria aparece acá."
                  />
                ) : (
                  <Suspense
                    fallback={
                      <div role="status" aria-label="Cargando gráfico">
                        <Skeleton className="h-[240px] rounded-md" />
                      </div>
                    }
                  >
                    <UsageChart daily={daily} />
                  </Suspense>
                )}
              </div>
            </Panel>

            {/* Demotadas: contexto que acompaña al foco */}
            <MetricGrid cols={2}>
              <Metric
                size="md"
                label="Tokens"
                value={fmtNum(usage.totals.tokens)}
                hint="procesados en 30 días"
                icon={Lightning}
              />
              <Metric
                size="md"
                label="Latencia media"
                value={fmtLatency(usage.totals.avg_latency_ms)}
                hint="por consulta"
                icon={Timer}
              />
              <Metric
                size="md"
                label="Errores"
                value={fmtNum(usage.totals.errors ?? 0)}
                tone={(usage.totals.errors ?? 0) > 0 ? "danger" : "default"}
                hint={(usage.totals.errors ?? 0) > 0 ? "revisá las consultas recientes" : "sin errores"}
                icon={Warning}
              />
              <Metric
                size="md"
                label="Costo estimado"
                value={
                  usage.totals.estimated_cost != null
                    ? fmtCurrency(usage.totals.estimated_cost)
                    : "—"
                }
                hint={usage.totals.estimated_cost != null ? "30 días" : "sin datos de costo"}
                icon={Coins}
              />
            </MetricGrid>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Panel>
              <PanelHeader
                title="Por día"
                description="Consultas, tokens y latencia de cada día con actividad."
              />
              {daily.length === 0 ? (
                <EmptyState
                  compact
                  icon={ChartLineUp}
                  title="Sin actividad aún"
                  body="Todavía no hay consultas registradas en los últimos 30 días."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table min-w-[520px]">
                    <caption className="sr-only">
                      Consultas, tokens y latencia media por día
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Día</th>
                        <th scope="col" className="text-right">Consultas</th>
                        <th scope="col" className="text-right">Tokens</th>
                        <th scope="col" className="text-right">Latencia media</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.daily.map((d) => (
                        <tr key={d.day}>
                          <td className="mono">{d.day}</td>
                          <td className="mono text-right">{fmtNum(d.requests)}</td>
                          <td className="mono text-right">{fmtNum(d.tokens)}</td>
                          <td className="mono text-right">{fmtLatency(d.avg_latency_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            <div className="flex flex-col gap-4">
              <Panel>
                <PanelHeader
                  title="Recientes"
                  description="Últimas consultas y su rendimiento."
                />
                {usage.recent.length === 0 ? (
                  <EmptyState
                    compact
                    icon={ListBullets}
                    title="Sin consultas recientes"
                    body="Las últimas consultas y su rendimiento aparecerán aquí."
                  />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table min-w-[480px]">
                      <caption className="sr-only">Consultas recientes con tokens, latencia y modelo</caption>
                      <thead>
                        <tr>
                          <th scope="col">Fecha</th>
                          <th scope="col" className="text-right">Tokens</th>
                          <th scope="col" className="text-right">Latencia</th>
                          <th scope="col">Modelo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usage.recent.map((r) => (
                          <tr key={r.id}>
                            <td className="text-muted">{fmtDateTime(r.created_at)}</td>
                            <td className="mono text-right">{fmtNum(r.total_tokens)}</td>
                            <td className="mono text-right">{fmtLatency(r.latency_ms)}</td>
                            <td className="mono text-faint">{r.model || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>

              {(usage.top_users?.length ?? 0) > 0 && (
                <Panel>
                  <PanelHeader
                    title="Usuarios más activos"
                    description="Consultas por usuario en los últimos 30 días."
                  />
                  <ul className="divide-y divide-border-soft px-4 py-1">
                    {(usage.top_users ?? []).slice(0, 8).map((u) => (
                      <li key={u.user_id} className="flex items-center justify-between gap-3 py-2.5">
                        <span className="mono min-w-0 truncate text-xs text-muted" title={u.user_id}>
                          {u.user_id.slice(0, 8)}…
                        </span>
                        <span className="text-[13px] tabular-nums text-text">
                          {fmtNum(u.requests)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
