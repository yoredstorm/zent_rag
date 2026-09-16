import {
  ArrowClockwise,
  Briefcase,
  CheckCircle,
  MagnifyingGlass,
  Package,
  Plus,
  Sparkle,
  Stack,
  Storefront,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  Drawer,
  EmptyState,
  ErrorInline,
  Input,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  Skeleton,
  StatusBadge,
  Toolbar,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

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
  INTELLIGENCE_PACK: Sparkle,
  BUSINESS_PACK: Briefcase,
  SEMANTIC_PACK: MagnifyingGlass,
  COMPOSITE_PACK: Stack,
};

/** `pricing.model` llega como enum del backend; no se inventan montos. */
function priceLabel(pricing: Record<string, unknown>): string {
  const model = typeof pricing?.model === "string" ? pricing.model : "";
  if (!model) return "Gratis";
  return model === "FREE" || model.toUpperCase() === "FREE" ? "Gratis" : model;
}

/** Error de carga del catálogo o de las instalaciones: no se disfraza de "sin datos". */
function LoadErrorPanel({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <Panel>
      <EmptyState
        icon={WarningCircle}
        title={title}
        body={message}
        hint="Revisá la conexión y volvé a intentar."
        action={
          <Button variant="secondary" leadingIcon={ArrowClockwise} onClick={onRetry}>
            Reintentar
          </Button>
        }
      />
    </Panel>
  );
}

export default function MarketplaceProductsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<"discover" | "installed">("discover");
  const [products, setProducts] = useState<Product[]>([]);
  const [installs, setInstalls] = useState<Install[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [lastResult, setLastResult] = useState<{ product: string; result: InstallResult } | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [type, setType] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);

  async function load() {
    if (!session) return;
    setLoadError("");
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
      setLoadError(e instanceof Error ? e.message : "Error");
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

  const categories = useMemo(
    () => Array.from(new Set(products.map((p) => p.category).filter(Boolean))).sort(),
    [products],
  );
  const types = useMemo(
    () => Array.from(new Set(products.map((p) => p.product_type).filter(Boolean))).sort(),
    [products],
  );
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products.filter((p) => {
      if (category && p.category !== category) return false;
      if (type && p.product_type !== type) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        (p.short_description ?? "").toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q)
      );
    });
  }, [products, query, category, type]);

  const installedProductIds = useMemo(
    () => new Set(installs.map((i) => i.product_id)),
    [installs],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketplace"
        subtitle="Capacidades de negocio de Zent: integraciones, workflows, agentes y packs listos para activar."
      />
      <ErrorInline message={error} />
      <ErrorInline
        message={loadError && (products.length > 0 || installs.length > 0) ? loadError : ""}
      />
      {lastResult && (
        <Panel className="p-4" data-testid="install-result">
          <div className="flex items-center gap-2 font-medium text-text">
            <CheckCircle size={16} className="text-ok" aria-hidden />
            {lastResult.product} instalado
            {lastResult.result.reused ? " (ya estaba activo)" : ""}
          </div>
          <CodeBlock
            className="mt-3"
            language="json"
            filename="assets instalados"
            code={JSON.stringify(lastResult.result.installed_assets, null, 2)}
            maxHeight={200}
          />
        </Panel>
      )}

      <div className="tabs">
        <button
          type="button"
          className="tab"
          aria-current={tab === "discover" ? "page" : undefined}
          onClick={() => setTab("discover")}
        >
          <Storefront size={16} aria-hidden />
          Descubrir
        </button>
        <button
          type="button"
          className="tab"
          aria-current={tab === "installed" ? "page" : undefined}
          onClick={() => setTab("installed")}
        >
          <CheckCircle size={16} aria-hidden />
          Instalados
          {installs.length > 0 && <Badge>{installs.length}</Badge>}
        </button>
      </div>

      {tab === "discover" && (
        <div data-testid="product-catalog" className="flex flex-col gap-3">
          {!loaded ? (
            <Skeleton className="h-[420px] rounded-lg" />
          ) : products.length === 0 && loadError ? (
            <LoadErrorPanel
              title="No pudimos cargar el catálogo"
              message={loadError}
              onRetry={() => void load()}
            />
          ) : products.length === 0 ? (
            <Panel>
              <EmptyState
                icon={Storefront}
                title="El catálogo está vacío"
                body="El Control Center publica los productos desde el Marketplace Factory."
                hint="Cuando se publique el primero, va a aparecer acá para instalar."
              />
            </Panel>
          ) : (
            <>
              <Toolbar className="justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    icon={MagnifyingGlass}
                    aria-label="Buscar productos"
                    placeholder="Buscar por nombre, descripción o slug…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    className="w-64"
                  />
                  <Select
                    aria-label="Categoría"
                    className="w-44"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="">Todas las categorías</option>
                    {categories.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                  <Select
                    aria-label="Tipo de producto"
                    className="w-44"
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                  >
                    <option value="">Todos los tipos</option>
                    {types.map((t) => (
                      <option key={t} value={t}>
                        {TYPE_LABEL[t] ?? t}
                      </option>
                    ))}
                  </Select>
                </div>
                <ResultCount shown={filtered.length} total={products.length} noun="productos" />
              </Toolbar>

              {filtered.length === 0 ? (
                <Panel>
                  <EmptyState
                    compact
                    icon={MagnifyingGlass}
                    title="Sin resultados"
                    body="Ningún producto coincide con la búsqueda y los filtros actuales."
                    action={
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setQuery("");
                          setCategory("");
                          setType("");
                        }}
                      >
                        Limpiar filtros
                      </Button>
                    }
                  />
                </Panel>
              ) : (
                <Panel className="overflow-hidden">
                  <ul className="divide-y divide-border-soft">
                    {filtered.map((p) => {
                      const Icon = TYPE_ICON[p.product_type] ?? Package;
                      const installed = installedProductIds.has(p.id);
                      return (
                        <li key={p.id}>
                          <div className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-start sm:justify-between">
                            <div className="flex min-w-0 gap-3">
                              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-soft bg-raised text-accent">
                                <Icon size={17} aria-hidden />
                              </span>
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                  <button
                                    type="button"
                                    className="text-left text-sm font-semibold text-text transition-colors duration-150 hover:text-accent"
                                    onClick={() => setSelected(p)}
                                  >
                                    {p.name}
                                  </button>
                                  <StatusBadge status={p.status.toLowerCase()} />
                                  {installed && <Badge tone="ok">Instalado</Badge>}
                                  <Badge tone="info">{TYPE_LABEL[p.product_type] ?? p.product_type}</Badge>
                                  <span className="badge badge-muted">v{p.version}</span>
                                </div>
                                <p className="mt-1 line-clamp-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                                  {p.short_description || "Sin descripción todavía."}
                                </p>
                                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
                                  <span className="chip">{p.category || "general"}</span>
                                  <span>{priceLabel(p.pricing)}</span>
                                </div>
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-2 sm:pl-4">
                              <Button size="sm" variant="secondary" onClick={() => setSelected(p)}>
                                Ver detalle
                              </Button>
                              {!installed && (
                                <Button
                                  size="sm"
                                  variant="primary"
                                  leadingIcon={Plus}
                                  loading={busy === p.id}
                                  onClick={() => void install(p)}
                                >
                                  Instalar
                                </Button>
                              )}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </Panel>
              )}
            </>
          )}
        </div>
      )}

      {tab === "installed" && (
        <div className="flex flex-col gap-3" data-testid="product-installs">
          {!loaded ? (
            <Skeleton className="h-[280px] rounded-lg" />
          ) : installs.length === 0 && loadError ? (
            <LoadErrorPanel
              title="No pudimos cargar tus instalaciones"
              message={loadError}
              onRetry={() => void load()}
            />
          ) : installs.length === 0 ? (
            <Panel>
              <EmptyState
                icon={CheckCircle}
                title="Aún no instalaste productos"
                body="Activá una integración, un workflow o un pack desde la pestaña Descubrir."
                action={
                  <Button variant="secondary" leadingIcon={Storefront} onClick={() => setTab("discover")}>
                    Ver catálogo
                  </Button>
                }
              />
            </Panel>
          ) : (
            <Panel className="overflow-hidden">
              <PanelHeader
                title={`Instalados (${installs.length})`}
                description="Versión activa, estado real y assets que dejó cada instalación."
              />
              <ul className="divide-y divide-border-soft">
                {installs.map((i) => {
                  const assets = Object.entries(i.installed_assets ?? {});
                  return (
                    <li
                      key={i.id}
                      className="state-rail px-4 py-3.5"
                      data-state={i.status === "active" ? "ready" : "warning"}
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <p className="text-sm font-semibold text-text">{i.product.name}</p>
                            <StatusBadge status={i.status} />
                            <span className="badge badge-muted">v{i.product_version}</span>
                            <Badge tone="info">
                              {TYPE_LABEL[i.product.product_type] ?? i.product.product_type}
                            </Badge>
                          </div>
                          <p className="mt-1 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                            {i.product.short_description || "Sin descripción."}
                          </p>
                          <p className="mt-1 text-xs text-faint">
                            Instalado {fmtDateTime(i.created_at)}
                          </p>
                          {assets.length > 0 && (
                            <details className="mt-2">
                              <summary className="cursor-pointer text-xs text-muted transition-colors duration-150 hover:text-text">
                                Ver {assets.length === 1 ? "1 asset" : `${assets.length} assets`} instalados
                              </summary>
                              <CodeBlock
                                className="mt-2"
                                language="json"
                                code={JSON.stringify(i.installed_assets, null, 2)}
                                maxHeight={180}
                              />
                            </details>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <Button
                            size="sm"
                            variant="ghost"
                            leadingIcon={Trash}
                            className="text-danger"
                            loading={busy === `u-${i.id}`}
                            onClick={() => void uninstall(i)}
                          >
                            Desinstalar
                          </Button>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Panel>
          )}
        </div>
      )}

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.name ?? "Producto"}
        description={selected ? TYPE_LABEL[selected.product_type] ?? selected.product_type : undefined}
        width={480}
        footer={
          selected ? (
            installedProductIds.has(selected.id) ? (
              <Badge tone="ok" icon={CheckCircle}>
                Ya instalado
              </Badge>
            ) : (
              <Button
                variant="primary"
                leadingIcon={Plus}
                loading={busy === selected.id}
                onClick={() => void install(selected)}
              >
                Instalar
              </Button>
            )
          ) : undefined
        }
      >
        {selected && (
          <div className="flex flex-col gap-5">
            <p className="text-[13px] leading-relaxed text-muted">
              {selected.short_description || "Sin descripción todavía."}
            </p>
            <KeyValue
              columns={2}
              items={[
                { key: "Estado", value: <StatusBadge status={selected.status.toLowerCase()} /> },
                { key: "Categoría", value: selected.category || "general" },
                { key: "Versión", value: `v${selected.version}` },
                { key: "Precio", value: priceLabel(selected.pricing) },
                { key: "Slug", value: selected.slug, mono: true },
                {
                  key: "Publicado",
                  value: selected.published_at ? fmtDateTime(selected.published_at) : "sin publicar",
                },
              ]}
            />
            {(() => {
              const installed = installs.find((i) => i.product_id === selected.id);
              if (!installed) return null;
              return (
                <div className="rounded-md border border-border bg-raised p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={installed.status} />
                    <span className="text-xs text-faint">
                      Instalado {fmtDateTime(installed.created_at)}
                    </span>
                  </div>
                  {Object.keys(installed.installed_assets ?? {}).length > 0 && (
                    <CodeBlock
                      className="mt-3"
                      language="json"
                      filename="assets instalados"
                      code={JSON.stringify(installed.installed_assets, null, 2)}
                      maxHeight={200}
                    />
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </Drawer>
    </div>
  );
}
