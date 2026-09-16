import {
  CheckCircle,
  Clock,
  Plus,
  Prohibit,
  Question,
  ShieldWarning,
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
  Switch,
  Textarea,
  type Column,
  type Tone,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Terms = { latest: { version: number; title: string; content: string } | null; versions: { version: number; title: string }[] };
type Consent = { organization_id: string; terms_version: number; consented_by: string | null; consented_at: string };
type Rule = { id: string; organization_id: string | null; name: string; category: string; patterns: string[]; min_score: number; action: string; enabled: boolean };
type Incident = { id: string; organization_id: string; direction: string; rule_name: string; score: number; snippet: string; action: string; status: string; resolution_note: string | null; created_at: string };
type Trust = { queries: number; blocked: number; warned: number; inputs: number; outputs: number; block_rate: number; by_rule: { rule_name: string; direction: string; action: string; total: number; resolved: number; dismissed: number; resolution_rate: number; avg_score: number }[] };

const CATEGORIES = ["prohibited_topics", "toxicity", "malware", "financial_advice", "legal", "medical", "pii"];
const ACTIONS = ["block", "warn"];

/** Estado de un incidente de contenido. */
const INCIDENT_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  open: { label: "Abierto", tone: "warn", icon: Clock },
  resolved: { label: "Resuelto", tone: "ok", icon: CheckCircle },
  dismissed: { label: "Desestimado", tone: "neutral", icon: Prohibit },
};

function IncidentStatusBadge({ status }: { status: string }) {
  const meta = INCIDENT_STATUS_META[status] ?? {
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

export default function AdminTrustSafetyPage() {
  const { session } = usePlatformAuth();
  const [terms, setTerms] = useState<Terms | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [trust, setTrust] = useState<Trust | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [ruleForm, setRuleForm] = useState({ name: "", category: "prohibited_topics", action: "block", min_score: 0.6, patterns: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<Incident | null>(null);

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = new URLSearchParams();
      if (orgId) q.set("organization_id", orgId);
      if (statusFilter) q.set("status", statusFilter);
      const [t, c, r, i, d] = await Promise.all([
        platformApi<Terms>("/api/v1/platform/trust/aup/terms", { token: session.token }),
        platformApi<{ consents: Consent[] }>("/api/v1/platform/trust/aup/consents", { token: session.token }),
        platformApi<{ rules: Rule[] }>(`/api/v1/platform/trust/rules${orgId ? `?organization_id=${orgId}` : ""}`, { token: session.token }),
        platformApi<{ incidents: Incident[] }>(`/api/v1/platform/trust/incidents?${q}`, { token: session.token }),
        platformApi<Trust>("/api/v1/platform/trust/dashboard?hours=24", { token: session.token }),
      ]);
      setTerms(t);
      setConsents(c.consents || []);
      setRules(r.rules || []);
      setIncidents(i.incidents || []);
      setTrust(d);
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
        if (o.organizations?.length) setOrgId(o.organizations[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, statusFilter]);

  async function acceptAup() {
    if (!session) return;
    setBusy("aup");
    setError("");
    try {
      await platformApi("/api/v1/platform/trust/aup/accept", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, terms_version: terms?.latest?.version ?? 1 }),
      });
      setNote("AUP aceptada por la org.");
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createRule() {
    if (!session) return;
    setBusy("rule");
    setError("");
    try {
      const patterns = ruleForm.patterns.split(",").map((p) => p.trim()).filter(Boolean);
      await platformApi("/api/v1/platform/trust/rules", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ ...ruleForm, patterns, organization_id: orgId }),
      });
      setRuleForm({ name: "", category: "prohibited_topics", action: "block", min_score: 0.6, patterns: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggle(rule: Rule) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/trust/rules/${rule.id}/toggle`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function act(incidentId: string, action: "resolve" | "dismiss") {
    if (!session) return;
    setBusy(`${action}-${incidentId.slice(0, 6)}`);
    try {
      await platformApi(`/api/v1/platform/trust/incidents/${incidentId}/${action}`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ note: action === "resolve" ? "Revisado por el equipo de seguridad" : "Falso positivo" }),
      });
      setSelected(null);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const myConsent = consents.find((c) => c.organization_id === orgId);

  const columns: Column<Incident>[] = [
    {
      key: "created_at",
      header: "Hora",
      width: "120px",
      render: (i) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(i.created_at)}</span>,
    },
    {
      key: "direction",
      header: "Dir.",
      render: (i) => <span className="mono text-xs text-muted">{i.direction}</span>,
    },
    {
      key: "rule_name",
      header: "Regla",
      render: (i) => (
        <span className="block max-w-40 truncate text-[13px] text-text" title={i.rule_name}>
          {i.rule_name}
        </span>
      ),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      render: (i) => <span className="mono text-xs text-muted tabular-nums">{(i.score * 100).toFixed(0)}%</span>,
    },
    {
      key: "snippet",
      header: "Snippet",
      hideBelow: "lg",
      render: (i) => (
        <span className="block max-w-64 truncate text-xs text-faint" title={i.snippet}>
          {i.snippet}
        </span>
      ),
    },
    {
      key: "action",
      header: "Acción",
      hideBelow: "md",
      render: (i) =>
        i.action === "block" ? (
          <Badge tone="danger" icon={XCircle}>
            block
          </Badge>
        ) : (
          <Badge tone="warn" icon={WarningCircle}>
            {i.action}
          </Badge>
        ),
    },
    {
      key: "status",
      header: "Estado",
      render: (i) => <IncidentStatusBadge status={i.status} />,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trust & Safety Center"
        subtitle="AUP versionada, moderación de contenido con puntuación e incidentes."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {note && <SuccessInline message={note} />}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid className="xl:grid-cols-5">
            <Metric label="Consultas (24h)" value={(trust?.queries ?? 0).toLocaleString()} />
            <Metric
              label="Bloqueos"
              value={trust?.blocked ?? 0}
              size="md"
              tone={(trust?.blocked ?? 0) > 0 ? "danger" : "default"}
              icon={Prohibit}
            />
            <Metric
              label="Warnings"
              value={trust?.warned ?? 0}
              size="md"
              tone={(trust?.warned ?? 0) > 0 ? "warn" : "default"}
              icon={WarningCircle}
            />
            <Metric label="Block rate" value={`${((trust?.block_rate ?? 0) * 100).toFixed(2)}%`} size="md" />
            <Metric label="Input / Output" value={`${trust?.inputs ?? 0} / ${trust?.outputs ?? 0}`} size="md" hint="Consultas por dirección" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <ShieldWarning size={15} className="text-faint" aria-hidden />
                    AUP
                  </span>
                }
                description={terms?.latest ? `v${terms.latest.version}: ${terms.latest.title}` : "Sin términos cargados."}
              />
              <div className="panel-body flex flex-col gap-3">
                <div className="max-h-28 overflow-auto rounded-sm border border-border bg-control p-2.5">
                  <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted">
                    {terms?.latest?.content ?? "Sin términos."}
                  </p>
                </div>
                <Field label="Organización">
                  <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    variant="primary"
                    size="sm"
                    loading={busy === "aup"}
                    disabled={!!busy || !orgId}
                    onClick={() => void acceptAup()}
                  >
                    Aceptar
                  </Button>
                  {myConsent ? (
                    <span className="text-xs text-muted">
                      Consentimiento v{myConsent.terms_version} · {fmtDateTime(myConsent.consented_at)}
                    </span>
                  ) : (
                    <Badge tone="warn" icon={WarningCircle}>
                      Sin consentimiento de esta org
                    </Badge>
                  )}
                </div>
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Reglas de moderación" description="Se aplican sobre inputs y outputs de la organización." />
              <div className="panel-body flex flex-col gap-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="Nombre">
                    <Input
                      placeholder="p. ej. malware-crítico"
                      value={ruleForm.name}
                      onChange={(e) => setRuleForm((f) => ({ ...f, name: e.target.value }))}
                    />
                  </Field>
                  <Field label="Categoría">
                    <Select
                      value={ruleForm.category}
                      onChange={(e) => setRuleForm((f) => ({ ...f, category: e.target.value }))}
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Acción" className="sm:col-span-1">
                    <Select
                      value={ruleForm.action}
                      onChange={(e) => setRuleForm((f) => ({ ...f, action: e.target.value }))}
                    >
                      {ACTIONS.map((a) => (
                        <option key={a} value={a}>
                          {a}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Score mínimo">
                    <Input
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      className="mono"
                      value={ruleForm.min_score}
                      onChange={(e) => setRuleForm((f) => ({ ...f, min_score: Number(e.target.value) }))}
                    />
                  </Field>
                  <Field label="Patterns" hint="Separados por coma." className="sm:col-span-2">
                    <Textarea
                      rows={2}
                      placeholder='"hackear cuenta, ransomware"'
                      value={ruleForm.patterns}
                      onChange={(e) => setRuleForm((f) => ({ ...f, patterns: e.target.value }))}
                    />
                  </Field>
                </div>
                <div>
                  <Button
                    variant="primary"
                    size="sm"
                    leadingIcon={Plus}
                    loading={busy === "rule"}
                    disabled={!!busy || !ruleForm.name.trim()}
                    onClick={() => void createRule()}
                  >
                    Crear
                  </Button>
                </div>
                <ul className="divide-y divide-border-soft border-t border-border-soft">
                  {rules.map((r) => (
                    <li key={r.id} className="py-3">
                      <Switch
                        checked={r.enabled}
                        onCheckedChange={() => void toggle(r)}
                        label={r.name}
                        hint={`${r.category} · ≥${r.min_score} · ${r.action} · ${r.enabled ? "Activa" : "Inactiva"}`}
                      />
                    </li>
                  ))}
                  {rules.length === 0 && <li className="py-3 text-[13px] text-muted">Sin reglas para esta org.</li>}
                </ul>
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Tasas por regla (24h)" description="Incidentes, resolución y score promedio." />
              <ul className="divide-y divide-border-soft">
                {(trust?.by_rule ?? []).map((r) => (
                  <li key={`${r.rule_name}:${r.direction}`} className="px-4 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-xs text-text" title={`${r.rule_name} (${r.direction})`}>
                        {r.rule_name} ({r.direction})
                      </span>
                      {r.action === "block" ? (
                        <Badge tone="danger" icon={XCircle}>
                          block
                        </Badge>
                      ) : (
                        <Badge tone="warn" icon={WarningCircle}>
                          {r.action}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-faint tabular-nums">
                      {r.total} inc · resuelto {r.resolved} ({(r.resolution_rate * 100).toFixed(0)}%) · score avg {r.avg_score}
                    </p>
                  </li>
                ))}
                {(trust?.by_rule ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin incidentes en la ventana.</li>
                )}
              </ul>
            </Panel>
          </div>

          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-h2">Incidentes de contenido</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  Seleccioná una fila para ver el snippet completo y la resolución registrada.
                </p>
              </div>
              <Select
                className="w-full sm:w-44"
                aria-label="Filtrar por estado"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="">todos los estados</option>
                <option value="open">Abiertos</option>
                <option value="resolved">Resueltos</option>
                <option value="dismissed">Desestimados</option>
              </Select>
            </div>
            <DataTable
              columns={columns}
              rows={incidents}
              rowKey={(i) => i.id}
              caption="Incidentes de contenido"
              stickyHeader
              onRowClick={(i) => setSelected(i)}
              rowActions={(i) =>
                i.status === "open" ? (
                  <>
                    <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => void act(i.id, "resolve")}>
                      Resolver
                    </Button>
                    <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => void act(i.id, "dismiss")}>
                      Desestimar
                    </Button>
                  </>
                ) : null
              }
              empty={
                <p className="px-4 py-6 text-center text-[13px] text-muted">
                  {statusFilter ? "Ningún incidente coincide con el estado seleccionado." : "Sin incidentes registrados."}
                </p>
              }
              footer={incidents.length > 0 ? <ResultCount shown={incidents.length} total={incidents.length} noun="incidentes" /> : undefined}
            />
          </section>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Evidencia del incidente"
        description={selected ? `${selected.rule_name} · ${selected.direction}` : undefined}
        width={520}
        footer={
          selected && selected.status === "open" ? (
            <>
              <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => void act(selected.id, "dismiss")}>
                Desestimar
              </Button>
              <Button variant="primary" size="sm" disabled={!!busy} onClick={() => void act(selected.id, "resolve")}>
                Resolver
              </Button>
            </>
          ) : undefined
        }
      >
        {selected && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <IncidentStatusBadge status={selected.status} />
              {selected.action === "block" ? (
                <Badge tone="danger" icon={XCircle}>
                  block
                </Badge>
              ) : (
                <Badge tone="warn" icon={WarningCircle}>
                  {selected.action}
                </Badge>
              )}
              <Badge tone="neutral">Score {(selected.score * 100).toFixed(0)}%</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Regla", value: selected.rule_name },
                { key: "Dirección", value: selected.direction, mono: true },
                { key: "Organización", value: selected.organization_id, mono: true },
                { key: "Detectado", value: fmtDateTime(selected.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Snippet detectado</p>
              <p className="rounded-sm border border-border bg-control px-3 py-2 text-[13px] leading-relaxed break-words whitespace-pre-wrap text-text">
                {selected.snippet}
              </p>
            </div>
            <div>
              <p className="eyebrow mb-2">Nota de resolución</p>
              <p className="text-[13px] leading-relaxed text-muted">
                {selected.resolution_note ?? "Sin nota registrada todavía."}
              </p>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
