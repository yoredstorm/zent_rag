import { Plus, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  SkeletonTable,
  SuccessInline,
  Textarea,
  Toolbar,
  ToolbarSpacer,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Incident = {
  id: string;
  organization_id: string;
  source: string;
  severity: string;
  status: string;
  title: string;
  description: string | null;
  occurred_at: string;
  detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  mttd_seconds: number | null;
  mttr_seconds: number | null;
};

type IncidentEvent = { id: string; type: string; detail: string; created_at: string };
type IncidentDetail = Incident & { timeline?: IncidentEvent[] };

type Runbook = { id: string; trigger_type: string; trigger_match: string; title: string; description: string | null; steps: unknown[]; enabled: boolean };
type SeverityMetric = { severity: string; total: number; resolved: number; avg_mttr_seconds: number | null; avg_mttd_seconds: number | null };

const SEVERITY_META: Record<string, { tone: Tone; label: string }> = {
  severe: { tone: "danger", label: "Crítico" },
  major: { tone: "warn", label: "Mayor" },
  minor: { tone: "neutral", label: "Menor" },
};

const STATUS_META: Record<string, { tone: Tone; label: string }> = {
  open: { tone: "danger", label: "Abierto" },
  acknowledged: { tone: "warn", label: "Reconocido" },
  resolved: { tone: "ok", label: "Resuelto" },
};

const EVENT_META: Record<string, { tone: Tone; label: string }> = {
  created: { tone: "info", label: "Creado" },
  acknowledged: { tone: "warn", label: "Reconocido" },
  escalation: { tone: "warn", label: "Escalado" },
  escalated: { tone: "warn", label: "Escalado" },
  resolved: { tone: "ok", label: "Resuelto" },
  note: { tone: "neutral", label: "Nota" },
};

function minutes(seconds: number | null, digits = 0) {
  return seconds != null ? `${(seconds / 60).toFixed(digits)}m` : "—";
}

const RAIL_STATE: Record<string, "ready" | "warning" | "failed"> = {
  resolved: "ready",
  acknowledged: "warning",
  open: "failed",
};

export default function AdminOpsCenterPage() {
  const { session } = usePlatformAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [metrics, setMetrics] = useState<SeverityMetric[]>([]);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [confirmResolve, setConfirmResolve] = useState<Incident | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [form, setForm] = useState({ title: "", description: "", severity: "major", source: "manual" });
  const [rbForm, setRbForm] = useState({ trigger_type: "cost_alert", trigger_match: "*", title: "", steps: '[]' });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = new URLSearchParams();
      if (orgId) q.set("organization_id", orgId);
      if (statusFilter) q.set("status", statusFilter);
      const [i, r, m] = await Promise.all([
        platformApi<{ incidents: Incident[] }>(`/api/v1/platform/ops/incidents?${q}`, { token: session.token }),
        platformApi<{ runbooks: Runbook[] }>("/api/v1/platform/ops/runbooks", { token: session.token }),
        platformApi<{ by_severity: SeverityMetric[] }>("/api/v1/platform/ops/incidents/metrics", { token: session.token }),
      ]);
      setIncidents(i.incidents || []);
      setRunbooks(r.runbooks || []);
      setMetrics(m.by_severity || []);
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
    const id = setInterval(() => void loadAll(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function openIncident() {
    if (!session) return;
    setBusy("inc");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ id: string }>("/api/v1/platform/ops/incidents", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId || undefined, ...form }),
      });
      setNote(`Incidente ${out.id.slice(0, 8)}… abierto (runbooks ejecutados).`);
      setForm({ title: "", description: "", severity: "major", source: "manual" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createRunbook() {
    if (!session) return;
    setBusy("rb");
    setError("");
    setNote("");
    try {
      let steps: unknown[] = [];
      try {
        steps = JSON.parse(rbForm.steps || "[]");
      } catch {
        setError("steps JSON inválido");
        return;
      }
      await platformApi("/api/v1/platform/ops/runbooks", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ ...rbForm, steps }),
      });
      setRbForm({ trigger_type: "cost_alert", trigger_match: "*", title: "", steps: '[]' });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(incidentId: string, action: "ack" | "resolve") {
    if (!session) return;
    setBusy(`${action}-${incidentId.slice(0, 6)}`);
    setError("");
    try {
      await platformApi(`/api/v1/platform/ops/incidents/${incidentId}/${action}`, {
        method: "POST",
        token: session.token,
      });
      await loadAll();
      if (detail?.id === incidentId) setDetail(null);
      setConfirmResolve(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(incidentId: string) {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<IncidentDetail>(`/api/v1/platform/ops/incidents/${incidentId}`, { token: session.token });
      setDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const openCount = metrics.reduce((sum, m) => sum + Math.max(m.total - m.resolved, 0), 0);
  const severeOpen = metrics.reduce(
    (sum, m) => sum + (m.severity === "severe" ? Math.max(m.total - m.resolved, 0) : 0),
    0
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ops Center"
        subtitle="Runbooks por alerta, incidentes con SLA (MTTR/MTTD) y escalamiento automático."
      />
      <ErrorInline message={error} />
      {note && <SuccessInline>{note}</SuccessInline>}
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={5} />
        </Panel>
      ) : (
        <>
          <Panel className={`p-4 ${severeOpen > 0 ? "border-danger/40" : ""}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Incidentes sin resolver</p>
                <p
                  className={`mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums ${
                    openCount > 0 ? (severeOpen > 0 ? "text-danger" : "text-warn") : "text-text"
                  }`}
                >
                  {openCount}
                </p>
                <p className="mt-2 flex items-center gap-2 text-[13px] leading-relaxed text-muted">
                  {severeOpen > 0 ? (
                    <>
                      <WarningCircle size={15} weight="fill" className="text-danger" aria-hidden />
                      <span className="text-danger">
                        {severeOpen} crítico(s) abierto(s) requieren intervención inmediata.
                      </span>
                    </>
                  ) : openCount > 0 ? (
                    <span>Sin criticidad severa abierta, pero hay incidentes en curso.</span>
                  ) : (
                    <span>Todo lo detectado está resuelto.</span>
                  )}
                </p>
              </div>
              {metrics.length > 0 && (
                <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
                  {metrics.map((m) => (
                    <div key={m.severity}>
                      <dt className="eyebrow">{SEVERITY_META[m.severity]?.label ?? m.severity}</dt>
                      <dd className="mt-1 text-sm tabular-nums text-text">
                        {Math.max(m.total - m.resolved, 0)} abiertos
                        <span className="block text-xs text-faint">de {m.total}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </Panel>

          {metrics.length > 0 && (
            <section>
              <SectionHeader
                title="SLA por severidad"
                description="MTTR y MTTD medidos por el backend sobre los incidentes registrados."
                className="mb-3"
              />
              <MetricGrid cols={3}>
                {metrics.map((m) => {
                  const meta = SEVERITY_META[m.severity];
                  return (
                    <Metric
                      key={m.severity}
                      size="md"
                      label={`${meta?.label ?? m.severity} · MTTR`}
                      value={minutes(m.avg_mttr_seconds)}
                      tone={meta?.tone === "danger" ? "danger" : meta?.tone === "warn" ? "warn" : "default"}
                      hint={`${m.total} incidentes · ${m.resolved} resueltos · MTTD ${minutes(m.avg_mttd_seconds, 1)}`}
                    />
                  );
                })}
              </MetricGrid>
            </section>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <SectionHeader
                title="Incidentes"
                description="Se refresca cada 15 segundos."
                className="mb-3"
              />
              <Toolbar className="mb-3">
                <Field label="Organización" className="w-full sm:w-48">
                  <Select value={orgId} placeholder="Todas" onChange={(e) => setOrgId(e.target.value)}>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Estado" className="w-full sm:w-44">
                  <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                    <option value="">Todos</option>
                    {["open", "acknowledged", "resolved"].map((s) => (
                      <option key={s} value={s}>
                        {STATUS_META[s]?.label ?? s}
                      </option>
                    ))}
                  </Select>
                </Field>
                <ToolbarSpacer />
                <Button variant="secondary" size="sm" className="self-end" onClick={() => void loadAll()}>
                  Refrescar
                </Button>
              </Toolbar>
              <Panel className="overflow-x-auto">
                <table className="table min-w-[880px]">
                  <thead>
                    <tr>
                      <th>Incidente</th>
                      <th>Severidad</th>
                      <th>Estado</th>
                      <th>Fuente</th>
                      <th className="text-right">MTTR</th>
                      <th>Detectado</th>
                      <th className="text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((i) => {
                      const sev = SEVERITY_META[i.severity] ?? { tone: "neutral" as Tone, label: i.severity };
                      const st = STATUS_META[i.status] ?? { tone: "neutral" as Tone, label: i.status };
                      return (
                        <tr key={i.id} className="state-rail" data-state={RAIL_STATE[i.status] ?? "warning"}>
                          <td>
                            <button
                              type="button"
                              className="cursor-pointer text-left font-medium text-accent hover:underline"
                              onClick={() => void showDetail(i.id)}
                            >
                              {i.title}
                            </button>
                          </td>
                          <td>
                            <Badge tone={sev.tone} dot>
                              {sev.label}
                            </Badge>
                          </td>
                          <td>
                            <Badge tone={st.tone} dot>
                              {st.label}
                            </Badge>
                          </td>
                          <td className="mono text-xs text-faint">{i.source}</td>
                          <td className="text-right tabular-nums">{minutes(i.mttr_seconds, 1)}</td>
                          <td className="text-xs text-muted tabular-nums">
                            {new Date(i.detected_at).toLocaleString("es-PE")}
                          </td>
                          <td className="text-right whitespace-nowrap">
                            {i.status !== "resolved" && (
                              <>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={busy === `ack-${i.id.slice(0, 6)}`}
                                  onClick={() => void act(i.id, "ack")}
                                >
                                  Reconocer
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={busy === `resolve-${i.id.slice(0, 6)}`}
                                  onClick={() => setConfirmResolve(i)}
                                >
                                  Resolver
                                </Button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {incidents.length === 0 && (
                      <tr>
                        <td colSpan={7}>
                          <EmptyState
                            icon={ShieldCheck}
                            compact
                            title="Sin incidentes"
                            body="No hay incidentes que coincidan con los filtros seleccionados."
                          />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Panel>
            </section>

            <div className="space-y-4">
              <Panel>
                <PanelHeader
                  title="Abrir incidente"
                  description="Dispara los runbooks cuyo trigger coincida."
                />
                <div className="space-y-3 p-4">
                  <Field label="Título" required>
                    <Input
                      value={form.title}
                      onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                    />
                  </Field>
                  <Field label="Descripción">
                    <Input
                      value={form.description}
                      onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                    />
                  </Field>
                  <Field label="Severidad">
                    <Select
                      value={form.severity}
                      onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value }))}
                    >
                      {["severe", "major", "minor"].map((s) => (
                        <option key={s} value={s}>
                          {SEVERITY_META[s].label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Button
                    variant="primary"
                    leadingIcon={ShieldCheck}
                    loading={busy === "inc"}
                    disabled={!form.title}
                    onClick={() => void openIncident()}
                  >
                    Abrir (auto-runbook)
                  </Button>
                </div>
              </Panel>

              <Panel>
                <PanelHeader title="Runbooks" description="Se ejecutan automáticamente al abrir un incidente." />
                <div className="space-y-3 p-4">
                  <Field label="Título" required>
                    <Input
                      value={rbForm.title}
                      onChange={(e) => setRbForm((f) => ({ ...f, title: e.target.value }))}
                    />
                  </Field>
                  <Field label="Trigger">
                    <Select
                      value={rbForm.trigger_type}
                      onChange={(e) => setRbForm((f) => ({ ...f, trigger_type: e.target.value }))}
                    >
                      {["cost_alert", "slo", "manual", "deployment"].map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field
                    label="Pasos (JSON)"
                    hint='Ej. [{"action":"annotate","params":{}}]'
                  >
                    <Textarea
                      className="min-h-20 font-mono text-xs"
                      value={rbForm.steps}
                      onChange={(e) => setRbForm((f) => ({ ...f, steps: e.target.value }))}
                    />
                  </Field>
                  <Button
                    variant="secondary"
                    leadingIcon={Plus}
                    loading={busy === "rb"}
                    disabled={!rbForm.title}
                    onClick={() => void createRunbook()}
                  >
                    Crear runbook
                  </Button>
                </div>
                <div className="overflow-x-auto border-t border-border">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Runbook</th>
                        <th>Trigger</th>
                        <th className="text-right">Pasos</th>
                        <th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runbooks.map((r) => (
                        <tr key={r.id}>
                          <td className="text-[13px]">{r.title}</td>
                          <td className="mono text-xs text-faint">
                            {r.trigger_type}
                            {r.trigger_match !== "*" ? `:${r.trigger_match}` : ""}
                          </td>
                          <td className="text-right tabular-nums">{r.steps.length}</td>
                          <td>
                            <Badge tone={r.enabled ? "ok" : "neutral"} dot>
                              {r.enabled ? "Activo" : "Inactivo"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                      {runbooks.length === 0 && (
                        <tr>
                          <td colSpan={4}>
                            <EmptyState
                              icon={ShieldCheck}
                              compact
                              title="Sin runbooks"
                              body="Ningún incidente ejecuta acciones automáticas todavía."
                            />
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>
        </>
      )}

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => !open && setDetail(null)}
        title={detail?.title ?? "Incidente"}
        description={detail?.description ?? undefined}
        width={520}
        footer={
          detail && detail.status !== "resolved" ? (
            <>
              <Button variant="ghost" onClick={() => void act(detail.id, "ack")}>
                Reconocer
              </Button>
              <Button variant="primary" onClick={() => setConfirmResolve(detail)}>
                Resolver
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setDetail(null)}>
              Cerrar
            </Button>
          )
        }
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={SEVERITY_META[detail.severity]?.tone ?? "neutral"} dot>
                {SEVERITY_META[detail.severity]?.label ?? detail.severity}
              </Badge>
              <Badge tone={STATUS_META[detail.status]?.tone ?? "neutral"} dot>
                {STATUS_META[detail.status]?.label ?? detail.status}
              </Badge>
              <Badge tone="neutral">{detail.source}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Detectado", value: new Date(detail.detected_at).toLocaleString("es-PE"), mono: true },
                { key: "Ocurrió", value: new Date(detail.occurred_at).toLocaleString("es-PE"), mono: true },
                { key: "MTTR", value: minutes(detail.mttr_seconds, 1) },
                { key: "MTTD", value: minutes(detail.mttd_seconds, 1) },
                { key: "Reconocido", value: detail.acknowledged_at ? new Date(detail.acknowledged_at).toLocaleString("es-PE") : "—", mono: true },
                { key: "Resuelto", value: detail.resolved_at ? new Date(detail.resolved_at).toLocaleString("es-PE") : "—", mono: true },
                { key: "Organización", value: detail.organization_id, mono: true },
              ]}
            />
            <div>
              <h3 className="eyebrow mb-2">Timeline</h3>
              {(detail.timeline ?? []).length === 0 ? (
                <p className="text-[13px] text-muted">El incidente no registró eventos.</p>
              ) : (
                <ol className="relative ml-2 border-l border-border-soft">
                  {[...(detail.timeline ?? [])]
                    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
                    .map((e) => {
                      const meta = EVENT_META[e.type] ?? { tone: "neutral" as Tone, label: e.type };
                      return (
                        <li key={e.id} className="relative ml-4 pb-4 pl-4 last:pb-1">
                          <span
                            className={`absolute top-1 -left-[5px] h-2 w-2 rounded-full ${
                              meta.tone === "ok"
                                ? "bg-ok"
                                : meta.tone === "warn"
                                  ? "bg-warn"
                                  : meta.tone === "danger"
                                    ? "bg-danger"
                                    : meta.tone === "info"
                                      ? "bg-info"
                                      : "bg-faint"
                            }`}
                            aria-hidden
                          />
                          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                            <time dateTime={e.created_at} className="text-xs text-faint tabular-nums">
                              {new Date(e.created_at).toLocaleString("es-PE")}
                            </time>
                          </div>
                          <p className="mt-1 text-[13px] leading-relaxed text-muted">{e.detail}</p>
                        </li>
                      );
                    })}
                </ol>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmResolve !== null}
        onOpenChange={(open) => !open && setConfirmResolve(null)}
        title="Resolver incidente"
        body={
          confirmResolve
            ? `"${confirmResolve.title}" pasa a resuelto y el MTTR queda registrado con este cierre.`
            : undefined
        }
        confirmLabel="Resolver"
        tone="primary"
        onConfirm={() => confirmResolve && void act(confirmResolve.id, "resolve")}
      />
    </div>
  );
}
