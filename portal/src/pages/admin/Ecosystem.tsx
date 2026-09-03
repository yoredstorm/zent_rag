import { Storefront, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
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

  return (
    <div className="space-y-6">
      <PageHeader title="Agent Ecosystem" subtitle="Marketplace público: adopción por categoría, ingresos con revenue sharing y top publicadores." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.listings_total ?? 0}</p><p className="text-xs text-faint">Listings</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.listings_published ?? 0}</p><p className="text-xs text-faint">Publicados</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.total_installs ?? 0}</p><p className="text-xs text-faint">Instalaciones</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">${((dash?.gmv_cents ?? 0) / 100).toFixed(0)}</p><p className="text-xs text-faint">GMV · fees ${((dash?.platform_fees_cents ?? 0) / 100).toFixed(0)}</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">★ {dash?.avg_rating ?? 0}</p><p className="text-xs text-faint">Rating medio</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={15} /> Adopción por categoría</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.by_category ?? []).map((c) => (
                  <div key={c.category} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{c.category}</span>
                    <span className="text-faint">{c.count} listings · {c.installs} installs</span>
                  </div>
                ))}
                {(dash?.by_category ?? []).length === 0 && <p className="text-xs text-faint">Sin listings.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Storefront size={15} /> Top publicadores</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_publishers ?? []).map((p) => (
                  <div key={p.publisher} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 truncate text-text">{p.publisher}</span>
                    {p.badge !== "sin badge" && <span className="badge badge-warning">{p.badge}</span>}
                    <span className="text-faint">{p.listings} listings · ${(p.earned_cents / 100).toFixed(0)}</span>
                  </div>
                ))}
                {(dash?.top_publishers ?? []).length === 0 && <p className="text-xs text-faint">Sin publicadores.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}