import {
  ArrowClockwise,
  CheckCircle,
  Download,
  MagnifyingGlass,
  Receipt,
  SquaresFour,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Input,
  PageHeader,
  Panel,
  ResultCount,
  Select,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Toolbar,
} from "../../components/ui";
import { ProductCard } from "../../components/marketplace/ProductCard";
import { ProductDetailDrawer } from "../../components/marketplace/ProductDetailDrawer";
import {
  CATEGORY_LABEL,
  relativeTime,
  SURFACE_LABEL,
  TYPE_LABEL,
  type CatalogFacets,
  type MarketplaceProduct,
  type ProductInstall,
} from "../../components/marketplace/model";

type Tab = "discover" | "all" | "categories" | "installed" | "updates" | "purchases";

export default function MarketplacePage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<Tab>("discover");
  const [products, setProducts] = useState<MarketplaceProduct[]>([]);
  const [installs, setInstalls] = useState<ProductInstall[]>([]);
  const [facets, setFacets] = useState<CatalogFacets | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [surface, setSurface] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const auth = { token: session?.token, organizationId: session?.organizationId };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalog, mine, facetsData] = await Promise.all([
        api<{ products: MarketplaceProduct[] }>("/api/v1/products", auth),
        api<{ installs: ProductInstall[] }>("/api/v1/products/installs", auth),
        api<CatalogFacets>("/api/v1/products/categories", auth).catch(() => null),
      ]);
      setProducts(catalog.products);
      setInstalls(mine.installs);
      if (facetsData) setFacets(facetsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos cargar el Marketplace");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- auth derivado de la sesión
  }, [session?.token, session?.organizationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const installByProduct = useMemo(
    () => new Map(installs.map((i) => [i.product_id, i])),
    [installs]
  );
  const updates = useMemo(() => installs.filter((i) => i.update_available), [installs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products.filter((p) => {
      if (category && p.category !== category) return false;
      if (surface && !(p.applies_to || []).includes(surface)) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        (p.short_description || "").toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q)
      );
    });
  }, [products, query, category, surface]);

  async function installProduct(product: MarketplaceProduct) {
    setBusy(product.id);
    setError(null);
    try {
      await api(`/api/v1/products/${product.id}/install`, {
        method: "POST",
        ...auth,
        body: JSON.stringify({ answers: {} }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos instalar el producto");
    } finally {
      setBusy(null);
    }
  }

  async function updateInstall(install: ProductInstall) {
    setBusy(install.id);
    setError(null);
    try {
      await api(`/api/v1/products/installs/${install.id}/update`, {
        method: "POST",
        ...auth,
        body: JSON.stringify({}),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos actualizar el producto");
    } finally {
      setBusy(null);
    }
  }

  const categoryKeys =
    facets?.categories.map((c) => c.key) ?? [...new Set(products.map((p) => p.category))];
  const surfaceKeys =
    facets?.applies_to.map((s) => s.key) ?? [...new Set(products.flatMap((p) => p.applies_to || []))];

  return (
    <div className="page flex flex-col gap-5">
      <PageHeader
        title="Marketplace"
        subtitle="Un solo catálogo para todo Zent: integraciones, workflows, agentes y packs. Se usa desde Workflows, Agents y Knowledge, y se administra desde el Control Center."
        actions={
          <Button
            variant="secondary"
            leadingIcon={ArrowClockwise}
            onClick={() => void load()}
            loading={loading}
          >
            Actualizar
          </Button>
        }
      />

      {error && <ErrorInline message={error} />}

      <Tabs value={tab} onValueChange={(next) => setTab(next as Tab)}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="discover" icon={Storefront}>
            Descubrir
          </TabsTrigger>
          <TabsTrigger value="all" icon={MagnifyingGlass}>
            Todos
          </TabsTrigger>
          <TabsTrigger value="categories" icon={SquaresFour}>
            Categorías
          </TabsTrigger>
          <TabsTrigger value="installed" icon={CheckCircle}>
            Instalados
          </TabsTrigger>
          <TabsTrigger value="updates" icon={Download}>
            Actualizaciones{updates.length > 0 ? ` (${updates.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="purchases" icon={Receipt}>
            Mis compras
          </TabsTrigger>
        </TabsList>

        {/* Descubrir */}
        <TabsContent value="discover" className="pt-4">
          {updates.length > 0 && (
            <Panel className="mb-3 flex flex-wrap items-center justify-between gap-2 p-3">
              <span className="text-[13px] text-muted">
                Hay {updates.length} {updates.length === 1 ? "producto con actualización" : "productos con actualizaciones"} disponible
                {updates.length === 1 ? "" : "s"}.
              </span>
              <Button size="sm" variant="secondary" onClick={() => setTab("updates")}>
                Ver actualizaciones
              </Button>
            </Panel>
          )}
          {loading ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <Skeleton className="h-[210px] rounded-xl" />
              <Skeleton className="h-[210px] rounded-xl" />
              <Skeleton className="h-[210px] rounded-xl" />
            </div>
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
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="marketplace-grid">
              {products.slice(0, 12).map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  install={installByProduct.get(product.id)}
                  busy={busy === product.id}
                  onOpen={(p) => setSelectedId(p.id)}
                  onInstall={(p) => void installProduct(p)}
                  onUpdate={(i) => void updateInstall(i)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Todos */}
        <TabsContent value="all" className="pt-4">
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
                className="w-48"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">Todas las categorías</option>
                {categoryKeys.map((key) => (
                  <option key={key} value={key}>
                    {CATEGORY_LABEL[key] ?? key}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Superficie"
                className="w-48"
                value={surface}
                onChange={(e) => setSurface(e.target.value)}
              >
                <option value="">Todas las superficies</option>
                {surfaceKeys.map((key) => (
                  <option key={key} value={key}>
                    {SURFACE_LABEL[key] ?? key}
                  </option>
                ))}
              </Select>
            </div>
            <ResultCount shown={filtered.length} total={products.length} noun="productos" />
          </Toolbar>

          {loading ? (
            <Skeleton className="mt-3 h-[320px] rounded-xl" />
          ) : filtered.length === 0 ? (
            <Panel className="mt-3">
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
                      setSurface("");
                    }}
                  >
                    Limpiar filtros
                  </Button>
                }
              />
            </Panel>
          ) : (
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  install={installByProduct.get(product.id)}
                  busy={busy === product.id}
                  onOpen={(p) => setSelectedId(p.id)}
                  onInstall={(p) => void installProduct(p)}
                  onUpdate={(i) => void updateInstall(i)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Categorías */}
        <TabsContent value="categories" className="pt-4">
          {!facets || facets.categories.length === 0 ? (
            <Panel>
              <EmptyState compact icon={SquaresFour} title="Sin categorías todavía" body="El catálogo aún no tiene productos visibles." />
            </Panel>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {facets.categories.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className="flex items-center justify-between gap-2 rounded-lg border border-border bg-overlay px-3.5 py-3 text-left text-sm transition-colors duration-150 hover:border-border-strong hover:text-accent"
                  onClick={() => {
                    setCategory(c.key);
                    setTab("all");
                  }}
                >
                  <span className="truncate font-medium">{CATEGORY_LABEL[c.key] ?? c.key}</span>
                  <Badge tone="neutral">{c.count}</Badge>
                </button>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Instalados */}
        <TabsContent value="installed" className="pt-4">
          {loading ? (
            <Skeleton className="h-[280px] rounded-xl" />
          ) : installs.length === 0 ? (
            <Panel>
              <EmptyState
                icon={CheckCircle}
                title="Aún no instalaste productos"
                body="Activá una integración, un workflow o un pack desde Descubrir. También puedes instalarlos desde Workflows, Agents o Knowledge."
                action={
                  <Button variant="secondary" leadingIcon={Storefront} onClick={() => setTab("discover")}>
                    Ver catálogo
                  </Button>
                }
              />
            </Panel>
          ) : (
            <div className="flex flex-col gap-3" data-testid="marketplace-installed">
              {installs.map((install) => (
                <Panel key={install.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="text-sm font-semibold text-text transition-colors hover:text-accent"
                        onClick={() => setSelectedId(install.product_id)}
                      >
                        {install.product.name}
                      </button>
                      <Badge tone="neutral">{TYPE_LABEL[install.product.product_type] ?? install.product.product_type}</Badge>
                      <span className="chip">v{install.product_version}</span>
                      {install.update_available && <Badge tone="accent" icon={Download}>Actualización v{install.latest_version}</Badge>}
                    </div>
                    <p className="mt-1 text-xs text-faint">
                      Usado por {install.health.workflows ?? 0} workflows · {install.health.agents ?? 0} agentes
                      {install.last_used_at ? ` · última llamada ${relativeTime(install.last_used_at)}` : " · sin uso aún"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setSelectedId(install.product_id)}>
                      Estado y configuración
                    </Button>
                    {install.update_available && (
                      <Button
                        size="sm"
                        variant="primary"
                        leadingIcon={Download}
                        loading={busy === install.id}
                        onClick={() => void updateInstall(install)}
                      >
                        Actualizar
                      </Button>
                    )}
                  </div>
                </Panel>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Actualizaciones */}
        <TabsContent value="updates" className="pt-4">
          {loading ? (
            <Skeleton className="h-[220px] rounded-xl" />
          ) : updates.length === 0 ? (
            <Panel>
              <EmptyState
                icon={CheckCircle}
                title="Todo al día"
                body="Ninguno de tus productos instalados tiene una versión nueva publicada."
              />
            </Panel>
          ) : (
            <div className="flex flex-col gap-2">
              {updates.map((install) => (
                <Panel key={install.id} className="flex flex-wrap items-center justify-between gap-2 p-3.5">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-text">{install.product.name}</p>
                    <p className="text-xs text-faint">
                      v{install.product_version} → v{install.latest_version} ·{" "}
                      {CATEGORY_LABEL[install.product.category] ?? install.product.category}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="primary"
                    leadingIcon={Download}
                    loading={busy === install.id}
                    onClick={() => void updateInstall(install)}
                  >
                    Actualizar
                  </Button>
                </Panel>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Mis compras */}
        <TabsContent value="purchases" className="pt-4">
          <Panel>
            <EmptyState
              icon={Receipt}
              title="Todavía no hay compras"
              body="Los productos gratuitos se instalan sin generar órdenes. Cuando Zent habilite pagos y suscripciones, tus compras aparecerán acá."
              hint="No mostramos montos ni órdenes que no existan."
            />
          </Panel>
        </TabsContent>
      </Tabs>

      <ProductDetailDrawer
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        productId={selectedId}
        install={selectedId ? installByProduct.get(selectedId) : undefined}
        onInstall={installProduct}
        onUpdate={updateInstall}
        onUninstalled={() => void load()}
      />
    </div>
  );
}
