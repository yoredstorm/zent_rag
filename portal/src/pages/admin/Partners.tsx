import { Handshake, Plus, Pulse, PuzzlePiece } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  Skeleton,
  SuccessInline,
  type Column,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";
import { fmtCurrency, fmtDateTime } from "../../lib/format";

type Partner = {
  id: string;
  organization_id: string;
  name: string;
  contact_email: string | null;
  rev_share_pct: number;
  status: string;
  white_label_enabled: boolean;
  branding: Record<string, unknown>;
  created_at: string;
};

type PartnerUsage = { total_requests: number; total_cost: number; by_day: { date: string; requests: number; cost: number }[] };
type Commission = { period: string; revenue: number; commission: number; status: string };
type Integration = { key: string; name: string; category: string; description: string | null; oauth_url_template: string | null; is_active: boolean };

export default function AdminPartnersPage() {
  const { session } = usePlatformAuth();
  const [partners, setPartners] = useState<Partner[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [form, setForm] = useState({ organization_id: "", name: "", contact_email: "", rev_share_pct: 10 });
  const [usage, setUsage] = useState<Record<string, PartnerUsage>>({});
  const [commissions, setCommissions] = useState<Record<string, Commission[]>>({});
  const [subtenants, setSubtenants] = useState<Record<string, { organization_id: string; commission_share_pct: number }[]>>({});
  const [detail, setDetail] = useState<Partner | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, i, o] = await Promise.all([
        platformApi<{ partners: Partner[] }>("/api/v1/platform/partners", { token: session.token }),
        platformApi<{ integrations: Integration[] }>("/api/v1/platform/partners/integrations", { token: session.token }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token }),
      ]);
      setPartners(p.partners || []);
      setIntegrations(i.integrations || []);
      setOrgs(o.organizations || []);
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

  async function create() {
    if (!session) return;
    setBusy("create");
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ api_token: string }>("/api/v1/platform/partners", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(form),
      });
      setNotice(`Partner creado. TOKEN (una vez): ${out.api_token}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function loadUsage(partnerId: string) {
    if (!session) return;
    setBusy(partnerId);
    setError("");
    try {
      const [u, c, s] = await Promise.all([
        platformApi<PartnerUsage>(`/api/v1/platform/partners/${partnerId}/usage`, { token: session.token }),
        platformApi<{ commissions: Commission[] }>(`/api/v1/platform/partners/${partnerId}/commissions`, { token: session.token }),
        platformApi<{ subtenants: { organization_id: string; commission_share_pct: number }[] }>(
          `/api/v1/platform/partners/${partnerId}/subtenants`,
          { token: session.token }
        ),
      ]);
      setUsage((prev) => ({ ...prev, [partnerId]: u }));
      setCommissions((prev) => ({ ...prev, [partnerId]: c.commissions || [] }));
      setSubtenants((prev) => ({ ...prev, [partnerId]: s.subtenants || [] }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function calcCommission(partnerId: string) {
    if (!session) return;
    setBusy(partnerId);
    setError("");
    setNotice("");
    const period = new Date().toISOString().slice(0, 7);
    try {
      const out = await platformApi<{ commission: number; revenue: number }>(
        `/api/v1/platform/partners/${partnerId}/commission/calculate`,
        { method: "POST", token: session.token, body: JSON.stringify({ period }) }
      );
      setNotice(`${period}: revenue $${out.revenue} → comisión $${out.commission}`);
      await loadUsage(partnerId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  function openDetail(partner: Partner) {
    setDetail(partner);
    void loadUsage(partner.id);
  }

  const partnerColumns: Column<Partner>[] = [
    {
      key: "name",
      header: "Partner",
      render: (p) => (
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium text-text">{p.name}</span>
          {p.contact_email && <span className="truncate text-xs text-faint">{p.contact_email}</span>}
        </span>
      ),
    },
    {
      key: "org",
      header: "Org",
      hideBelow: "lg",
      render: (p) => <span className="mono text-xs text-muted">{p.organization_id.slice(0, 8)}…</span>,
    },
    {
      key: "rev_share",
      header: "Rev-share",
      align: "right",
      render: (p) => <span className="mono">{p.rev_share_pct}%</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (p) => <Badge tone={p.status === "active" ? "ok" : "danger"}>{p.status}</Badge>,
    },
    {
      key: "white_label",
      header: "White-label",
      hideBelow: "md",
      render: (p) =>
        p.white_label_enabled ? <Badge tone="warn">activo</Badge> : <span className="text-faint">—</span>,
    },
    {
      key: "created",
      header: "Creado",
      hideBelow: "xl",
      render: (p) => <span className="text-muted">{fmtDateTime(p.created_at)}</span>,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Partner Ecosystem"
        subtitle="Partners con rev-share, subtenants white-label y catálogo de integraciones."
      />
      {error && <ErrorInline message={error} />}
      {notice && <SuccessInline>{notice}</SuccessInline>}
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[112px] rounded-lg" />
          <Skeleton className="h-[220px] rounded-lg" />
        </div>
      ) : (
        <>
          <Panel>
            <PanelHeader
              title="Nuevo partner"
              description="Genera un token dedicado; se muestra una sola vez."
            />
            <form
              className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-5 lg:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <Field label="Organización">
                <Select
                  value={form.organization_id}
                  placeholder="Elegir org…"
                  onChange={(e) => setForm((f) => ({ ...f, organization_id: e.target.value }))}
                >
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.id.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Nombre">
                <Input
                  placeholder="Nombre del partner"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </Field>
              <Field label="Email de contacto">
                <Input
                  type="email"
                  placeholder="partner@empresa.com"
                  value={form.contact_email}
                  onChange={(e) => setForm((f) => ({ ...f, contact_email: e.target.value }))}
                />
              </Field>
              <Field label="Rev-share %">
                <Input
                  type="number"
                  min={0}
                  value={form.rev_share_pct}
                  onChange={(e) => setForm((f) => ({ ...f, rev_share_pct: Number(e.target.value) }))}
                />
              </Field>
              <Button type="submit" variant="primary" leadingIcon={Plus} loading={busy === "create"}>
                Crear (token)
              </Button>
            </form>
          </Panel>

          <section>
            <SectionHeader
              title="Partners"
              description="Abrí el detalle para ver uso, comisiones y subtenants reales."
              className="mb-3"
            />
            <DataTable
              columns={partnerColumns}
              rows={partners}
              rowKey={(p) => p.id}
              caption="Partners de la plataforma"
              stickyHeader
              onRowClick={(p) => openDetail(p)}
              rowActions={(p) => (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy !== ""}
                    onClick={() => openDetail(p)}
                  >
                    Uso
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy !== ""}
                    onClick={() => {
                      setDetail(p);
                      void calcCommission(p.id);
                    }}
                  >
                    Comisión
                  </Button>
                </>
              )}
              empty={
                <EmptyState
                  icon={Handshake}
                  title="Sin partners"
                  body="Creá un partner para emitir su token dedicado."
                />
              }
            />
          </section>

          <section>
            <SectionHeader
              title="Catálogo de integraciones"
              description="Integraciones soportadas por el ecosistema."
              className="mb-3"
            />
            {integrations.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={PuzzlePiece}
                  title="Sin integraciones"
                  body="El catálogo no devolvió integraciones."
                />
              </Panel>
            ) : (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
                {integrations.map((i) => (
                  <Panel key={i.key} className="flex flex-col gap-1 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[13px] font-medium text-text">{i.name}</p>
                      <Badge tone={i.is_active ? "ok" : "neutral"}>
                        {i.is_active ? "activa" : "inactiva"}
                      </Badge>
                    </div>
                    <p className="text-xs text-faint">
                      {i.category} · {i.key}
                    </p>
                    {i.description && <p className="text-xs leading-relaxed text-muted">{i.description}</p>}
                  </Panel>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <Drawer
        open={!!detail}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.name || "Partner"}
        description={
          detail
            ? `org ${detail.organization_id.slice(0, 8)}… · rev-share ${detail.rev_share_pct}%`
            : undefined
        }
        width={480}
      >
        {detail && (
          <div className="flex flex-col gap-4">
            {!usage[detail.id] ? (
              <Skeleton className="h-[104px] rounded-lg" />
            ) : (
              <MetricGrid cols={3}>
                <Metric
                  size="md"
                  label="Requests 30d"
                  value={usage[detail.id].total_requests}
                  icon={Pulse}
                />
                <Metric
                  size="md"
                  label="Costo 30d"
                  value={fmtCurrency(usage[detail.id].total_cost)}
                />
                <Metric size="md" label="Subtenants" value={subtenants[detail.id]?.length ?? 0} />
              </MetricGrid>
            )}

            <Panel>
              <PanelHeader title="Comisiones" description="Comisiones calculadas por período." />
              {(commissions[detail.id] ?? []).length === 0 ? (
                <EmptyState
                  compact
                  title="Sin comisiones"
                  body="Calculá una comisión para ver el período acá."
                />
              ) : (
                <ul className="divide-y divide-border-soft px-4">
                  {(commissions[detail.id] ?? []).map((c) => (
                    <li key={c.period} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-xs">
                      <span className="mono text-text">{c.period}</span>
                      <span className="text-muted">
                        revenue ${c.revenue} · <b className="text-text">comisión ${c.commission}</b> · {c.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader title="Subtenants" description="Organizaciones bajo este partner." />
              {(subtenants[detail.id] ?? []).length === 0 ? (
                <EmptyState
                  compact
                  title="Sin subtenants"
                  body="Este partner todavía no tiene organizaciones asociadas."
                />
              ) : (
                <ul className="divide-y divide-border-soft px-4">
                  {(subtenants[detail.id] ?? []).map((s) => (
                    <li key={s.organization_id} className="flex items-center justify-between gap-2 py-2.5 text-xs">
                      <span className="mono text-muted">{s.organization_id.slice(0, 8)}…</span>
                      <span className="mono text-text">{s.commission_share_pct}%</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        )}
      </Drawer>
    </div>
  );
}
