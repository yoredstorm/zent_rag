import { MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Button, EmptyState, ErrorInline, Input, Modal, Skeleton } from "../ui";
import { ProductCard } from "./ProductCard";
import { SURFACE_LABEL, type MarketplaceProduct, type ProductInstall } from "./model";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Superficie de Zent que filtra el catálogo global (applies_to). */
  surface: "WORKFLOWS" | "AGENTS" | "KNOWLEDGE" | "DATA" | "INTEGRATIONS" | "PAYMENTS" | "CHANNELS" | "AUTOMATIONS";
  title?: string;
  /** Tras instalar (o si ya estaba), entrega el producto elegido al módulo. */
  onInstalled?: (product: MarketplaceProduct, install: ProductInstall) => void;
};

/**
 * Vista contextual FILTRADA del Marketplace global. No crea catálogo propio:
 * consulta /api/v1/products?applies_to=SURFACE e instala con el flujo único.
 */
export function MarketplaceSurfaceDialog({ open, onOpenChange, surface, title, onInstalled }: Props) {
  const { session } = useAuth();
  const [products, setProducts] = useState<MarketplaceProduct[]>([]);
  const [installs, setInstalls] = useState<ProductInstall[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [catalog, mine] = await Promise.all([
        api<{ products: MarketplaceProduct[] }>(
          `/api/v1/products?applies_to=${encodeURIComponent(surface)}`,
          { token: session?.token, organizationId: session?.organizationId }
        ),
        api<{ installs: ProductInstall[] }>("/api/v1/products/installs", {
          token: session?.token,
          organizationId: session?.organizationId,
        }),
      ]);
      setProducts(catalog.products);
      setInstalls(mine.installs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos cargar el Marketplace");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recarga solo al abrir/cambiar de superficie
  }, [open, surface]);

  const installByProduct = useMemo(
    () => new Map(installs.map((i) => [i.product_id, i])),
    [installs]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return products;
    return products.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.short_description || "").toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q)
    );
  }, [products, query]);

  async function install(product: MarketplaceProduct) {
    setBusy(product.id);
    setError(null);
    try {
      await api(`/api/v1/products/${product.id}/install`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({ answers: {} }),
      });
      const mine = await api<{ installs: ProductInstall[] }>("/api/v1/products/installs", {
        token: session?.token,
        organizationId: session?.organizationId,
      });
      setInstalls(mine.installs);
      const install = mine.installs.find((i) => i.product_id === product.id);
      if (install && onInstalled) onInstalled(product, install);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos instalar el producto");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title ?? `Agregar desde Marketplace · ${SURFACE_LABEL[surface] ?? surface}`}
      description="Estos productos vienen del Marketplace global: la instalación es la misma que verás en /marketplace."
      size="lg"
    >
      <div className="flex flex-col gap-3" data-testid={`marketplace-surface-${surface}`}>
        <Input
          icon={MagnifyingGlass}
          aria-label="Buscar en el marketplace"
          placeholder="Buscar productos…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {error && <ErrorInline message={error} />}
        {loading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Skeleton className="h-[180px] rounded-xl" />
            <Skeleton className="h-[180px] rounded-xl" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={MagnifyingGlass}
            title="Sin productos para esta superficie"
            body="Cuando el catálogo publique productos que apliquen acá, van a aparecer."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {filtered.map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                install={installByProduct.get(product.id)}
                busy={busy === product.id}
                compact
                onOpen={() => {
                  if (onInstalled && installByProduct.has(product.id)) {
                    onInstalled(product, installByProduct.get(product.id)!);
                  }
                }}
                onInstall={install}
              />
            ))}
          </div>
        )}
        <div className="flex justify-end">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cerrar
          </Button>
        </div>
      </div>
    </Modal>
  );
}
