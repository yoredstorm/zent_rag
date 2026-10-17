/**
 * SalesFunnelKpis — panel de KPIs del embudo de ventas.
 *
 * Consume `GET /api/v1/commerce/kpis` (instancias del workflow + pedidos +
 * cobros reales). No es analytics completo: el texto al pie lo dice explícito.
 */
import {
  ArrowClockwise,
  CheckCircle,
  Clock,
  CreditCard,
  CurrencyCircleDollar,
  Hourglass,
  Lightning,
  Timer,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, Metric, MetricGrid, Skeleton } from "../ui";
import { LOCALE } from "../../lib/locale";

export type FunnelKpis = {
  instances: {
    active: number;
    waiting_customers: number;
    completed: number;
    failed: number;
    expired: number;
    cancelled: number;
    by_status?: Record<string, number>;
  };
  orders: {
    draft: number;
    awaiting_confirmation: number;
    awaiting_payment: number;
    paid: number;
    fulfilled: number;
    cancelled: number;
    expired: number;
    abandoned: number;
    by_status?: Record<string, number>;
  };
  sales: { revenue_paid: Record<string, number> };
  average_completion_seconds: number | null;
};

const LOAD_ERROR = "No pudimos cargar los KPIs del embudo. Reintenta en unos minutos.";

/** Segundos → texto legible: "42 s", "2 min 5 s", "1 h 2 min". */
function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const restSeconds = total % 60;
  if (minutes < 60) return restSeconds > 0 ? `${minutes} min ${restSeconds} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes > 0 ? `${hours} h ${restMinutes} min` : `${hours} h`;
}

/** Monto con la moneda real del cobro (nunca asume PEN/USD). */
function fmtMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export function SalesFunnelKpis({ className = "" }: { className?: string }) {
  const { session } = useAuth();
  const [kpis, setKpis] = useState<FunnelKpis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session) {
      setLoading(false);
      setError("Inicia sesión para ver los KPIs del embudo.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api<FunnelKpis>("/api/v1/commerce/kpis", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setKpis(data);
    } catch {
      setError(LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const revenue = Object.entries(kpis?.sales.revenue_paid ?? {}).sort(([a], [b]) =>
    a.localeCompare(b)
  );

  return (
    <div className={`panel ${className}`} data-testid="funnel-kpis">
      <div className="panel-header">
        <div className="min-w-0">
          <h2 className="text-h3">KPIs del embudo</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Actividad real del workflow de ventas: instancias, pedidos y cobros.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => void load()}
          disabled={loading}
          aria-busy={loading || undefined}
        >
          <ArrowClockwise size={14} weight="regular" aria-hidden />
          Actualizar
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-3 px-5 pb-5 sm:grid-cols-2 lg:grid-cols-4" role="status" aria-label="Cargando KPIs del embudo">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[86px] rounded-lg" />
          ))}
        </div>
      ) : error ? (
        <div className="px-5 pb-5">
          <ErrorInline message={error} className="mb-0" />
          <button type="button" className="btn btn-secondary btn-sm mt-3" onClick={() => void load()}>
            <ArrowClockwise size={14} weight="regular" aria-hidden />
            Reintentar
          </button>
        </div>
      ) : kpis ? (
        <div className="px-5 pb-1">
          <MetricGrid cols={4}>
            <div data-testid="funnel-kpi-instances-active">
              <Metric
                label="Instancias activas"
                value={kpis.instances.active}
                hint="Conversaciones en curso en el embudo."
                icon={Lightning}
              />
            </div>
            <div data-testid="funnel-kpi-waiting-customers">
              <Metric
                label="Clientes esperando"
                value={kpis.instances.waiting_customers}
                hint="El embudo espera una respuesta del cliente."
                icon={Clock}
              />
            </div>
            <div data-testid="funnel-kpi-awaiting-payment">
              <Metric
                label="Esperando pago"
                value={kpis.orders.awaiting_payment}
                hint="Pedidos confirmados sin cobro."
                icon={CreditCard}
              />
            </div>
            <div data-testid="funnel-kpi-completed-sales">
              <Metric
                label="Ventas completadas"
                value={kpis.orders.fulfilled}
                hint="Pedidos pagados y entregados."
                icon={CheckCircle}
                tone="ok"
              />
            </div>
            <div data-testid="funnel-kpi-abandoned">
              <Metric
                label="Abandonadas"
                value={kpis.orders.abandoned}
                hint="Pedidos sin pago: espera vencida o sin confirmar."
                icon={Hourglass}
              />
            </div>
            <div data-testid="funnel-kpi-failed">
              <Metric
                label="Fallidas"
                value={kpis.instances.failed}
                hint="Instancias que terminaron con error."
                icon={WarningCircle}
                tone={kpis.instances.failed > 0 ? "danger" : "default"}
              />
            </div>
            <div data-testid="funnel-kpi-avg-completion">
              <Metric
                label="Tiempo medio de cierre"
                value={fmtDuration(kpis.average_completion_seconds)}
                hint="Desde que inicia hasta que se completa."
                icon={Timer}
              />
            </div>
            <div data-testid="funnel-kpi-revenue-paid">
              <Metric
                label="Ventas cobradas"
                value={
                  revenue.length > 0 ? (
                    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      {revenue.map(([currency, amount]) => (
                        <span key={currency} className="tabular-nums">
                          {fmtMoney(amount, currency)}
                        </span>
                      ))}
                    </span>
                  ) : (
                    "—"
                  )
                }
                hint="Solo pedidos pagados y entregados, por moneda."
                icon={CurrencyCircleDollar}
              />
            </div>
          </MetricGrid>
        </div>
      ) : null}

      <p className="px-5 pt-2 pb-4 text-[11px] leading-relaxed text-faint">
        Son KPIs del workflow de ventas (instancias y pedidos del embudo), no analytics completos
        del negocio.
      </p>
    </div>
  );
}
