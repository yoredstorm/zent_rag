import { ArrowClockwise, CheckCircle, Package, Plus, Storefront, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

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

type Install = {
  id: string;
  product_id: string;
  product_version: number;
  status: string;
  installed_assets: Record<string, string>;
  install_answers: Record<string, unknown>;
  created_at: string;
  product: { slug: string; name: string; product_type: string; short_description: string | null };
};

type InstallResult = {
  install_id: string;
  reused: boolean;
  status: string;
  installed_assets: Record<string, string>;
};

const TYPE_LABEL: Record<string, string> = {
  INTEGRATION: "Integración",
  WORKFLOW_TEMPLATE: "Workflow",
  AGENT_TEMPLATE: "Agente",
  INTELLIGENCE_PACK: "Intelligence",
  BUSINESS_PACK: "Business Pack",
  SEMANTIC_PACK: "Semantic",
  COMPOSITE_PACK: "Composite",
};

const TYPE_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  INTEGRATION: Package,
  WORKFLOW_TEMPLATE: ArrowClockwise,
  AGENT_TEMPLATE: Plus,
};

export default function MarketplaceProductsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<"discover" | "installed">("discover");
  const [products, setProducts] = useState<Product[]>([]);
  const [installs, setInstalls] = useState<Install[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [lastResult, setLastResult] = useState<{ product: string; result: InstallResult } | null>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [catalog, mine] = await Promise.all([
        api<{ products: Product[] }>("/api/v1/products", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ installs: Install[] }>("/api/v1/products/installs", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setProducts(catalog.products || []);
      setInstalls(mine.installs || []);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setLoaded(true);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function install(p: Product) {
    if (!session) return;
    setBusy(p.id);
    setError("");
    setLastResult(null);
    try {
      const r = await api<InstallResult>(`/api/v1/products/${p.id}/install`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ answers: {} }),
      });
      setLastResult({ product: p.name, result: r });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function uninstall(i: Install) {
    if (!session) return;
    setBusy(`u-${i.id}`);
    setError("");
    try {
      await api(`/api/v1/products/installs/${i.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketplace"
        subtitle="Capacidades de negocio de Zent: integraciones, workflows, agentes y packs listos para activar."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {lastResult && (
        <div className="rounded-md border border-border bg-surface p-3 text-sm" data-testid="install-result">
          <div className="flex items-center gap-2 font-medium text-text">
            <CheckCircle size={16} className="text-accent" aria-hidden />
            {lastResult.product} instalado
            {lastResult.result.reused ? " (ya estaba activo)" : ""}
          </div>
          <pre className="mt-2 overflow-auto rounded-md border border-border bg-bg p-2 font-mono text-[11px] text-muted">
            {JSON.stringify(lastResult.result.installed_assets, null, 2)}
          </pre>
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-border pb-2">
        {(
          [
            ["discover", "Descubrir", Storefront],
            ["installed", "Instalados", CheckCircle],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            className={`btn min-h-10 gap-1.5 rounded-md px-3 text-sm ${tab === id ? "btn-primary" : "btn-ghost text-muted"}`}
            onClick={() => setTab(id)}
          >
            <Icon size={16} aria-hidden />
            {label}
            {id === "installed" && installs.length > 0 && (
              <span className="badge badge-muted">{installs.length}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "discover" && (
        <div data-testid="product-catalog" className="space-y-3">
          {!loaded ? (
            <SkeletonBlock className="h-28" />
          ) : products.length === 0 ? (
            <p className="rounded-md border border-border bg-surface p-6 text-sm text-muted">
              El catálogo aún no tiene productos publicados. El Control Center los publica desde el Marketplace Factory.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {products.map((p) => {
                const Icon = TYPE_ICON[p.product_type] ?? Package;
                const model = (p.pricing as { model?: string })?.model ?? "FREE";
                return (
                  <div key={p.id} className="flex flex-col rounded-md border border-border bg-surface p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon size={16} className="text-faint" aria-hidden />
                        <span className={`badge ${TYPE_LABEL[p.product_type] ? "badge-info" : "badge-muted"}`}>
                          {TYPE_LABEL[p.product_type] ?? p.product_type}
                        </span>
                        <span className="badge badge-success">{model}</span>
                      </div>
                    </div>
                    <p className="mt-2 text-sm font-semibold text-text">{p.name}</p>
                    <p className="mt-1 line-clamp-3 flex-1 text-xs text-muted">{p.short_description || "—"}</p>
                    <button
                      type="button"
                      className="btn btn-primary mt-3 min-h-9 gap-1.5 text-sm"
                      disabled={busy === p.id}
                      onClick={() => void install(p)}
                    >
                      <Plus size={15} aria-hidden />
                      {busy === p.id ? "Instalando…" : "Instalar"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {tab === "installed" && (
        <div className="space-y-3" data-testid="product-installs">
          {installs.length === 0 && (
            <p className="rounded-md border border-border bg-surface p-6 text-sm text-muted">
              Aún no instalaste productos del catálogo.
            </p>
          )}
          {installs.map((i) => (
            <div key={i.id} className="rounded-md border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-text">{i.product.name}</p>
                    <span className="badge badge-muted">{TYPE_LABEL[i.product.product_type] ?? i.product.product_type}</span>
                    <span className="badge badge-muted">v{i.product_version}</span>
                    <span className={`badge ${i.status === "active" ? "badge-success" : "badge-warning"}`}>
                      {i.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{i.product.short_description || "—"}</p>
                  {Object.keys(i.installed_assets).length > 0 && (
                    <pre className="mt-2 max-h-32 overflow-auto rounded-md border border-border bg-bg p-2 font-mono text-[11px] text-muted">
                      {JSON.stringify(i.installed_assets, null, 2)}
                    </pre>
                  )}
                </div>
                <button
                  type="button"
                  className="btn btn-ghost min-h-9 gap-1.5 text-sm text-danger"
                  disabled={busy === `u-${i.id}`}
                  onClick={() => void uninstall(i)}
                >
                  <Trash size={15} aria-hidden />
                  Desinstalar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}