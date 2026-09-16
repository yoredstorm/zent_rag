import {
  CheckCircle,
  Clock,
  Info,
  Minus,
  Question,
  ShieldWarning,
  WarningCircle,
  WarningOctagon,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  InfoInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  Textarea,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Risk = { id: string; agent_id: string | null; agent_name: string | null; risk_type: string; severity: string; likelihood: number; impact: number; score: number; status: string; source: string; evidence: Record<string, unknown>; mitigations: number; created_at: string };
type Heatmap = { heatmap: { agent_id: string; agent_name: string; risks: Record<string, { severity: string; score: number }> }[] };
type Posture = { framework: string; total_controls: number; implemented: number; in_review: number; not_implemented: number; score: number; by_risk_type: Record<string, { total: number; implemented: number; pct: number }>; controls: { control_id: string; title: string; risk_type: string | null; status: string }[] };
type Trend = { trend: { date: string; score: number }[] };
type Mitigation = { id: string; risk_id: string; action_type: string; description: string | null; created_at: string; risk_type: string; severity: string };

const FRAMEWORKS = [
  { id: "eu_ai_act", label: "EU AI Act" },
  { id: "soc2", label: "SOC 2" },
  { id: "gdpr", label: "GDPR" },
  { id: "iso27001", label: "ISO 27001" },
];

const RISK_TYPES = ["bias", "hallucination", "pii_leak", "security", "safety"];

/** Valores que acepta el alta manual (los mismos que ya enviaba el formulario). */
const SEVERITY_OPTIONS = ["low", "medium", "high", "critical"];

/**
 * Escala única de severidad del bloque de seguridad y riesgo
 * (crítica → alta → media → baja). Mismos valores en SecurityAudit,
 * SecurityCenter y RiskCenter.
 */
const SEVERITY_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  critical: { label: "Crítica", tone: "danger", icon: WarningOctagon },
  high: { label: "Alta", tone: "warn", icon: WarningCircle },
  medium: { label: "Media", tone: "info", icon: Info },
  low: { label: "Baja", tone: "neutral", icon: Minus },
  info: { label: "Informativa", tone: "neutral", icon: Info },
};

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

function SeverityBadge({ severity }: { severity: string }) {
  const meta = SEVERITY_META[severity] ?? {
    label: severity || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

/** Estado del riesgo en el registro (vocabulario propio de Risk Center). */
const RISK_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  open: { label: "Abierto", tone: "warn", icon: Clock },
  mitigated: { label: "Mitigado", tone: "ok", icon: CheckCircle },
  accepted: { label: "Aceptado", tone: "info", icon: Info },
  closed: { label: "Cerrado", tone: "neutral", icon: CheckCircle },
};

function RiskStatusBadge({ status }: { status: string }) {
  const meta = RISK_STATUS_META[status] ?? {
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

/** Estado de un control de cumplimiento: implementado / en revisión / faltante. */
const CONTROL_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  implemented: { label: "Implementado", tone: "ok", icon: CheckCircle },
  in_review: { label: "En revisión", tone: "warn", icon: Clock },
  not_implemented: { label: "No implementado", tone: "danger", icon: XCircle },
};

function ControlStatusBadge({ status }: { status: string }) {
  const meta = CONTROL_STATUS_META[status] ?? {
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

type RiskRow = Risk & { severityRank: number; agentLabel: string };

const RISK_COLUMNS: Column<RiskRow>[] = [
  {
    key: "agentLabel",
    header: "Agente",
    sortable: true,
    render: (r) => <span className="text-xs text-muted">{r.agentLabel}</span>,
  },
  {
    key: "risk_type",
    header: "Tipo",
    sortable: true,
    render: (r) => <span className="mono text-xs text-text">{r.risk_type}</span>,
  },
  {
    key: "severityRank",
    header: "Severidad",
    sortable: true,
    render: (r) => <SeverityBadge severity={r.severity} />,
  },
  {
    key: "score",
    header: "Score",
    sortable: true,
    align: "right",
    render: (r) => <span className="mono text-xs text-muted">{r.score}</span>,
  },
  {
    key: "likelihood",
    header: "Exposición",
    sortable: true,
    align: "right",
    hideBelow: "lg",
    render: (r) => (
      <span className="text-xs text-muted tabular-nums">
        {r.likelihood} × {r.impact}
      </span>
    ),
  },
  {
    key: "mitigations",
    header: "Mitigaciones",
    sortable: true,
    align: "right",
    hideBelow: "xl",
    render: (r) => <span className="mono text-xs text-faint">{r.mitigations}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (r) => <RiskStatusBadge status={r.status} />,
  },
  {
    key: "created_at",
    header: "Creado",
    sortable: true,
    hideBelow: "md",
    render: (r) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(r.created_at)}</span>,
  },
];

const CONTROL_COLUMNS: Column<Posture["controls"][number]>[] = [
  {
    key: "control_id",
    header: "Control",
    sortable: true,
    render: (c) => <span className="mono text-xs text-text">{c.control_id}</span>,
  },
  {
    key: "title",
    header: "Título",
    render: (c) => <span className="text-[13px] text-muted">{c.title}</span>,
  },
  {
    key: "risk_type",
    header: "Riesgo asociado",
    hideBelow: "md",
    render: (c) => <span className="text-xs text-faint">{c.risk_type ?? "—"}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (c) => <ControlStatusBadge status={c.status} />,
  },
];

const CONTROL_PAGE_SIZE = 15;

export default function RiskCenterPage() {
  const { session } = useAuth();
  const [risks, setRisks] = useState<Risk[]>([]);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [mitigations, setMitigations] = useState<Mitigation[]>([]);
  const [framework, setFramework] = useState("eu_ai_act");
  const [draft, setDraft] = useState({ risk_type: "bias", severity: "medium", notes: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<string>("");
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [controlSort, setControlSort] = useState<SortState>(null);
  const [controlPage, setControlPage] = useState(1);
  const [selected, setSelected] = useState<Risk | null>(null);
  const [confirmAccept, setConfirmAccept] = useState(false);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, hm, p, t, m] = await Promise.all([
        api<{ risks: Risk[] }>("/api/v1/risk-center/register", { token: session.token, organizationId: session.organizationId }),
        api<Heatmap>("/api/v1/risk-center/heatmap", { token: session.token, organizationId: session.organizationId }),
        api<Posture>(`/api/v1/risk-center/compliance/posture?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
        api<Trend>(`/api/v1/risk-center/compliance/trend?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
        api<{ mitigations: Mitigation[] }>("/api/v1/risk-center/mitigations", { token: session.token, organizationId: session.organizationId }),
      ]);
      setRisks(r.risks || []);
      setHeatmap(hm);
      setPosture(p);
      setTrend(t);
      setMitigations(m.mitigations || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, framework]);

  async function assess() {
    if (!session) return;
    setBusy("assess");
    setError("");
    setNotice("");
    try {
      const out = await api<{ assessments: { risk_type: string; created: boolean }[] }>("/api/v1/risk-center/assess", { method: "POST", token: session.token, organizationId: session.organizationId });
      const created = out.assessments.filter((a) => a.created).map((a) => a.risk_type);
      setNotice(created.length ? `Evaluación completa. Riesgos nuevos: ${created.join(", ")}.` : "Evaluación completa: sin riesgos nuevos.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addRisk() {
    if (!session) return;
    setBusy("add");
    setError("");
    setNotice("");
    try {
      await api("/api/v1/risk-center/risks", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draft),
      });
      setDraft({ risk_type: "bias", severity: "medium", notes: "" });
      setNotice("Riesgo registrado.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(id: string, action: "mitigate" | "accept") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const body = action === "mitigate" ? JSON.stringify({ description: "Mitigación registrada" }) : JSON.stringify({ reason: "Riesgo aceptado por el equipo" });
      await api(`/api/v1/risk-center/risks/${id}/${action}`, { method: "POST", token: session.token, organizationId: session.organizationId, body });
      setNotice(action === "mitigate" ? "Mitigación registrada." : "Riesgo aceptado y firmado en el registro.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const rows = useMemo<RiskRow[]>(
    () =>
      risks.map((r) => ({
        ...r,
        severityRank: SEVERITY_ORDER[r.severity] ?? 9,
        agentLabel: r.agent_name ?? "General",
      })),
    [risks],
  );

  const sortedRisks = useMemo(() => {
    if (!sort) return rows;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const left = (a as unknown as Record<string, unknown>)[sort.key];
      const right = (b as unknown as Record<string, unknown>)[sort.key];
      if (typeof left === "number" && typeof right === "number") return (left - right) * dir;
      return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
    });
  }, [rows, sort]);

  const sortedControls = useMemo(() => {
    if (!controlSort) return posture?.controls ?? [];
    const dir = controlSort.dir === "asc" ? 1 : -1;
    return [...(posture?.controls ?? [])].sort((a, b) => {
      const left = (a as unknown as Record<string, unknown>)[controlSort.key];
      const right = (b as unknown as Record<string, unknown>)[controlSort.key];
      return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
    });
  }, [posture, controlSort]);
  const controlPageRows = sortedControls.slice((controlPage - 1) * CONTROL_PAGE_SIZE, controlPage * CONTROL_PAGE_SIZE);

  const trendPoints = (trend?.trend ?? []).slice(-14);
  const frameworkLabel = FRAMEWORKS.find((f) => f.id === framework)?.label ?? framework;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Risk & Compliance Center"
        subtitle="Registro de riesgos de IA con scoring, mitigaciones, heatmap por agente y postura de cumplimiento."
        actions={
          <Button variant="secondary" leadingIcon={ShieldWarning} loading={busy === "assess"} disabled={busy !== ""} onClick={() => void assess()}>
            Evaluar riesgos
          </Button>
        }
      />

      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <InfoInline message={notice} />}

      {loading ? (
        <div className="panel">
          <div className="panel-body">
            <SkeletonBlock rows={6} />
          </div>
        </div>
      ) : (
        <>
          <MetricGrid>
            <Metric
              label={`Postura ${frameworkLabel}`}
              value={`${posture?.score ?? 0}%`}
              hint={`${posture?.implemented ?? 0}/${posture?.total_controls ?? 0} controles implementados`}
              help="Porcentaje de controles implementados sobre el total del framework seleccionado."
            />
            <Metric label="En revisión" value={posture?.in_review ?? 0} size="md" hint="Controles sin veredicto final" />
            <Metric label="Riesgos en registro" value={risks.length} size="md" hint={`${mitigations.length} mitigaciones registradas`} />
            <Metric label="Agentes con riesgo" value={heatmap?.heatmap.length ?? 0} size="md" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={RISK_COLUMNS}
                rows={sortedRisks}
                rowKey={(r) => r.id}
                caption="Riesgos registrados"
                stickyHeader
                sort={sort}
                onSortChange={setSort}
                onRowClick={(r) => setSelected(r)}
                empty={
                  <EmptyState
                    icon={ShieldWarning}
                    title="Sin riesgos en el registro"
                    body="No hay riesgos cargados ni detectados por la evaluación automática."
                    hint="Registrá uno a mano o corré «Evaluar riesgos» para revisar el workspace."
                  />
                }
                footer={sortedRisks.length > 0 ? <ResultCount shown={sortedRisks.length} total={rows.length} noun="riesgos" /> : undefined}
              />
            </div>

            <Panel>
              <PanelHeader
                title="Registrar riesgo"
                description="Alta manual con severidad declarada. La evaluación automática carga el resto."
              />
              <div className="panel-body flex flex-col gap-4">
                <Field label="Tipo de riesgo">
                  <Select
                    value={draft.risk_type}
                    onChange={(e) => setDraft((d) => ({ ...d, risk_type: e.target.value }))}
                  >
                    {RISK_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field
                  label="Severidad"
                  hint="Crítica y alta entran en el seguimiento prioritario del registro."
                >
                  <Select
                    value={draft.severity}
                    onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value }))}
                  >
                    {SEVERITY_OPTIONS.map((id) => (
                      <option key={id} value={id}>
                        {SEVERITY_META[id].label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Notas">
                  <Textarea
                    value={draft.notes}
                    onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
                    placeholder="Contexto, alcance, evidencia disponible…"
                    rows={3}
                  />
                </Field>
                <FormActions>
                  <Button variant="primary" loading={busy === "add"} disabled={busy !== ""} onClick={() => void addRisk()}>
                    Registrar
                  </Button>
                </FormActions>
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={CONTROL_COLUMNS}
                rows={controlPageRows}
                rowKey={(c) => c.control_id}
                caption={`Controles de ${frameworkLabel}`}
                dense
                stickyHeader
                sort={controlSort}
                onSortChange={(next) => {
                  setControlSort(next);
                  setControlPage(1);
                }}
                toolbar={
                  <>
                    <Select
                      className="w-full sm:w-52"
                      aria-label="Framework de cumplimiento"
                      value={framework}
                      onChange={(e) => {
                        setFramework(e.target.value);
                        setControlPage(1);
                      }}
                    >
                      {FRAMEWORKS.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.label}
                        </option>
                      ))}
                    </Select>
                    <span className="flex-1" aria-hidden />
                    <span className="text-xs text-muted tabular-nums">
                      {posture?.implemented ?? 0} implementados · {posture?.in_review ?? 0} en revisión · {posture?.not_implemented ?? 0} faltantes
                    </span>
                  </>
                }
                empty={
                  <EmptyState
                    icon={CheckCircle}
                    title="Sin controles cargados"
                    body={`El framework ${frameworkLabel} todavía no tiene controles asociados a esta organización.`}
                  />
                }
                footer={
                  sortedControls.length > 0 ? (
                    <>
                      <ResultCount shown={controlPageRows.length} total={sortedControls.length} noun="controles" />
                      {sortedControls.length > CONTROL_PAGE_SIZE && (
                        <Pagination page={controlPage} pageSize={CONTROL_PAGE_SIZE} total={sortedControls.length} onPageChange={setControlPage} />
                      )}
                    </>
                  ) : undefined
                }
              />
            </div>

            <div className="space-y-4">
              <Panel>
                <PanelHeader title="Cobertura por tipo de riesgo" description={`Controles implementados por tipo en ${frameworkLabel}.`} />
                <div className="panel-body">
                  {Object.keys(posture?.by_risk_type ?? {}).length === 0 ? (
                    <p className="text-[13px] leading-relaxed text-muted">Sin controles por tipo todavía.</p>
                  ) : (
                    <ul className="divide-y divide-border-soft">
                      {Object.entries(posture?.by_risk_type ?? {}).map(([rt, v]) => (
                        <li key={rt} className="flex items-baseline justify-between gap-3 py-2 first:pt-0 last:pb-0">
                          <span className="mono min-w-0 truncate text-xs text-text">{rt}</span>
                          <span className="shrink-0 text-xs text-muted tabular-nums">
                            {v.implemented}/{v.total} · {v.pct}%
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Panel>

              <Panel>
                <PanelHeader title="Tendencia de postura" description="Score diario de los últimos 14 días con datos." />
                <div className="panel-body">
                  {trendPoints.length === 0 ? (
                    <p className="text-[13px] leading-relaxed text-muted">Sin serie histórica todavía.</p>
                  ) : (
                    <>
                      <div className="flex h-20 items-end gap-1" aria-hidden>
                        {trendPoints.map((t) => (
                          <div
                            key={t.date}
                            className="flex-1 rounded-t-xs bg-accent/60"
                            style={{ height: `${Math.max(t.score, 3)}%` }}
                            title={`${t.date}: ${t.score}%`}
                          />
                        ))}
                      </div>
                      <p className="mt-2 text-xs text-faint tabular-nums">
                        {trendPoints[0].date} — {trendPoints[trendPoints.length - 1].date} · último {trendPoints[trendPoints.length - 1].score}%
                      </p>
                    </>
                  )}
                </div>
              </Panel>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
            <Panel>
              <PanelHeader title="Heatmap por agente" description="Riesgos abiertos y su score, agrupados por agente." />
              <div className="panel-body">
                {(heatmap?.heatmap ?? []).length === 0 ? (
                  <p className="text-[13px] leading-relaxed text-muted">
                    Ningún agente tiene riesgos abiertos. El heatmap se llena cuando la evaluación detecta hallazgos.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-3">
                    {(heatmap?.heatmap ?? []).map((a) => (
                      <li key={a.agent_id}>
                        <p className="text-[13px] font-medium text-text">{a.agent_name}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {Object.entries(a.risks).map(([rt, v]) => (
                            <Badge key={rt} tone={SEVERITY_META[v.severity]?.tone ?? "neutral"} icon={SEVERITY_META[v.severity]?.icon ?? Question}>
                              {rt} · {v.score}
                            </Badge>
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Mitigaciones" description="Acciones registradas sobre los riesgos del registro." />
              <div className="panel-body">
                {mitigations.length === 0 ? (
                  <p className="text-[13px] leading-relaxed text-muted">
                    Sin mitigaciones. Se registran al mitigar un riesgo desde su detalle.
                  </p>
                ) : (
                  <ul className="max-h-[320px] divide-y divide-border-soft overflow-y-auto">
                    {mitigations.map((m) => (
                      <li key={m.id} className="py-2 first:pt-0 last:pb-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <SeverityBadge severity={m.severity} />
                          <span className="mono text-xs text-text">{m.action_type}</span>
                          <span className="text-xs text-faint">{m.risk_type}</span>
                          <span className="ml-auto text-[11px] text-faint tabular-nums">{fmtDateTime(m.created_at)}</span>
                        </div>
                        {m.description && <p className="mt-1 text-xs leading-relaxed text-muted">{m.description}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>
          </div>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Detalle del riesgo"
        description={selected ? `${selected.risk_type} · ${selected.agent_name ?? "General"}` : undefined}
        width={520}
        footer={
          selected && (
            <>
              <Button
                variant="secondary"
                loading={busy === `mitigate-${selected.id.slice(0, 6)}`}
                disabled={busy !== ""}
                onClick={() => void act(selected.id, "mitigate")}
              >
                Mitigar
              </Button>
              <Button variant="primary" disabled={busy !== ""} onClick={() => setConfirmAccept(true)}>
                Aceptar riesgo
              </Button>
            </>
          )
        }
      >
        {selected && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={selected.severity} />
              <RiskStatusBadge status={selected.status} />
              <Badge tone="neutral">Score {selected.score}</Badge>
              <Badge tone="neutral">{selected.source}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Agente", value: selected.agent_name ?? "General" },
                { key: "Tipo", value: selected.risk_type, mono: true },
                { key: "Probabilidad", value: String(selected.likelihood) },
                { key: "Impacto", value: String(selected.impact) },
                { key: "Mitigaciones", value: String(selected.mitigations) },
                { key: "Creado", value: fmtDateTime(selected.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Evidencia</p>
              <CodeBlock code={JSON.stringify(selected.evidence, null, 2)} language="json" maxHeight={240} />
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmAccept}
        onOpenChange={setConfirmAccept}
        title="Aceptar riesgo"
        body="El riesgo queda aceptado en el registro con la razón del equipo. La decisión se firma en la auditoría y no se puede revertir desde acá."
        confirmLabel="Aceptar riesgo"
        onConfirm={() => {
          if (selected) void act(selected.id, "accept");
          setConfirmAccept(false);
        }}
      />
    </div>
  );
}
