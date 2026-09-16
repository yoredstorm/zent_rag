import { Storefront, TrendUp } from "@phosphor-icons/react";
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
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { listings_total: number; listings_published: number; total_installs: number; gmv_cents: number; platform_fees_cents: number; publisher_payouts_cents: number; orders_count: number; avg_rating: number; by_category: { category: string; count: number; installs: number }[]; top_publishers: { publisher: string; listings: number; earned_cents: number; badge: string }[] };

export default function AdminEcosystemPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/ecosystem/dashboard", { token: session.token });
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

  const published = dash?.listings_published ?? 0;
  const total = dash?.listings_total ?? 0;
  const drafts = Math.max(0, total - published);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Agent Ecosystem"
        subtitle="Marketplace público: adopción por categoría, ingresos con revenue sharing y top publicadores."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid className="xl:grid-cols-5">
            <Metric
              label="Listings"
              value={total}
              hint={drafts > 0 ? `${drafts} fuera de publicación` : "Todos publicados"}
            />
            <Metric label="Publicados" value={published} size="md" tone={published > 0 ? "ok" : "default"} icon={Storefront} />
            <Metric label="Instalaciones" value={dash?.total_installs ?? 0} size="md" hint={`${dash?.orders_count ?? 0} órdenes`} />
            <Metric
              label="GMV"
              value={`$${((dash?.gmv_cents ?? 0) / 100).toFixed(0)}`}
              size="md"
              hint={`Fees $${((dash?.platform_fees_cents ?? 0) / 100).toFixed(0)} · payouts $${((dash?.publisher_payouts_cents ?? 0) / 100).toFixed(0)}`}
            />
            <Metric label="Rating medio" value={dash?.avg_rating ?? 0} size="md" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <TrendUp size={15} className="text-faint" aria-hidden />
                    Adopción por categoría
                  </span>
                }
                description="Listings publicados e instalaciones acumuladas."
              />
              <ul className="divide-y divide-border-soft">
                {(dash?.by_category ?? []).map((c) => (
                  <li key={c.category} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0 truncate text-xs text-text" title={c.category}>
                      {c.category}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {c.count} listings · {c.installs} installs
                    </span>
                  </li>
                ))}
                {(dash?.by_category ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin listings.</li>
                )}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <Storefront size={15} className="text-faint" aria-hidden />
                    Top publicadores
                  </span>
                }
                description="Ingresos acumulados y catálogo publicado."
              />
              <ul className="divide-y divide-border-soft">
                {(dash?.top_publishers ?? []).map((p) => (
                  <li key={p.publisher} className="flex items-center gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1 truncate text-xs text-text" title={p.publisher}>
                      {p.publisher}
                    </span>
                    {p.badge !== "sin badge" && (
                      <Badge tone="warn" icon={Storefront}>
                        {p.badge}
                      </Badge>
                    )}
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {p.listings} listings · ${(p.earned_cents / 100).toFixed(0)}
                    </span>
                  </li>
                ))}
                {(dash?.top_publishers ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin publicadores.</li>
                )}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
