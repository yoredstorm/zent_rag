import { ArrowSquareOut, Download, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Button, Drawer, EmptyState, ErrorInline, KeyValue, Modal, Skeleton } from "../ui";
import {
  CATEGORY_LABEL,
  priceLabel,
  readinessMeta,
  relativeTime,
  SURFACE_LABEL,
  TYPE_LABEL,
  type MarketplaceProduct,
  type ProductInstall,
} from "./model";

export type InstallationImpact = {
  install_id: string;
  product: { slug: string; name: string };
  assets: { alias: string; install_id: string }[];
  workflows: { id: string; name: string }[];
  agents: { id: string; name: string }[];
  products: { install_id: string; slug: string; name: string }[];
  message: string;
};

const SURFACE_ROUTE: Record<string, string> = {
  WORKFLOWS: "/workflows",
  AGENTS: "/agents",
  KNOWLEDGE: "/knowledge",
  DATA: "/knowledge",
  INTEGRATIONS: "/integrations",
  ANALYTICS: "/chat-insights",
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string | null;
  install?: ProductInstall;
  onInstall: (product: MarketplaceProduct) => Promise<void>;
  onUpdate: (install: ProductInstall) => Promise<void>;
  onUninstalled: () => void;
};

export function ProductDetailDrawer({
  open,
  onOpenChange,
  productId,
  install,
  onInstall,
  onUpdate,
  onUninstalled,
}: Props) {
  const { session } = useAuth();
  const [product, setProduct] = useState<MarketplaceProduct | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [impact, setImpact] = useState<InstallationImpact | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    if (!open || !productId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<MarketplaceProduct>(`/api/v1/products/${productId}`, {
      token: session?.token,
      organizationId: session?.organizationId,
    })
      .then((data) => {
        if (!cancelled) setProduct(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "No pudimos cargar el producto");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, productId, session?.token, session?.organizationId]);

  const meta = readinessMeta(install?.readiness);
  const health = install?.health ?? {};
  const children = health.children ?? [];

  async function openUninstall() {
    if (!install) return;
    setBusy(true);
    try {
      const data = await api<InstallationImpact>(`/api/v1/products/installs/${install.id}/impact`, {
        token: session?.token,
        organizationId: session?.organizationId,
      });
      setImpact(data);
      setConfirmOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos calcular el impacto");
    } finally {
      setBusy(false);
    }
  }

  async function confirmUninstall() {
    if (!install) return;
    setBusy(true);
    try {
      await api(`/api/v1/products/installs/${install.id}?cascade=false`, {
        method: "DELETE",
        token: session?.token,
        organizationId: session?.organizationId,
      });
      setConfirmOpen(false);
      onUninstalled();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos desinstalar el producto");
    } finally {
      setBusy(false);
    }
  }

  const route = (product?.applies_to || []).map((s) => SURFACE_ROUTE[s]).find(Boolean);
  const configKeys = Object.keys(product?.configuration_schema ?? {});
  const permissions = Object.entries(product?.security ?? {});

  return (
    <>
      <Drawer
        open={open}
        onOpenChange={onOpenChange}
        title={product?.name ?? "Producto"}
        description={product ? TYPE_LABEL[product.product_type] ?? product.product_type : undefined}
        width={560}
      >
        {loading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-24 rounded-lg" />
            <Skeleton className="h-40 rounded-lg" />
          </div>
        ) : error && !product ? (
          <ErrorInline message={error} />
        ) : product ? (
          <div className="flex flex-col gap-5 pb-2">
            {/* Header */}
            <div className="flex flex-wrap items-center gap-2">
              {install ? (
                <Badge tone={meta.tone} dot>
                  {meta.label}
                </Badge>
              ) : (
                <Badge tone="accent">Disponible</Badge>
              )}
              {install?.update_available && (
                <Badge tone="info" icon={Download}>
                  Actualización {install.latest_version} disponible
                </Badge>
              )}
              {product.certification && <Badge tone="info">Verificado</Badge>}
              <span className="chip">v{product.version}</span>
              <span className="chip">{CATEGORY_LABEL[product.category] ?? product.category}</span>
              <span className="ml-auto text-sm font-semibold">{priceLabel(product.pricing)}</span>
            </div>

            {/* Acciones */}
            <div className="flex flex-wrap gap-2">
              {!install && (
                <Button
                  variant="primary"
                  loading={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await onInstall(product);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Instalar
                </Button>
              )}
              {install?.update_available && (
                <Button
                  variant="primary"
                  leadingIcon={Download}
                  loading={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await onUpdate(install);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Actualizar a v{install.latest_version}
                </Button>
              )}
              {route && (
                <Button
                  variant="secondary"
                  leadingIcon={ArrowSquareOut}
                  onClick={() => {
                    window.location.assign(route);
                  }}
                >
                  Abrir módulo
                </Button>
              )}
              {install && (
                <Button variant="danger" leadingIcon={Trash} onClick={() => void openUninstall()}>
                  Desinstalar
                </Button>
              )}
            </div>

            {error && <ErrorInline message={error} />}

            {/* Salud de la instalación (datos reales) */}
            {install && (
              <section aria-label="Estado de la instalación" className="rounded-lg border border-border-soft bg-raised p-3">
                <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <div>
                    <p className="text-faint">Versión instalada</p>
                    <p className="font-semibold text-text">v{install.product_version}</p>
                  </div>
                  <div>
                    <p className="text-faint">Usado por</p>
                    <p className="font-semibold text-text">
                      {health.workflows ?? 0} workflows · {health.agents ?? 0} agentes
                    </p>
                  </div>
                  <div>
                    <p className="text-faint">Última llamada</p>
                    <p className="font-semibold text-text">{relativeTime(health.last_used_at) ?? "sin uso aún"}</p>
                  </div>
                  <div>
                    <p className="text-faint">Instalado</p>
                    <p className="font-semibold text-text">{relativeTime(install.created_at)}</p>
                  </div>
                </div>
                {children.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1.5 border-t border-border-soft pt-2.5">
                    {children.map((child) => (
                      <li key={child.install_id} className="flex items-center justify-between gap-2 text-xs">
                        <span className="truncate text-muted">{child.name ?? child.slug ?? child.alias}</span>
                        <span className="shrink-0 text-faint">
                          {child.connected ? "conectado" : child.needs_credentials ? "sin credenciales" : child.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {product.long_description && (
              <section>
                <h3 className="text-h3">Descripción</h3>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">{product.long_description}</p>
              </section>
            )}

            <section>
              <h3 className="text-h3">Dónde se usa</h3>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(product.applies_to || []).map((surface) => (
                  <span key={surface} className="chip">
                    {SURFACE_LABEL[surface] ?? surface}
                  </span>
                ))}
              </div>
            </section>

            {(product.capabilities || []).length > 0 && (
              <section>
                <h3 className="text-h3">Capacidades</h3>
                <ul className="mt-1.5 flex flex-col gap-1 font-mono text-xs text-muted">
                  {product.capabilities.map((cap) => (
                    <li key={cap}>{cap}</li>
                  ))}
                </ul>
              </section>
            )}

            {(product.dependencies || []).length > 0 && (
              <section>
                <h3 className="text-h3">Dependencias</h3>
                <ul className="mt-1.5 flex flex-col gap-1 text-xs text-muted">
                  {(product.dependencies || []).map((dep, idx) => (
                    <li key={`${dep.kind}-${dep.ref}-${idx}`}>
                      <span className="font-medium text-text">{dep.kind}</span>: {dep.ref}
                      {dep.requirement ? ` (${dep.requirement})` : ""}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {configKeys.length > 0 && (
              <section>
                <h3 className="text-h3">Configuración requerida</h3>
                <div className="mt-1.5">
                  <KeyValue
                    items={configKeys.map((key) => ({ key, value: "pendiente" }))}
                    columns={2}
                  />
                </div>
              </section>
            )}

            {(product.events || []).length > 0 && (
              <section>
                <h3 className="text-h3">Eventos que proporciona</h3>
                <ul className="mt-1.5 flex flex-col gap-1 font-mono text-xs text-muted">
                  {(product.events || []).map((event) => (
                    <li key={event}>{event}</li>
                  ))}
                </ul>
              </section>
            )}

            {permissions.length > 0 && (
              <section>
                <h3 className="text-h3">Seguridad</h3>
                <div className="mt-1.5">
                  <KeyValue
                    items={permissions.map(([key, value]) => ({ key, value: String(value) }))}
                    columns={2}
                  />
                </div>
              </section>
            )}

            {product.documentation && (
              <section>
                <h3 className="text-h3">Documentación y soporte</h3>
                <a
                  href={product.documentation}
                  className="text-sm text-accent hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  Ver documentación
                </a>
              </section>
            )}
          </div>
        ) : (
          <EmptyState
            icon={WarningCircle}
            title="Producto no disponible"
            body="El producto no existe o fue dado de baja del catálogo."
          />
        )}
      </Drawer>

      <Modal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Desinstalar producto"
        description="Esto libera la instalación. No borra workflows ni agentes: te mostramos qué queda en uso."
        role="alertdialog"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Cancelar
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void confirmUninstall()}>
              Desinstalar
            </Button>
          </>
        }
      >
        {impact && (
          <div className="flex flex-col gap-2 text-[13px] text-muted">
            <p>{impact.message}</p>
            {impact.assets.length > 0 && (
              <p>
                <span className="font-medium text-text">Integraciones:</span>{" "}
                {impact.assets.map((a) => a.alias).join(", ")}
              </p>
            )}
            {impact.workflows.length > 0 && (
              <p>
                <span className="font-medium text-text">Workflows que la usan:</span>{" "}
                {impact.workflows.map((w) => w.name).join(", ")}
              </p>
            )}
            {impact.agents.length > 0 && (
              <p>
                <span className="font-medium text-text">Agentes que la usan:</span>{" "}
                {impact.agents.map((a) => a.name).join(", ")}
              </p>
            )}
            {impact.products.length > 0 && (
              <p>
                <span className="font-medium text-text">Otros productos:</span>{" "}
                {impact.products.map((p) => p.name).join(", ")}
              </p>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
