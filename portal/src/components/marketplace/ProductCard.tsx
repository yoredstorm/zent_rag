import { Check, Download, GearSix } from "@phosphor-icons/react";
import { Badge, Button } from "../ui";
import {
  CATEGORY_LABEL,
  priceLabel,
  readinessMeta,
  SURFACE_LABEL,
  TYPE_LABEL,
  type MarketplaceProduct,
  type ProductInstall,
} from "./model";

type Props = {
  product: MarketplaceProduct;
  install?: ProductInstall;
  busy?: boolean;
  onOpen: (product: MarketplaceProduct) => void;
  onInstall?: (product: MarketplaceProduct) => void;
  onUpdate?: (install: ProductInstall) => void;
  compact?: boolean;
};

/** Iniciales del logo cuando el catálogo no trae imagen real. */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function ProductCard({
  product,
  install,
  busy = false,
  onOpen,
  onInstall,
  onUpdate,
  compact = false,
}: Props) {
  const meta = readinessMeta(install?.readiness);
  return (
    <article
      className="group flex h-full flex-col rounded-xl border border-border bg-overlay p-4 shadow-card transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-pop"
      data-testid="marketplace-product-card"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border-soft bg-raised text-accent"
        >
          {product.logo ? (
            <img src={product.logo} alt="" className="h-full w-full object-cover" />
          ) : (
            <span className="text-sm font-semibold">{initials(product.name)}</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="truncate text-sm font-semibold text-text">{product.name}</h3>
            {product.certification && (
              <Badge tone="info" icon={Check}>
                Verificado
              </Badge>
            )}
            {install && (
              <Badge tone={meta.tone} dot>
                {meta.label}
              </Badge>
            )}
            {install?.update_available && <Badge tone="accent" icon={Download}>Actualización</Badge>}
          </div>
          <p className="mt-0.5 truncate text-xs text-faint">
            {product.publisher ? `por ${product.publisher}` : "por Zent"}
            {" · "}
            {TYPE_LABEL[product.product_type] ?? product.product_type}
          </p>
        </div>
      </div>

      <p className="mt-3 line-clamp-2 text-[13px] leading-relaxed text-muted" data-testid="product-description">
        {product.short_description || "Sin descripción todavía."}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="chip">{CATEGORY_LABEL[product.category] ?? product.category}</span>
        {(product.applies_to || []).slice(0, 3).map((surface) => (
          <span key={surface} className="chip">
            {SURFACE_LABEL[surface] ?? surface}
          </span>
        ))}
      </div>

      {!compact && (product.capabilities || []).length > 0 && (
        <p className="mt-2 line-clamp-1 text-xs text-faint" title={product.capabilities.join(", ")}>
          Capacidades: {product.capabilities.slice(0, 3).join(", ")}
          {product.capabilities.length > 3 ? "…" : ""}
        </p>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-4">
        <span className="text-sm font-semibold text-text" data-testid="product-price">
          {priceLabel(product.pricing)}
        </span>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => onOpen(product)}>
            Ver detalle
          </Button>
          {!install && onInstall && (
            <Button size="sm" variant="primary" loading={busy} onClick={() => onInstall(product)}>
              Instalar
            </Button>
          )}
          {install?.update_available && onUpdate && (
            <Button size="sm" variant="secondary" leadingIcon={Download} onClick={() => onUpdate(install)}>
              Actualizar
            </Button>
          )}
          {install && !install.update_available && (
            <Button size="sm" variant="secondary" leadingIcon={GearSix} onClick={() => onOpen(product)}>
              Configurar
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
