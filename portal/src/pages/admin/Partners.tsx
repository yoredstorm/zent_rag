import { Handshake, Plus, PuzzlePiece } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

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
    try {
      const out = await platformApi<{ api_token: string }>("/api/v1/platform/partners", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(form),
      });
      setError(`Partner creado. TOKEN (una vez): ${out.api_token}`);
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
    const period = new Date().toISOString().slice(0, 7);
    try {
      const out = await platformApi<{ commission: number; revenue: number }>(
        `/api/v1/platform/partners/${partnerId}/commission/calculate`,
        { method: "POST", token: session.token, body: JSON.stringify({ period }) }
      );
      setError(`${period}: revenue $${out.revenue} → comisión $${out.commission}`);
      await loadUsage(partnerId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Partner Ecosystem"
        subtitle="Partners con rev-share, subtenants white-label y catálogo de integraciones."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Handshake size={15} aria-hidden /> Partners
            </h3>
            <div className="panel grid grid-cols-1 gap-3 p-4 lg:grid-cols-5">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={form.organization_id} onChange={(e) => setForm((f) => ({ ...f, organization_id: e.target.value }))}>
                <option value="">Org del partner…</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                ))}
              </select>
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Nombre" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Email" value={form.contact_email} onChange={(e) => setForm((f) => ({ ...f, contact_email: e.target.value }))} />
              <input type="number" className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Rev-share %" value={form.rev_share_pct} onChange={(e) => setForm((f) => ({ ...f, rev_share_pct: Number(e.target.value) }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void create()}>
                <Plus size={13} aria-hidden /> Crear (token)
              </button>
            </div>

            {partners.length === 0 ? (
              <div className="panel mt-2">
                <EmptyState icon={Handshake} title="Sin partners" body="Crea un partner para emitir su token dedicado." />
              </div>
            ) : (
              <div className="mt-2 space-y-3">
                {partners.map((p) => (
                  <div key={p.id} className="panel p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-text">{p.name}</p>
                        <p className="text-xs text-faint">
                          org {p.organization_id.slice(0, 8)} · rev-share {p.rev_share_pct}% ·{" "}
                          <span className={`badge ${p.status === "active" ? "badge-ok" : "badge-danger"}`}>{p.status}</span>{" "}
                          {p.white_label_enabled && <span className="badge badge-pending">white-label</span>}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={!!busy} onClick={() => void loadUsage(p.id)}>
                          Uso
                        </button>
                        <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={!!busy} onClick={() => void calcCommission(p.id)}>
                          Comisión
                        </button>
                      </div>
                    </div>
                    {usage[p.id] && (
                      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                        <span className="text-muted">Requests 30d: <b className="text-text">{usage[p.id].total_requests}</b></span>
                        <span className="text-muted">Costo: <b className="text-text">${usage[p.id].total_cost.toFixed(2)}</b></span>
                        <span className="text-muted">Subtenants: <b className="text-text">{subtenants[p.id]?.length ?? 0}</b></span>
                      </div>
                    )}
                    {(commissions[p.id] ?? []).length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {commissions[p.id]?.map((c) => (
                          <li key={c.period} className="flex items-center justify-between text-xs">
                            <span className="mono text-text">{c.period}</span>
                            <span className="text-faint">revenue ${c.revenue} · <b>comisión ${c.commission}</b> · {c.status}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <PuzzlePiece size={15} aria-hidden /> Catálogo de integraciones
            </h3>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {integrations.map((i) => (
                <div key={i.key} className="panel flex flex-col gap-1 p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold text-text">{i.name}</p>
                    <span className={`badge ${i.is_active ? "badge-ok" : "badge-muted"}`}>{i.is_active ? "activa" : "inactiva"}</span>
                  </div>
                  <p className="text-xs text-faint">{i.category} · {i.key}</p>
                  <p className="text-xs text-muted">{i.description}</p>
                  {i.oauth_url_template && (
                    <p className="truncate text-[10px] text-faint">{i.oauth_url_template}</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}