import {
  ArrowClockwise,
  Broadcast,
  CheckCircle,
  Clock,
  Plus,
  Question,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  ErrorInline,
  Field,
  Input,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  SuccessInline,
  type Column,
  type Tone,
} from "../../components/ui";
import { fmtDateTime, fmtLatency } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Delivery = { id: string; subscription_id: string; organization_id: string; event_type: string; status: string; attempts: number; last_status_code: number | null; latency_ms: number | null; error: string | null; delivered_at: string | null; created_at: string };
type SubStatus = { subscription_id: string; url: string; total: number; delivered: number; failed: number; retrying: number; success_rate: number; avg_latency_ms: number | null; last_status_code: number | null };

/** Estados reales de una entrega de webhook. */
const DELIVERY_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  delivered: { label: "Entregado", tone: "ok", icon: CheckCircle },
  failed: { label: "Falló", tone: "danger", icon: XCircle },
  retrying: { label: "Reintentando", tone: "warn", icon: ArrowClockwise },
  pending: { label: "Pendiente", tone: "neutral", icon: Clock },
};

function DeliveryStatusBadge({ status }: { status: string }) {
  const meta = DELIVERY_STATUS_META[status] ?? {
    label: status || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

const EVENT_TYPES = ["invoice.paid", "quota.exceeded", "agent.deployed", "usage.alert", "test.ping"];

export default function AdminNotificationsPage() {
  const { session } = usePlatformAuth();
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [status, setStatus] = useState<SubStatus[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [trigger, setTrigger] = useState({ organization_id: "", event_type: "invoice.paid", title: "Evento de prueba" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Delivery | null>(null);

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [d, s] = await Promise.all([
        platformApi<{ deliveries: Delivery[] }>(`/api/v1/platform/notifications/deliveries${q}`, { token: session.token }),
        platformApi<{ subscriptions: SubStatus[] }>("/api/v1/platform/notifications/deliveries/status?hours=24", { token: session.token }),
      ]);
      setDeliveries(d.deliveries || []);
      setStatus(s.subscriptions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function triggerEvent() {
    if (!session) return;
    setBusy("trigger");
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ in_app: boolean; email: boolean; webhook_deliveries: number }>("/api/v1/platform/notifications/trigger", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(trigger),
      });
      setNotice(`Evento enviado: in_app=${out.in_app} · email=${out.email} · webhook_deliveries=${out.webhook_deliveries}`);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const filtered = statusFilter ? deliveries.filter((d) => d.status === statusFilter) : deliveries;
  const retrying = deliveries.filter((d) => d.status === "retrying");
  const totals = deliveries.reduce(
    (acc, d) => {
      acc[d.status] = (acc[d.status] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const columns: Column<Delivery>[] = [
    {
      key: "created_at",
      header: "Hora",
      width: "120px",
      render: (d) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(d.created_at)}</span>,
    },
    {
      key: "event_type",
      header: "Evento",
      render: (d) => (
        <span className="text-[13px] text-text">
          <span className="mono text-xs">{d.event_type}</span>
          <span className="mt-0.5 block text-[11px] text-faint" title={d.organization_id}>
            {d.organization_id.slice(0, 8)} · sub {d.subscription_id.slice(0, 8)}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (d) => <DeliveryStatusBadge status={d.status} />,
    },
    {
      key: "attempts",
      header: "Intentos",
      align: "right",
      hideBelow: "md",
      render: (d) => <span className="mono text-xs text-muted tabular-nums">{d.attempts}</span>,
    },
    {
      key: "last_status_code",
      header: "HTTP",
      align: "right",
      hideBelow: "md",
      render: (d) => <span className="mono text-xs text-muted tabular-nums">{d.last_status_code ?? "—"}</span>,
    },
    {
      key: "latency_ms",
      header: "Latencia",
      align: "right",
      hideBelow: "lg",
      render: (d) => <span className="mono text-xs text-muted tabular-nums">{fmtLatency(d.latency_ms)}</span>,
    },
    {
      key: "error",
      header: "Error",
      hideBelow: "xl",
      render: (d) =>
        d.error ? (
          <span className="block max-w-56 truncate text-xs text-danger" title={d.error}>
            {d.error}
          </span>
        ) : (
          <span className="text-xs text-ghost">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Webhooks & Notifications"
        subtitle="Entregas con firma HMAC, reintentos con backoff y preferencias multicanal."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {status.map((s) => (
              <Panel key={s.subscription_id}>
                <PanelHeader
                  title={<span className="mono block truncate text-xs text-text" title={s.url}>{s.url}</span>}
                  actions={<Badge tone={s.failed > 0 ? "warn" : "ok"}>{s.success_rate >= 1 ? "Sin fallos" : "Con fallos"}</Badge>}
                  description={`${s.total} entregas · ${s.delivered} ok · ${s.failed} fail · ${s.retrying} retry`}
                />
                <div className="panel-body flex flex-wrap items-baseline gap-x-6 gap-y-2">
                  <span className="stat-value">{(s.success_rate * 100).toFixed(0)}%</span>
                  <span className="text-xs text-muted">
                    latencia avg {fmtLatency(s.avg_latency_ms)} · último HTTP {s.last_status_code ?? "—"}
                  </span>
                </div>
              </Panel>
            ))}
            {status.length === 0 && (
              <Panel className="sm:col-span-2 xl:col-span-3">
                <p className="px-4 py-3 text-[13px] text-muted">Sin entregas en 24h.</p>
              </Panel>
            )}
          </div>

          <Panel>
            <PanelHeader
              title={
                <span className="flex items-center gap-2">
                  <Broadcast size={15} className="text-faint" aria-hidden />
                  Enviar evento de prueba
                </span>
              }
              description="Dispara el pipeline completo: in-app, email y webhooks suscritos."
            />
            <div className="panel-body grid grid-cols-1 items-end gap-3 md:grid-cols-4">
              <Field label="Organización">
                <Select
                  placeholder="org…"
                  value={trigger.organization_id}
                  onChange={(e) => setTrigger((t) => ({ ...t, organization_id: e.target.value }))}
                >
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.id.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Tipo de evento">
                <Select
                  value={trigger.event_type}
                  onChange={(e) => setTrigger((t) => ({ ...t, event_type: e.target.value }))}
                >
                  {EVENT_TYPES.map((ev) => (
                    <option key={ev} value={ev}>
                      {ev}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Título">
                <Input
                  value={trigger.title}
                  onChange={(e) => setTrigger((t) => ({ ...t, title: e.target.value }))}
                />
              </Field>
              <Button
                variant="primary"
                leadingIcon={Plus}
                loading={busy === "trigger"}
                disabled={!!busy || !trigger.organization_id}
                onClick={() => void triggerEvent()}
              >
                Enviar
              </Button>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric label="Entregas" value={deliveries.length} hint="Ventana cargada" />
            <Metric label="Entregadas" value={totals.delivered ?? 0} size="md" tone="ok" icon={CheckCircle} />
            <Metric label="Fallidas" value={totals.failed ?? 0} size="md" tone={(totals.failed ?? 0) > 0 ? "danger" : "default"} icon={XCircle} />
            <Metric label="En reintento" value={retrying.length} size="md" tone={retrying.length > 0 ? "warn" : "default"} icon={ArrowClockwise} />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <section className="lg:col-span-2">
              <DataTable
                columns={columns}
                rows={filtered}
                rowKey={(d) => d.id}
                caption="Entregas recientes"
                stickyHeader
                onRowClick={(d) => setSelected(d)}
                toolbar={
                  <>
                    <Select
                      className="w-full sm:w-48"
                      aria-label="Filtrar por organización"
                      value={orgId}
                      onChange={(e) => setOrgId(e.target.value)}
                    >
                      <option value="">todas las organizaciones</option>
                      {orgs.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.id.slice(0, 8)}
                        </option>
                      ))}
                    </Select>
                    <Select
                      className="w-full sm:w-44"
                      aria-label="Filtrar por estado"
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                    >
                      <option value="">todos los estados</option>
                      {Object.entries(DELIVERY_STATUS_META).map(([value, meta]) => (
                        <option key={value} value={value}>
                          {meta.label}
                        </option>
                      ))}
                    </Select>
                    <ResultCount shown={filtered.length} total={deliveries.length} noun="entregas" />
                  </>
                }
                empty={
                  <p className="px-4 py-6 text-center text-[13px] text-muted">
                    {statusFilter ? "Ninguna entrega coincide con el estado seleccionado." : "Sin entregas registradas."}
                  </p>
                }
              />
            </section>

            <Panel>
              <PanelHeader
                title="Cola de reintentos"
                description="Backoff exponencial: 1m → 5m → 30m → 2h → 6h (máx 5 intentos)."
              />
              <ul className="divide-y divide-border-soft">
                {retrying.slice(0, 8).map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="mono min-w-0 truncate text-xs text-text" title={d.event_type}>
                      {d.event_type}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">intento {d.attempts}/5</span>
                  </li>
                ))}
                {retrying.length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin reintentos pendientes.</li>
                )}
              </ul>
              {retrying.length > 0 && (
                <div className="panel-footer">
                  <span className="flex items-center gap-1.5 text-xs text-warn">
                    <WarningCircle size={13} aria-hidden />
                    {retrying.length} entregas en reintento
                  </span>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Detalle de la entrega"
        description={selected?.event_type}
        width={480}
      >
        {selected && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <DeliveryStatusBadge status={selected.status} />
              <Badge tone={selected.last_status_code && selected.last_status_code < 400 ? "ok" : "neutral"}>
                HTTP {selected.last_status_code ?? "—"}
              </Badge>
              <Badge tone="neutral">{selected.attempts} intentos</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Organización", value: selected.organization_id, mono: true },
                { key: "Suscripción", value: selected.subscription_id, mono: true },
                { key: "Latencia", value: fmtLatency(selected.latency_ms) },
                { key: "Entregado", value: fmtDateTime(selected.delivered_at) },
                { key: "Creado", value: fmtDateTime(selected.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Error reportado</p>
              {selected.error ? (
                <p className="rounded-sm border border-danger/25 bg-danger-soft px-3 py-2 text-[13px] leading-relaxed break-words text-danger">
                  {selected.error}
                </p>
              ) : (
                <p className="text-[13px] text-muted">La entrega no reportó error.</p>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
