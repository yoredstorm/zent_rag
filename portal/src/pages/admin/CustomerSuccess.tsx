import { ChartBar, Envelope, Rocket } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  SectionHeader,
  Skeleton,
  StatusBadge,
  SuccessInline,
  type Column,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";
import { fmtDateTime } from "../../lib/format";

type Conversion = {
  total_subscriptions: number;
  trials: number;
  paid_active: number;
  conversion_rate_pct: number | null;
  by_plan: { plan: string; total: number; active: number }[];
};

type Onboarding = {
  organization_id: string;
  step: number;
  completed: boolean;
  completed_at: string | null;
  items: { key: string; label: string; done: boolean }[];
};

type ReportSub = {
  id: string;
  organization_id: string;
  email: string;
  frequency: string;
  next_send_at: string;
  last_sent_at: string | null;
};

function CustomerSuccessSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-hidden>
      <Skeleton className="h-[112px] rounded-lg" />
      <Skeleton className="h-[240px] rounded-lg" />
      <Skeleton className="h-[240px] rounded-lg" />
    </div>
  );
}

export default function AdminCustomerSuccessPage() {
  const { session } = usePlatformAuth();
  const [conversion, setConversion] = useState<Conversion | null>(null);
  const [onboarding, setOnboarding] = useState<Onboarding[]>([]);
  const [subs, setSubs] = useState<ReportSub[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState<ReportSub | null>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [c, o, s] = await Promise.all([
        platformApi<Conversion>("/api/v1/platform/customer-success/conversion", {
          token: session.token,
        }),
        platformApi<{ organizations: Onboarding[] }>(
          "/api/v1/platform/customer-success/onboarding",
          { token: session.token }
        ),
        platformApi<{ subscriptions: ReportSub[] }>(
          "/api/v1/platform/customer-success/reports",
          { token: session.token }
        ),
      ]);
      setConversion(c);
      setOnboarding(o.organizations || []);
      setSubs(s.subscriptions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function sendNow(subId: string) {
    if (!session) return;
    setBusy(subId);
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/customer-success/reports/${subId}/send-now`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setNotice(`Reporte enviado: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function removeSub(subId: string) {
    if (!session) return;
    setBusy(subId);
    setError("");
    try {
      await platformApi(`/api/v1/platform/customer-success/reports/${subId}`, {
        method: "DELETE",
        token: session.token,
      });
      setRemoving(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const planColumns: Column<Conversion["by_plan"][number]>[] = [
    { key: "plan", header: "Plan", render: (p) => <span className="font-medium text-text">{p.plan}</span> },
    { key: "total", header: "Totales", align: "right", render: (p) => <span className="mono">{p.total}</span> },
    { key: "active", header: "Activas", align: "right", render: (p) => <span className="mono">{p.active}</span> },
  ];

  const onboardingColumns: Column<Onboarding>[] = [
    {
      key: "org",
      header: "Tenant",
      render: (o) => <span className="mono text-xs text-muted">{o.organization_id.slice(0, 13)}…</span>,
    },
    {
      key: "steps",
      header: "Pasos",
      render: (o) => (
        <span className="flex flex-wrap gap-1">
          {(o.items ?? []).map((item) => (
            <Badge key={item.key} tone={item.done ? "ok" : "neutral"} title={item.label}>
              {item.label}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (o) =>
        o.completed ? (
          <StatusBadge status="completed" />
        ) : (
          <Badge tone="warn">paso {o.step}/6</Badge>
        ),
    },
    {
      key: "completed",
      header: "Completado",
      hideBelow: "lg",
      render: (o) => (
        <span className="text-muted">{o.completed_at ? fmtDateTime(o.completed_at) : "—"}</span>
      ),
    },
  ];

  const reportColumns: Column<ReportSub>[] = [
    {
      key: "org",
      header: "Tenant",
      render: (s) => <span className="mono text-xs text-muted">{s.organization_id.slice(0, 8)}…</span>,
    },
    { key: "email", header: "Email", render: (s) => s.email },
    {
      key: "frequency",
      header: "Frecuencia",
      hideBelow: "md",
      render: (s) => <span className="text-muted">{s.frequency}</span>,
    },
    {
      key: "next",
      header: "Próximo envío",
      hideBelow: "lg",
      render: (s) => <span className="text-muted">{fmtDateTime(s.next_send_at)}</span>,
    },
    {
      key: "last",
      header: "Último envío",
      hideBelow: "xl",
      render: (s) => <span className="text-muted">{s.last_sent_at ? fmtDateTime(s.last_sent_at) : "—"}</span>,
    },
  ];

  const rate = conversion?.conversion_rate_pct;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Customer Success"
        subtitle="Conversión trial→paid, onboarding por tenant y reportes de uso por email."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      <SuccessInline>{notice}</SuccessInline>
      {loading ? (
        <CustomerSuccessSkeleton />
      ) : (
        <>
          <section className="flex flex-col gap-3">
            {/* Foco: la conversión trial→paid; el volumen queda demotado */}
            <Panel className="p-4">
              <p className="eyebrow">Conversión trial → paid</p>
              <p className="mt-1.5 text-display tabular-nums">
                {rate != null ? `${rate}%` : "—"}
              </p>
              <p className="mt-2 text-[13px] text-muted">
                {conversion?.trials ?? 0} trials
                <span className="mx-1.5 text-ghost">·</span>
                {conversion?.paid_active ?? 0} paid activos
                <span className="mx-1.5 text-ghost">·</span>
                {conversion?.total_subscriptions ?? 0} suscripciones totales
              </p>
            </Panel>

            <MetricGrid cols={3}>
              <Metric size="md" label="Trials" value={conversion?.trials ?? 0} icon={Rocket} />
              <Metric size="md" label="Paid activos" value={conversion?.paid_active ?? 0} />
              <Metric size="md" label="Subs totales" value={conversion?.total_subscriptions ?? 0} />
            </MetricGrid>
          </section>

          <section>
            <SectionHeader title="Por plan" description="Suscripciones totales y activas por plan." className="mb-3" />
            <DataTable
              columns={planColumns}
              rows={conversion?.by_plan ?? []}
              rowKey={(p) => p.plan}
              caption="Suscripciones por plan"
              empty={
                <EmptyState
                  icon={ChartBar}
                  title="Sin datos por plan"
                  body="Todavía no hay suscripciones agrupadas por plan."
                />
              }
            />
          </section>

          <section>
            <SectionHeader
              title="Onboarding por tenant"
              description="Pasos completados del flujo de activación."
              className="mb-3"
            />
            <DataTable
              columns={onboardingColumns}
              rows={onboarding}
              rowKey={(o) => o.organization_id}
              caption="Onboarding por organización"
              stickyHeader
              empty={
                <EmptyState
                  icon={Rocket}
                  title="Sin organizaciones en onboarding"
                  body="Todavía ninguna organización inició el flujo de activación."
                />
              }
            />
          </section>

          <section>
            <SectionHeader
              title="Reportes de uso por email"
              description="Suscripciones al resumen periódico de uso."
              className="mb-3"
            />
            <DataTable
              columns={reportColumns}
              rows={subs}
              rowKey={(s) => s.id}
              caption="Suscripciones a reportes de uso"
              stickyHeader
              rowActions={(s) => (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={busy === s.id}
                    disabled={busy !== ""}
                    onClick={() => void sendNow(s.id)}
                  >
                    Enviar ahora
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-danger"
                    disabled={busy !== ""}
                    onClick={() => setRemoving(s)}
                  >
                    Quitar
                  </Button>
                </>
              )}
              empty={
                <EmptyState
                  icon={Envelope}
                  title="Sin suscripciones"
                  body="Nadie se ha suscrito a reportes de uso."
                />
              }
            />
          </section>
        </>
      )}

      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title="Quitar reporte de uso"
        body={
          removing
            ? `Vas a quitar el reporte de ${removing.email}. Dejará de enviarse.`
            : undefined
        }
        confirmLabel="Quitar"
        tone="danger"
        loading={!!removing && busy === removing.id}
        onConfirm={() => {
          if (removing) void removeSub(removing.id);
        }}
      />
    </div>
  );
}
