import {
  ArrowClockwise,
  CaretDown,
  CaretUp,
  CheckCircle,
  Factory,
  Flask,
  Package,
  Plus,
  RocketLaunch,
  Storefront,
  TestTube,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";

type Overview = {
  products_total: number;
  products_published: number;
  products_drafts: number;
  tenant_installations: number;
  library: { integrations: number; workflow_templates: number; agents: number };
  palette: {
    integrations: { slug: string; name: string; category: string; status: string }[];
    actions: { action_id: string; display_name: string; integration_slug: string }[];
    workflow_templates: { slug: string; name: string; trigger_type: string }[];
    agents: { id: string; name: string }[];
  };
};

type Product = {
  id: string;
  slug: string;
  name: string;
  short_description: string | null;
  product_type: string;
  version: number;
  status: string;
  category: string;
  pricing: Record<string, unknown>;
  created_at: string | null;
  published_at: string | null;
};

type ProductDetail = Product & {
  included_assets: { kind: string; ref: string; alias?: string }[];
  dependencies: { kind: string; ref: string; requirement: string; alias?: string }[];
  countries: string[];
  pricing: Record<string, unknown>;
  entitlements: Record<string, unknown>;
};

const TYPE_LABEL: Record<string, string> = {
  INTEGRATION: "Integración",
  WORKFLOW_TEMPLATE: "Workflow",
  AGENT_TEMPLATE: "Agente",
  INTELLIGENCE_PACK: "Intelligence Pack",
  BUSINESS_PACK: "Business Pack",
  SEMANTIC_PACK: "Semantic Pack",
  COMPOSITE_PACK: "Composite",
};

const STATUS_BADGE: Record<string, string> = {
  DRAFT: "badge-muted",
  INTERNAL_TEST: "badge-info",
  SECURITY_REVIEW: "badge-warning",
  PRODUCT_REVIEW: "badge-warning",
  READY: "badge-success",
  PUBLISHED: "badge-success",
  PAUSED: "badge-warning",
  DEPRECATED: "badge-danger",
  END_OF_LIFE: "badge-danger",
};

type Tab = "overview" | "products" | "lab";

export default function MarketplaceFactoryPage() {
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<Product | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [impact, setImpact] = useState<{ installations: number; dependent_products: unknown[] } | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mapKey, setMapKey] = useState("legal_name");
  const [mapPath, setMapPath] = useState("razonSocial");
  const [sample, setSample] = useState("{\"razonSocial\": \"ACME SAC\", \"estado\": \"ACTIVO\"}");
  const [normalized, setNormalized] = useState<string>("");

  async function loadOverview() {
    if (!session) return;
    setError("");
    try {
      const data = await platformApi<Overview>("/api/v1/platform/marketplace/overview", {
        token: session.token,
      });
      setOverview(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function loadProducts() {
    if (!session) return;
    try {
      const data = await platformApi<{ products: Product[] }>("/api/v1/platform/marketplace/products", {
        token: session.token,
      });
      setProducts(data.products || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  function openTab(t: Tab) {
    setTab(t);
    setError("");
    setNotice("");
    if (t === "overview") void loadOverview();
    if (t === "products") void loadProducts();
  }

  useEffect(() => {
    void loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function migrateLegacy() {
    if (!session) return;
    setBusy("migrate");
    setError("");
    setNotice("");
    try {
      const r = await platformApi<{ created: number; skipped: string[] }>(
        "/api/v1/platform/marketplace/migrate-legacy",
        { method: "POST", token: session.token, body: "{}" }
      );
      setNotice(`Migración legacy: ${r.created} productos creados.`);
      await loadOverview();
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function openDetail(p: Product) {
    if (!session) return;
    setSelected(p);
    setDetail(null);
    setImpact(null);
    try {
      const [d, imp] = await Promise.all([
        platformApi<ProductDetail>(`/api/v1/platform/marketplace/products/${p.id}`, { token: session.token }),
        platformApi<{ installations: number; dependent_products: unknown[] }>(
          `/api/v1/platform/marketplace/products/${p.id}/impact`,
          { token: session.token }
        ),
      ]);
      setDetail(d);
      setImpact(imp);
      setTab("products");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function transition(status: string) {
    if (!session || !selected) return;
    setBusy(`t-${status}`);
    setError("");
    try {
      await platformApi(`/api/v1/platform/marketplace/products/${selected.id}/transition`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ status }),
      });
      setNotice(`Producto → ${status}.`);
      await openDetail(selected);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function newVersion() {
    if (!session || !selected) return;
    setBusy("version");
    setError("");
    try {
      await platformApi(`/api/v1/platform/marketplace/products/${selected.id}/versions`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ version: selected.version + 1 }),
      });
      setNotice(`Nueva versión v${selected.version + 1} creada (DRAFT).`);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function runLab() {
    if (!session) return;
    setBusy("lab");
    setError("");
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(sample);
      } catch {
        setError("Sample JSON inválido.");
        setBusy("");
        return;
      }
      const r = await platformApi<{ normalized: Record<string, unknown> }>(
        "/api/v1/platform/marketplace/test/output-normalizer",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ output_map: { [mapKey]: mapPath }, sample: parsed }),
        }
      );
      setNormalized(JSON.stringify(r.normalized, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketplace Factory"
        subtitle="El Control Center convierte capacidades de plataforma en productos vendibles para los tenants."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <p className="rounded-md border border-border bg-bg px-3 py-2 text-sm text-text">{notice}</p>}

      <div className="flex flex-wrap gap-1 border-b border-border pb-2">
        {(
          [
            ["overview", "Overview", Factory],
            ["products", "Products", Package],
            ["lab", "Test Lab", TestTube],
          ] as [Tab, string, React.ComponentType<{ size?: number }>][]
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            className={`btn min-h-10 gap-1.5 rounded-md px-3 text-sm ${tab === id ? "btn-primary" : "btn-ghost text-muted"}`}
            onClick={() => openTab(id)}
          >
            <Icon size={16} aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" &&
        (overview ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5" data-testid="factory-overview">
            {[
              { label: "Productos", value: overview.products_total },
              { label: "Publicados", value: overview.products_published },
              { label: "Borradores", value: overview.products_drafts },
              { label: "Installs de tenants", value: overview.tenant_installations },
              { label: "Integraciones en catálogo", value: overview.library.integrations },
            ].map((s) => (
              <div key={s.label} className="rounded-md border border-border bg-surface p-3">
                <p className="text-2xl font-semibold text-text">{s.value}</p>
                <p className="text-xs text-muted">{s.label}</p>
              </div>
            ))}
            <div className="col-span-2 rounded-md border border-border bg-surface p-4 sm:col-span-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-text">Fábrica de productos</p>
                  <p className="mt-1 text-xs text-muted">
                    {overview.library.workflow_templates} workflow templates · {overview.library.agents} agentes ·
                    {overview.palette.actions.length} acciones · {overview.palette.agents.length} agentes de paleta
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost gap-1.5 text-sm"
                  disabled={busy === "migrate"}
                  onClick={() => void migrateLegacy()}
                >
                  <ArrowClockwise size={16} aria-hidden />
                  {busy === "migrate" ? "Migrando…" : "Migrar legacy (manifests + workflows)"}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <SkeletonBlock className="h-28" />
        ))}

      {tab === "products" && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted">{products.length} productos</p>
            <button
              type="button"
              className="btn btn-primary min-h-10 gap-1.5 text-sm"
              onClick={() => setCreating(true)}
            >
              <Plus size={16} aria-hidden />
              Nuevo producto
            </button>
          </div>
          {products.length === 0 ? (
            <div data-testid="factory-products" className="rounded-md border border-border bg-surface p-6 text-sm text-muted">
              Sin productos todavía. Crea el primero con el Product Studio.
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2" data-testid="factory-products">
              {products.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="rounded-md border border-border bg-surface p-4 text-left transition-colors hover:border-accent"
                  onClick={() => void openDetail(p)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Storefront size={16} className="text-faint" aria-hidden />
                      <p className="text-sm font-semibold text-text">{p.name}</p>
                    </div>
                    <span className={`badge ${STATUS_BADGE[p.status] ?? "badge-muted"}`}>{p.status}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{p.short_description || "—"}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-faint">
                    <span className="badge badge-muted">{TYPE_LABEL[p.product_type] ?? p.product_type}</span>
                    <span className="badge badge-muted">v{p.version}</span>
                    <span className="badge badge-muted">{p.category}</span>
                    <span className="badge badge-muted">
                      {(p.pricing as { model?: string } | undefined)?.model ?? "FREE"}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "lab" && (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="factory-lab">
          <div className="rounded-md border border-border bg-surface p-4">
            <div className="flex items-center gap-2">
              <Flask size={18} aria-hidden />
              <p className="text-sm font-medium text-text">Output Normalizer</p>
            </div>
            <p className="mt-1 text-xs text-muted">
              Mapea la respuesta del proveedor a un output estable sin llamadas externas.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted">
                Campo de salida
                <input
                  className="input mt-1 w-full"
                  value={mapKey}
                  onChange={(e) => setMapKey(e.target.value)}
                  placeholder="legal_name"
                />
              </label>
              <label className="block text-xs text-muted">
                Ruta en la respuesta
                <input
                  className="input mt-1 w-full"
                  value={mapPath}
                  onChange={(e) => setMapPath(e.target.value)}
                  placeholder="razonSocial"
                />
              </label>
            </div>
            <label className="mt-3 block text-xs text-muted">
              Sample de respuesta del proveedor (JSON)
              <textarea
                className="input mt-1 w-full font-mono text-xs"
                rows={5}
                value={sample}
                onChange={(e) => setSample(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn btn-primary mt-3 min-h-10 gap-1.5 text-sm"
              disabled={busy === "lab"}
              onClick={() => void runLab()}
            >
              <TestTube size={16} aria-hidden />
              {busy === "lab" ? "Probando…" : "Probar mapeo"}
            </button>
          </div>
          <div className="rounded-md border border-border bg-surface p-4">
            <p className="text-sm font-medium text-text">Output normalizado</p>
            <pre className="mt-2 min-h-40 overflow-auto rounded-md border border-border bg-bg p-3 font-mono text-xs text-text">
              {normalized || "El resultado aparecerá aquí…"}
            </pre>
          </div>
        </div>
      )}

      {creating && (
        <ProductWizard
          palette={overview?.palette}
          onClose={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false);
            setNotice("Producto guardado.");
            await loadProducts();
          }}
        />
      )}

      {selected && detail && (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-6">
          <div className="max-h-[92dvh] w-full max-w-3xl overflow-y-auto rounded-t-lg border border-border bg-surface p-5 sm:rounded-lg">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold text-text">{detail.name}</h2>
                  <span className={`badge ${STATUS_BADGE[detail.status] ?? "badge-muted"}`}>
                    {detail.status} · v{detail.version}
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted">{detail.short_description || "—"}</p>
              </div>
              <button
                type="button"
                className="btn btn-ghost min-h-9 min-w-9 rounded-md"
                aria-label="Cerrar detalle"
                onClick={() => setSelected(null)}
              >
                ✕
              </button>
            </div>

            {impact && (
              <div className="mt-4 grid grid-cols-2 gap-3 rounded-md border border-border bg-bg p-3 text-center">
                <div>
                  <p className="text-xl font-semibold text-text">{impact.installations}</p>
                  <p className="text-xs text-muted">Instalaciones activas</p>
                </div>
                <div>
                  <p className="text-xl font-semibold text-text">{impact.dependent_products.length}</p>
                  <p className="text-xs text-muted">Productos dependientes</p>
                </div>
              </div>
            )}

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="rounded-md border border-border bg-bg p-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-faint">Incluye</p>
                <ul className="mt-2 space-y-1.5">
                  {detail.included_assets.length === 0 && <li className="text-xs text-muted">Sin assets aún</li>}
                  {detail.included_assets.map((a, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs text-text">
                      <CheckCircle size={13} className="text-accent" aria-hidden />
                      {a.kind} · {a.ref}
                      {a.alias ? ` (${a.alias})` : ""}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-md border border-border bg-bg p-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-faint">Dependencias</p>
                <ul className="mt-2 space-y-1.5">
                  {detail.dependencies.length === 0 && <li className="text-xs text-muted">Sin dependencias</li>}
                  {detail.dependencies.map((d, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs text-text">
                      <CaretUp size={12} className="text-faint" aria-hidden />
                      {d.kind}:{d.ref} ({d.requirement})
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-4 rounded-md border border-border bg-bg p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-faint">Pricing</p>
              <pre className="mt-1 overflow-auto font-mono text-xs text-text">
                {JSON.stringify(detail.pricing, null, 2)}
              </pre>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-ghost gap-1.5 text-sm"
                disabled={busy === "version"}
                onClick={() => void newVersion()}
              >
                <CaretDown size={15} aria-hidden />
                Nueva versión (clon)
              </button>
              {["READY", "PUBLISHED", "PAUSED"].map((st) => (
                <button
                  key={st}
                  type="button"
                  className={`btn min-h-9 gap-1.5 text-sm ${st === "PUBLISHED" ? "btn-primary" : "btn-ghost"}`}
                  disabled={busy === `t-${st}` || detail.status === st}
                  onClick={() => void transition(st)}
                >
                  {st === "PUBLISHED" && <RocketLaunch size={15} aria-hidden />}
                  {st === "READY" && <Factory size={15} aria-hidden />}
                  {st}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProductWizard({
  palette,
  onClose,
  onSaved,
}: {
  palette: Overview["palette"] | undefined;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { session } = usePlatformAuth();
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [type, setType] = useState("BUSINESS_PACK");
  const [category, setCategory] = useState("operations");
  const [countries, setCountries] = useState("PE");
  const [shortDesc, setShortDesc] = useState("");
  const [integrations, setIntegrations] = useState<string[]>([]);
  const [workflows, setWorkflows] = useState<string[]>([]);
  const [pricingModel, setPricingModel] = useState("FREE");

  async function save() {
    if (!session) return;
    setBusy(true);
    setError("");
    const assets = [
      ...integrations.map((ref) => ({ kind: "integration", ref, alias: ref })),
      ...workflows.map((ref) => ({ kind: "workflow_template", ref, alias: ref })),
    ];
    try {
      await platformApi(
        "/api/v1/platform/marketplace/products",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({
            slug,
            name,
            short_description: shortDesc,
            product_type: type,
            category,
            countries: countries.split(",").map((c) => c.trim()).filter(Boolean),
            pricing: { model: pricingModel },
            entitlements: {},
            dependencies: [],
            included_assets: assets,
            installation_flow: [],
            status: "DRAFT",
          }),
        }
      );
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  const toggle = (list: string[], set: (v: string[]) => void, item: string) => {
    set(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-6">
      <div className="max-h-[92dvh] w-full max-w-2xl overflow-y-auto rounded-t-lg border border-border bg-surface p-5 sm:rounded-lg">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-text">Nuevo producto</h2>
            <p className="text-xs text-muted">Paso {step} de 2 — Product Studio</p>
          </div>
          <button
            type="button"
            className="btn btn-ghost min-h-9 min-w-9 rounded-md"
            aria-label="Cerrar wizard"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        {error && <ErrorInline>{error}</ErrorInline>}

        {step === 1 && (
          <div className="mt-4 space-y-3">
            <label className="block text-xs text-muted">
              Nombre del producto
              <input className="input mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder="Peru Business Verification" />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted">
                Slug
                <input className="input mt-1 w-full font-mono" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="peru-business-verification" />
              </label>
              <label className="block text-xs text-muted">
                Tipo
                <select className="input mt-1 w-full" value={type} onChange={(e) => setType(e.target.value)}>
                  {Object.entries(TYPE_LABEL).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted">
                Categoría
                <input className="input mt-1 w-full" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="operations" />
              </label>
              <label className="block text-xs text-muted">
                Países (ISO, coma)
                <input className="input mt-1 w-full" value={countries} onChange={(e) => setCountries(e.target.value)} placeholder="PE,CL,MX" />
              </label>
            </div>
            <label className="block text-xs text-muted">
              Descripción corta (what it does)
              <textarea className="input mt-1 w-full" rows={2} value={shortDesc} onChange={(e) => setShortDesc(e.target.value)} placeholder="Verifica un negocio en Perú: SUNAT + workflow + reporte." />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="btn btn-ghost text-sm" onClick={onClose}>Cancelar</button>
              <button type="button" className="btn btn-primary text-sm" disabled={!name.trim() || !slug.trim()} onClick={() => setStep(2)}>
                Siguiente: incluye
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="mt-4 space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-faint">Integraciones</p>
              <div className="mt-2 max-h-44 space-y-1.5 overflow-y-auto rounded-md border border-border bg-bg p-2">
                {(palette?.integrations ?? []).map((i) => (
                  <label key={i.slug} className="flex items-center gap-2 text-xs text-text">
                    <input type="checkbox" className="accent-[var(--accent)]" checked={integrations.includes(i.slug)} onChange={() => toggle(integrations, setIntegrations, i.slug)} />
                    {i.name} <span className="text-faint">({i.slug})</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-faint">Workflow templates</p>
              <div className="mt-2 max-h-44 space-y-1.5 overflow-y-auto rounded-md border border-border bg-bg p-2">
                {(palette?.workflow_templates ?? []).map((w) => (
                  <label key={w.slug} className="flex items-center gap-2 text-xs text-text">
                    <input type="checkbox" className="accent-[var(--accent)]" checked={workflows.includes(w.slug)} onChange={() => toggle(workflows, setWorkflows, w.slug)} />
                    {w.name} <span className="text-faint">({w.slug})</span>
                  </label>
                ))}
              </div>
            </div>
            <label className="block text-xs text-muted">
              Pricing model
              <select className="input mt-1 w-full" value={pricingModel} onChange={(e) => setPricingModel(e.target.value)}>
                {["FREE", "ONE_TIME", "SUBSCRIPTION", "PER_USE", "BASE_PLUS_USAGE", "PLAN_INCLUDED", "CUSTOM"].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
            <div className="mt-5 flex justify-between gap-2">
              <button type="button" className="btn btn-ghost text-sm" onClick={() => setStep(1)}>← Volver</button>
              <div className="flex gap-2">
                <button type="button" className="btn btn-ghost text-sm" onClick={onClose}>Cancelar</button>
                <button type="button" className="btn btn-primary gap-1.5 text-sm" disabled={busy} onClick={() => void save()}>
                  <Plus size={15} aria-hidden />
                  {busy ? "Guardando…" : "Guardar producto"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}