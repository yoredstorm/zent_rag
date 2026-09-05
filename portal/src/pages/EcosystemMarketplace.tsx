import { CurrencyDollar, Plus, SealCheck, Storefront } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Listing = { id: string; name: string; slug: string; description: string | null; category: string; tags: string[]; pricing_type: string; price_cents: number; currency: string; version: string; status: string; installs: number; rating: number; reviews_count: number; publisher_name: string | null; publisher_badge: string | null };
type Review = { rating: number; comment: string | null; verified: boolean; created_at: string; org_name: string | null };
type Purchase = { id: string; listing: string; category: string; price_cents: number; platform_fee_cents: number; publisher_payout_cents: number; status: string; created_at: string };
type Payout = { id: string; amount_cents: number; period_start: string; period_end: string; status: string; created_at: string };

const CATS = ["general", "support", "sales", "operations", "legal", "hr", "analytics", "engineering"];

export default function EcosystemMarketplacePage() {
  const { session } = useAuth();
  const [catalog, setCatalog] = useState<Listing[]>([]);
  const [mine, setMine] = useState<Listing[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [badge, setBadge] = useState<{ badge: string | null; level?: string; status?: string } | null>(null);
  const [selected, setSelected] = useState<Listing | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState({ name: "", category: "general", pricing_type: "free", price_cents: 0, description: "", config_template: "", prompt_template: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [c, m, p, po, b] = await Promise.all([
        api<{ listings: Listing[] }>(`/api/v1/marketplace?${category ? `category=${category}&` : ""}${search ? `search=${encodeURIComponent(search)}` : ""}`, { token: session.token, organizationId: session.organizationId }),
        api<{ listings: Listing[] }>("/api/v1/marketplace/my/listings", { token: session.token, organizationId: session.organizationId }),
        api<{ purchases: Purchase[] }>("/api/v1/marketplace/my/purchases", { token: session.token, organizationId: session.organizationId }),
        api<{ payouts: Payout[] }>("/api/v1/marketplace/my/payouts", { token: session.token, organizationId: session.organizationId }),
        api<{ badge: string | null }>("/api/v1/marketplace/partner/badges", { token: session.token, organizationId: session.organizationId }),
      ]);
      setCatalog(c.listings || []);
      setMine(m.listings || []);
      setPurchases(p.purchases || []);
      setPayouts(po.payouts || []);
      setBadge(b as { badge: string | null });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, category, search]);

  async function create() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    try {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(draft.config_template || "{}");
      } catch {
        setError("config_template no es JSON válido");
        setBusy("");
        return;
      }
      const out = await api<{ listing_id: string }>("/api/v1/marketplace/listings", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ ...draft, price_cents: Number(draft.price_cents), config_template: config }),
      });
      setError(`Publicación creada: ${out.listing_id.slice(0, 8)}…`);
      setDraft({ name: "", category: "general", pricing_type: "free", price_cents: 0, description: "", config_template: "", prompt_template: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(id: string, action: "publish" | "unpublish" | "purchase") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/marketplace/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setError(`${action}: ${JSON.stringify(out).slice(0, 120)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(l: Listing) {
    setSelected(l);
    if (!session) return;
    const r = await api<{ reviews: Review[] }>(`/api/v1/marketplace/${l.id}/reviews`, { token: session.token, organizationId: session.organizationId });
    setReviews(r.reviews || []);
  }

  async function applyPartner() {
    if (!session) return;
    setBusy("partner");
    await api("/api/v1/marketplace/partner/apply", { method: "POST", token: session.token, organizationId: session.organizationId, body: JSON.stringify({ level: "partner" }) });
    setBusy("");
    await load();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Agent Marketplace" subtitle="Publica y compra agentes con reviews verificadas, revenue sharing y badges de partner." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <input className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" placeholder="buscar…" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">todas las categorías</option>
                {CATS.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
              {badge?.badge && <span className="badge badge-ok"><SealCheck size={11} /> {badge.badge}</span>}
              {!badge?.badge && <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void applyPartner()}>Solicitar badge partner</button>}
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {catalog.map((l) => (
                <div key={l.id} className="panel p-3">
                  <div className="flex items-center gap-2">
                    <Storefront size={13} className="text-accent" />
                    <button type="button" className="text-sm font-semibold text-text" onClick={() => void showDetail(l)}>{l.name}</button>
                    <span className="badge badge-muted">{l.category}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] text-faint">{l.description}</p>
                  <div className="mt-2 flex items-center gap-2 text-[10px]">
                    <span className="text-faint">★ {l.rating} ({l.reviews_count})</span>
                    <span className="text-faint">{l.installs} instalaciones</span>
                    <span className="flex-1" />
                    {l.publisher_badge && <span className="badge badge-warning">{l.publisher_badge}</span>}
                    <span className="text-xs font-bold text-text">{l.pricing_type === "free" ? "Gratis" : `$${(l.price_cents / 100).toFixed(2)}`}</span>
                    {l.pricing_type !== "free" && (
                      <button type="button" className="btn btn-primary min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(l.id, "purchase")}><CurrencyDollar size={10} /> Comprar</button>
                    )}
                  </div>
                </div>
              ))}
              {catalog.length === 0 && <p className="panel p-4 text-xs text-faint">Sin listings publicados. Publica el tuyo.</p>}
            </div>

            {selected && (
              <div className="panel mt-2 p-4">
                <h3 className="text-sm font-semibold text-text">{selected.name} · v{selected.version}</h3>
                <p className="mt-1 text-xs text-faint">{selected.publisher_name} {selected.publisher_badge ? `· ${selected.publisher_badge}` : ""}</p>
                <div className="mt-2 space-y-1">
                  {reviews.map((r, i) => (
                    <div key={i} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <p><span className="text-amber-400">{"★".repeat(r.rating)}</span> {r.verified && <span className="badge badge-ok">verificada</span>} <span className="text-faint">{r.org_name}</span></p>
                      {r.comment && <p className="text-text">{r.comment}</p>}
                    </div>
                  ))}
                  {reviews.length === 0 && <p className="text-xs text-faint">Sin reviews.</p>}
                </div>
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div className="panel p-4">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Plus size={14} /> Publicar agente</h2>
              <div className="grid grid-cols-1 gap-2">
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="nombre…" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
                <div className="flex gap-2">
                  <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}>
                    {CATS.map((c) => (<option key={c} value={c}>{c}</option>))}
                  </select>
                  <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={draft.pricing_type} onChange={(e) => setDraft((d) => ({ ...d, pricing_type: e.target.value }))}>
                    {["free", "one_time", "subscription"].map((p) => (<option key={p} value={p}>{p}</option>))}
                  </select>
                  <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="precio" value={draft.price_cents} onChange={(e) => setDraft((d) => ({ ...d, price_cents: Number(e.target.value) }))} />
                </div>
                <textarea className="h-16 rounded-md border border-border bg-soft px-2 py-2 text-[11px]" placeholder="descripción…" value={draft.description} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
                <textarea className="h-16 rounded-md border border-border bg-soft px-2 py-2 font-mono text-[10px]" placeholder='{"model": "gpt-4o-mini"}' value={draft.config_template} onChange={(e) => setDraft((d) => ({ ...d, config_template: e.target.value }))} />
                <textarea className="h-16 rounded-md border border-border bg-soft px-2 py-2 text-[11px]" placeholder="prompt template…" value={draft.prompt_template} onChange={(e) => setDraft((d) => ({ ...d, prompt_template: e.target.value }))} />
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !draft.name} onClick={() => void create()}>Crear</button>
              </div>
            </div>

            <div className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Mis publicaciones ({mine.length})</h3>
              <div className="space-y-1">
                {mine.map((l) => (
                  <div key={l.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="flex-1 font-medium text-text">{l.name}</span>
                      <span className={`badge ${l.status === "published" ? "badge-ok" : "badge-muted"}`}>{l.status}</span>
                    </div>
                    <p className="mt-0.5 text-[10px] text-faint">v{l.version} · {l.installs} instalaciones · ★ {l.rating}</p>
                    <div className="mt-1 flex gap-1">
                      {l.status !== "published" ? (
                        <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(l.id, "publish")}>Publicar</button>
                      ) : (
                        <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(l.id, "unpublish")}>Despublicar</button>
                      )}
                    </div>
                  </div>
                ))}
                {mine.length === 0 && <p className="text-xs text-faint">Sin publicaciones.</p>}
              </div>
            </div>

            <div className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Compras ({purchases.length}) y payouts ({payouts.length})</h3>
              {(purchases ?? []).slice(0, 4).map((p) => (
                <p key={p.id} className="rounded bg-soft px-2 py-1 text-[10px] text-faint">{p.listing} · ${(p.price_cents / 100).toFixed(2)} · fee {p.platform_fee_cents}c</p>
              ))}
              {(payouts ?? []).slice(0, 3).map((p) => (
                <p key={p.id} className="rounded bg-soft px-2 py-1 text-[10px] text-faint">Payout ${(p.amount_cents / 100).toFixed(2)} · {p.status} · {p.period_end}</p>
              ))}
              {(purchases?.length ?? 0) === 0 && (payouts?.length ?? 0) === 0 && <p className="text-xs text-faint">Sin actividad.</p>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}