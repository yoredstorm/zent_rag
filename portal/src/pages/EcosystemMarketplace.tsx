import {
  ArrowClockwise,
  CurrencyDollar,
  MagnifyingGlass,
  Plus,
  SealCheck,
  Star,
  Storefront,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  StatusBadge,
  SuccessInline,
  Textarea,
  Toolbar,
} from "../components/ui";
import { fmtCurrencyCents, fmtDateTime, fmtNum } from "../lib/format";

type Listing = { id: string; name: string; slug: string; description: string | null; category: string; tags: string[]; pricing_type: string; price_cents: number; currency: string; version: string; status: string; installs: number; rating: number; reviews_count: number; publisher_name: string | null; publisher_badge: string | null };
type Review = { rating: number; comment: string | null; verified: boolean; created_at: string; org_name: string | null };
type Purchase = { id: string; listing: string; category: string; price_cents: number; platform_fee_cents: number; publisher_payout_cents: number; status: string; created_at: string };
type Payout = { id: string; amount_cents: number; period_start: string; period_end: string; status: string; created_at: string };

const CATS = ["general", "support", "sales", "operations", "legal", "hr", "analytics", "engineering"];
const PRICING = ["free", "one_time", "subscription"];

const EMPTY_DRAFT = { name: "", category: "general", pricing_type: "free", price_cents: 0, description: "", config_template: "", prompt_template: "" };

function isFree(listing: Listing): boolean {
  return listing.pricing_type === "free" || listing.price_cents === 0;
}

function Rating({ rating, count }: { rating: number; count?: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-faint tabular-nums">
      <Star size={12} weight="fill" className="text-warn" aria-hidden />
      {rating}
      {count !== undefined ? ` (${fmtNum(count)})` : ""}
    </span>
  );
}

export default function EcosystemMarketplacePage() {
  const { session } = useAuth();
  const [catalog, setCatalog] = useState<Listing[]>([]);
  const [mine, setMine] = useState<Listing[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [badge, setBadge] = useState<{ badge: string | null; level?: string; status?: string } | null>(null);
  const [selected, setSelected] = useState<Listing | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [showPublish, setShowPublish] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    if (!session) return;
    setLoadError("");
    try {
      const [c, m, p, po, b] = await Promise.all([
        api<{ listings: Listing[] }>(`/api/v1/marketplace?${category ? `category=${category}&` : ""}${appliedSearch ? `search=${encodeURIComponent(appliedSearch)}` : ""}`, { token: session.token, organizationId: session.organizationId }),
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
      setLoadError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, category, appliedSearch]);

  /** La búsqueda pega contra la API: se aplica 300ms después de la última tecla. */
  useEffect(() => {
    const id = setTimeout(() => setAppliedSearch(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  async function create() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    setMsg("");
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
      setMsg(`Publicación creada: ${out.listing_id.slice(0, 8)}…`);
      setDraft(EMPTY_DRAFT);
      setShowPublish(false);
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
    setMsg("");
    try {
      await api(`/api/v1/marketplace/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(
        action === "purchase"
          ? "Compra confirmada."
          : action === "publish"
            ? "Publicación activa."
            : "Publicación despublicada.",
      );
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
    setReviews([]);
    setReviewsLoading(true);
    try {
      const r = await api<{ reviews: Review[] }>(`/api/v1/marketplace/${l.id}/reviews`, { token: session.token, organizationId: session.organizationId });
      setReviews(r.reviews || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude cargar las reviews");
    } finally {
      setReviewsLoading(false);
    }
  }

  async function applyPartner() {
    if (!session) return;
    setBusy("partner");
    setError("");
    setMsg("");
    try {
      await api("/api/v1/marketplace/partner/apply", { method: "POST", token: session.token, organizationId: session.organizationId, body: JSON.stringify({ level: "partner" }) });
      setMsg("Solicitud de partner enviada.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const partnerBadge = badge?.badge;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Marketplace"
        subtitle="Publica y compra agentes con reviews verificadas, revenue sharing y badges de partner."
        meta={partnerBadge ? <Badge tone="ok" icon={SealCheck}>{partnerBadge}</Badge> : undefined}
        actions={
          partnerBadge ? (
            <Button variant="primary" leadingIcon={Plus} onClick={() => setShowPublish(true)}>
              Publicar agente
            </Button>
          ) : (
            <Button
              variant="secondary"
              leadingIcon={SealCheck}
              loading={busy === "partner"}
              onClick={() => void applyPartner()}
            >
              Solicitar badge partner
            </Button>
          )
        }
      />
      <ErrorInline message={error} />
      <ErrorInline
        message={loadError && (catalog.length > 0 || mine.length > 0) ? loadError : ""}
      />
      <SuccessInline message={msg} />

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-3" aria-hidden>
          <Skeleton className="h-[420px] rounded-lg lg:col-span-2" />
          <div className="flex flex-col gap-4">
            <Skeleton className="h-36 rounded-lg" />
            <Skeleton className="h-56 rounded-lg" />
          </div>
        </div>
      ) : loadError && catalog.length === 0 && mine.length === 0 ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos cargar el marketplace"
            body={loadError}
            hint="Revisá la conexión y volvé a intentar."
            action={
              <Button variant="secondary" leadingIcon={ArrowClockwise} onClick={() => void load()}>
                Reintentar
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Foco: catálogo explorable */}
          <section className="flex flex-col gap-3 lg:col-span-2">
            <Toolbar className="justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  icon={MagnifyingGlass}
                  aria-label="Buscar agentes"
                  placeholder="Buscar agentes…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-64"
                />
                <Select
                  aria-label="Categoría"
                  className="w-48"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="">Todas las categorías</option>
                  {CATS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </div>
              <p className="text-xs text-muted tabular-nums">
                {catalog.length === 1 ? "1 listing" : `${fmtNum(catalog.length)} listings`}
              </p>
            </Toolbar>

            <Panel className="overflow-hidden">
              {catalog.length === 0 ? (
                search || category ? (
                  <EmptyState
                    icon={MagnifyingGlass}
                    title="Sin resultados"
                    body="Ningún agente publicado coincide con la búsqueda y la categoría elegidas."
                    action={
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setSearch("");
                          setCategory("");
                        }}
                      >
                        Limpiar búsqueda y filtros
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    icon={Storefront}
                    title="Sin listings publicados"
                    body="Todavía no hay agentes publicados en el marketplace."
                    hint="Si publicás un agente, aparece acá en cuanto esté publicado."
                    action={
                      <Button variant="primary" leadingIcon={Plus} onClick={() => setShowPublish(true)}>
                        Publicar agente
                      </Button>
                    }
                  />
                )
              ) : (
                <ul className="divide-y divide-border-soft">
                  {catalog.map((l) => (
                    <li key={l.id} className="px-4 py-3.5">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="flex min-w-0 gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-soft bg-raised text-accent">
                            <Storefront size={17} aria-hidden />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <button
                                type="button"
                                className="text-left text-sm font-semibold text-text transition-colors duration-150 hover:text-accent"
                                onClick={() => void showDetail(l)}
                              >
                                {l.name}
                              </button>
                              <Badge>{l.category}</Badge>
                              {l.publisher_badge && (
                                <Badge tone="info" icon={SealCheck}>
                                  {l.publisher_badge}
                                </Badge>
                              )}
                            </div>
                            <p className="mt-1 line-clamp-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                              {l.description || "Sin descripción todavía."}
                            </p>
                            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
                              <Rating rating={l.rating} count={l.reviews_count} />
                              <span className="tabular-nums">{fmtNum(l.installs)} instalaciones</span>
                              {l.publisher_name && <span>{l.publisher_name}</span>}
                            </div>
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center gap-2 sm:pl-4">
                          <span className="text-[13px] font-medium text-text">
                            {isFree(l) ? "Gratis" : fmtCurrencyCents(l.price_cents)}
                          </span>
                          <Button size="sm" variant="secondary" onClick={() => void showDetail(l)}>
                            Ver detalle
                          </Button>
                          {!isFree(l) && (
                            <Button
                              size="sm"
                              variant="primary"
                              leadingIcon={CurrencyDollar}
                              loading={busy === `purchase-${l.id.slice(0, 6)}`}
                              onClick={() => void act(l.id, "purchase")}
                            >
                              Comprar
                            </Button>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>

          {/* Aside: vender, publicaciones y actividad */}
          <section className="flex flex-col gap-4">
            <Panel>
              <PanelHeader
                title="Vender en el marketplace"
                description="Publicá agentes propios, recibí reviews verificadas y cobrá payouts."
                actions={
                  <Button size="sm" variant="primary" leadingIcon={Plus} onClick={() => setShowPublish(true)}>
                    Publicar
                  </Button>
                }
              />
              <div className="flex items-center gap-2 px-4 py-3">
                {partnerBadge ? (
                  <>
                    <Badge tone="ok" icon={SealCheck}>
                      {partnerBadge}
                    </Badge>
                    <span className="text-xs text-muted">Badge de partner activo</span>
                  </>
                ) : (
                  <>
                    <span className="text-xs text-muted">
                      Todavía no tenés badge de partner.
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={busy === "partner"}
                      onClick={() => void applyPartner()}
                    >
                      Solicitar
                    </Button>
                  </>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title={`Mis publicaciones (${mine.length})`} />
              {mine.length === 0 ? (
                <EmptyState
                  compact
                  icon={Storefront}
                  title="Sin publicaciones"
                  body="Cuando publiques un agente vas a poder seguir su estado acá."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {mine.map((l) => (
                    <li key={l.id} className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">
                          {l.name}
                        </span>
                        <StatusBadge status={l.status.toLowerCase()} />
                      </div>
                      <p className="mt-1 text-xs text-faint">
                        v{l.version} · {fmtNum(l.installs)} instalaciones · ★ {l.rating}
                      </p>
                      <div className="mt-2">
                        {l.status !== "published" ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            loading={busy === `publish-${l.id.slice(0, 6)}`}
                            onClick={() => void act(l.id, "publish")}
                          >
                            Publicar
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={busy === `unpublish-${l.id.slice(0, 6)}`}
                            onClick={() => void act(l.id, "unpublish")}
                          >
                            Despublicar
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader
                title={`Compras (${purchases.length}) y payouts (${payouts.length})`}
                description="Actividad económica de tu organización."
              />
              {purchases.length === 0 && payouts.length === 0 ? (
                <EmptyState
                  compact
                  icon={CurrencyDollar}
                  title="Sin actividad"
                  body="Compras y payouts van a aparecer acá cuando operes en el marketplace."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {purchases.slice(0, 4).map((p) => (
                    <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-[13px] text-text">{p.listing}</p>
                        <p className="text-xs text-faint">fee {fmtCurrencyCents(p.platform_fee_cents)}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[13px] tabular-nums text-text">
                          {fmtCurrencyCents(p.price_cents)}
                        </p>
                        <StatusBadge status={p.status.toLowerCase()} />
                      </div>
                    </li>
                  ))}
                  {payouts.slice(0, 3).map((p) => (
                    <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="text-[13px] text-text">Payout</p>
                        <p className="text-xs text-faint">
                          hasta {fmtDateTime(p.period_end)}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[13px] tabular-nums text-text">
                          {fmtCurrencyCents(p.amount_cents)}
                        </p>
                        <StatusBadge status={p.status.toLowerCase()} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>
        </div>
      )}

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.name ?? "Agente"}
        description={selected ? `v${selected.version}${selected.publisher_name ? ` · ${selected.publisher_name}` : ""}` : undefined}
        width={480}
        footer={
          selected && !isFree(selected) ? (
            <Button
              variant="primary"
              leadingIcon={CurrencyDollar}
              loading={busy === `purchase-${selected.id.slice(0, 6)}`}
              onClick={() => void act(selected.id, "purchase")}
            >
              Comprar · {fmtCurrencyCents(selected.price_cents)}
            </Button>
          ) : undefined
        }
      >
        {selected && (
          <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{selected.category}</Badge>
              {selected.publisher_badge && (
                <Badge tone="info" icon={SealCheck}>
                  {selected.publisher_badge}
                </Badge>
              )}
              <span className="badge badge-muted">
                {isFree(selected) ? "Gratis" : fmtCurrencyCents(selected.price_cents)}
              </span>
            </div>
            <p className="text-[13px] leading-relaxed text-muted">
              {selected.description || "Sin descripción todavía."}
            </p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
              <Rating rating={selected.rating} count={selected.reviews_count} />
              <span className="tabular-nums">{fmtNum(selected.installs)} instalaciones</span>
            </div>

            <div>
              <p className="eyebrow mb-2">Reviews ({reviews.length})</p>
              {reviewsLoading ? (
                <Skeleton className="h-20 rounded-md" />
              ) : reviews.length === 0 ? (
                <p className="text-[13px] text-muted">Sin reviews todavía.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {reviews.map((r, i) => (
                    <li key={i} className="rounded-md bg-raised px-3 py-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Rating rating={r.rating} />
                        {r.verified && <Badge tone="ok">verificada</Badge>}
                        {r.org_name && <span className="text-xs text-faint">{r.org_name}</span>}
                      </div>
                      {r.comment && (
                        <p className="mt-1 text-[13px] leading-relaxed text-text">{r.comment}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={showPublish}
        onOpenChange={setShowPublish}
        title="Publicar agente"
        description="El agente queda como borrador hasta que lo publiques desde Mis publicaciones."
        width={520}
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowPublish(false)}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={busy === "create"}
              disabled={!draft.name.trim()}
              onClick={() => void create()}
            >
              Publicar
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Field label="Nombre" required>
            <Input
              placeholder="Mi agente de ventas"
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Categoría">
              <Select
                value={draft.category}
                onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
              >
                {CATS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Modelo de precio">
              <Select
                value={draft.pricing_type}
                onChange={(e) => setDraft((d) => ({ ...d, pricing_type: e.target.value }))}
              >
                {PRICING.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Precio (centavos)" hint="Solo aplica a modelos de pago; 0 equivale a gratis.">
            <Input
              type="number"
              min={0}
              value={draft.price_cents}
              onChange={(e) => setDraft((d) => ({ ...d, price_cents: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Descripción">
            <Textarea
              placeholder="Qué hace y para quién es…"
              value={draft.description}
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            />
          </Field>
          <Field label="Config template" hint="JSON válido; se valida antes de publicar.">
            <Textarea
              className="font-mono text-xs"
              placeholder='{"model": "gpt-4o-mini"}'
              value={draft.config_template}
              onChange={(e) => setDraft((d) => ({ ...d, config_template: e.target.value }))}
            />
          </Field>
          <Field label="Prompt template">
            <Textarea
              placeholder="Instrucciones del agente…"
              value={draft.prompt_template}
              onChange={(e) => setDraft((d) => ({ ...d, prompt_template: e.target.value }))}
            />
          </Field>
        </div>
      </Drawer>
    </div>
  );
}
