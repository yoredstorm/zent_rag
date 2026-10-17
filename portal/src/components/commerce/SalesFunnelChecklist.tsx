/**
 * SalesFunnelChecklist — checklist de configuración del embudo de ventas.
 *
 * Consume `GET /api/v1/commerce/sales-funnel/readiness` y muestra pasos
 * numerados con marca ✓ / ! y un CTA por paso pendiente. Regla de oro: nunca
 * se exponen códigos técnicos ni stack traces; el `hint` del backend es el
 * texto humano que ve el usuario.
 */
import { ArrowClockwise, Storefront } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Button, ErrorInline, Skeleton } from "../ui";

export type FunnelReadinessAction = {
  kind: string;
  filter?: string | null;
  label: string;
};

export type FunnelReadinessItem = {
  key: string;
  label: string;
  status: "ok" | "attention";
  resolved: string[];
  missing: string[];
  hint?: string | null;
  action?: FunnelReadinessAction | null;
};

export type FunnelReadiness = {
  title: string;
  ready: boolean;
  items: FunnelReadinessItem[];
};

const LOAD_ERROR =
  "No pudimos cargar la configuración del embudo. Revisa tu conexión e inténtalo de nuevo.";

export function SalesFunnelChecklist({ className = "" }: { className?: string }) {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<FunnelReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session) {
      setLoading(false);
      setError("Inicia sesión para ver la configuración del embudo.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const readiness = await api<FunnelReadiness>("/api/v1/commerce/sales-funnel/readiness", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setData(readiness);
    } catch {
      // Sin detalles técnicos: el usuario solo necesita saber que puede reintentar.
      setError(LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const pending = data?.items.filter((item) => item.status !== "ok").length ?? 0;

  return (
    <div className={`panel ${className}`} data-testid="funnel-checklist">
      <div className="panel-header">
        <div className="min-w-0">
          <h2 className="text-h3">{data?.title ?? "Configura tu embudo"}</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Pasos para que el embudo cobre y cierre pedidos de punta a punta.
          </p>
        </div>
        {data &&
          (data.ready ? (
            <Badge tone="ok">Listo para vender</Badge>
          ) : (
            <Badge tone="warn">
              {pending === 1 ? "1 paso pendiente" : `${pending} pasos pendientes`}
            </Badge>
          ))}
      </div>

      {loading ? (
        <div className="flex flex-col gap-3 px-5 py-4" role="status" aria-label="Cargando configuración del embudo">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      ) : error ? (
        <div className="px-5 pb-5">
          <ErrorInline message={error} className="mb-0" />
          <Button size="sm" variant="secondary" leadingIcon={ArrowClockwise} className="mt-3" onClick={() => void load()}>
            Reintentar
          </Button>
        </div>
      ) : data && data.items.length > 0 ? (
        <ol className="px-2 pb-2">
          {data.items.map((item, index) => {
            const ok = item.status === "ok";
            const cta = !ok && item.action?.kind === "marketplace" ? item.action : null;
            return (
              <li
                key={item.key}
                data-testid={`funnel-step-${item.key}`}
                data-state={ok ? "ready" : "warning"}
                className="state-rail flex items-start gap-3 border-b border-border-soft py-3 pr-3 pl-4 last:border-b-0"
              >
                <span
                  className="mono mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-soft text-[11px] text-muted"
                  aria-hidden
                >
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-[13px] font-medium text-text">{item.label}</span>
                    <span
                      data-testid={`funnel-step-status-${item.key}`}
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${
                        ok ? "border-ok/30 bg-ok-soft text-ok" : "border-warn/30 bg-warn-soft text-warn"
                      }`}
                      title={ok ? "Listo" : "Requiere atención"}
                    >
                      {ok ? "✓" : "!"}
                    </span>
                  </div>
                  {item.hint && (
                    <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{item.hint}</p>
                  )}
                  {cta && (
                    <Button
                      size="sm"
                      variant="secondary"
                      leadingIcon={Storefront}
                      className="mt-2"
                      data-testid={`funnel-cta-${item.key}`}
                      onClick={() => navigate("/marketplace?applies_to=PAYMENTS&q=payment")}
                    >
                      {cta.label}
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="px-5 pb-5 text-[13px] text-muted">No hay pasos pendientes.</p>
      )}
    </div>
  );
}
