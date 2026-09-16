import {
  CheckCircle,
  Clock,
  Fingerprint,
  Info,
  Minus,
  Prohibit,
  Question,
  ShieldWarning,
  WarningCircle,
  WarningOctagon,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  SkeletonBlock,
  SuccessInline,
  Textarea,
  type Column,
  type Tone,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Summary = {
  organization_id: string;
  total_events: number;
  top_actions: { action: string; count: number }[];
  top_users: { user_id: string; count: number }[];
  timeline_30d: { date: string; count: number }[];
};

type Anomaly = {
  id: string;
  organization_id: string | null;
  anomaly_type: string;
  severity: string;
  message: string;
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
};

/**
 * Escala única de severidad del bloque de seguridad y riesgo
 * (crítica → alta → media → baja). Mismos valores que SecurityCenter y RiskCenter.
 */
const SEVERITY_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  critical: { label: "Crítica", tone: "danger", icon: WarningOctagon },
  high: { label: "Alta", tone: "warn", icon: WarningCircle },
  medium: { label: "Media", tone: "info", icon: Info },
  low: { label: "Baja", tone: "neutral", icon: Minus },
  info: { label: "Informativa", tone: "neutral", icon: Info },
};

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

const ANOMALY_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  open: { label: "Abierta", tone: "warn", icon: Clock },
  resolved: { label: "Resuelta", tone: "ok", icon: CheckCircle },
  dismissed: { label: "Desestimada", tone: "neutral", icon: Prohibit },
};

function AnomalyStatusBadge({ status }: { status: string }) {
  const meta = ANOMALY_STATUS_META[status] ?? {
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

export default function AdminAuditIntelligencePage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [piiResult, setPiiResult] = useState<{ detected: Record<string, number>; masked: string } | null>(null);
  const [piiInput, setPiiInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Anomaly | null>(null);
  const [orgId] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, a] = await Promise.all([
        platformApi<Summary>(`/api/v1/platform/audit-intelligence/summary?organization_id=${orgId}`, {
          token: session.token,
        }),
        platformApi<{ anomalies: Anomaly[] }>(
          `/api/v1/platform/audit-intelligence/anomalies?organization_id=${orgId}`,
          { token: session.token }
        ),
      ]);
      setSummary(s);
      setAnomalies(a.anomalies || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function runChecks() {
    if (!session) return;
    setBusy("check");
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ count: number }>(
        `/api/v1/platform/audit-intelligence/check?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setNotice(
        out.count > 0
          ? `Detección completa: ${out.count} anomalías nuevas.`
          : "Detección completa: sin anomalías nuevas."
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolve(anomalyId: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/audit-intelligence/anomalies/${anomalyId}/resolve`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function scanPii() {
    if (!session) return;
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ masked: string; detected: Record<string, number> }>(
        "/api/v1/platform/ai-governance/pii/mask",
        { method: "POST", token: session.token, body: JSON.stringify({ text: piiInput }) }
      );
      setPiiResult({ detected: out.detected, masked: out.masked });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const maxTimeline = Math.max(1, ...(summary?.timeline_30d ?? []).map((t) => t.count));
  const openAnomalies = anomalies.filter((a) => a.status === "open").length;
  const timelineTotal = (summary?.timeline_30d ?? []).reduce((n, t) => n + t.count, 0);

  const columns: Column<Anomaly>[] = [
    {
      key: "severity",
      header: "Severidad",
      render: (a) => <SeverityBadge severity={a.severity} />,
    },
    {
      key: "message",
      header: "Hallazgo",
      render: (a) => (
        <span className="block max-w-96 truncate text-[13px] text-text" title={a.message}>
          {a.message || a.anomaly_type}
        </span>
      ),
    },
    {
      key: "anomaly_type",
      header: "Tipo",
      hideBelow: "lg",
      render: (a) => <span className="mono text-xs text-muted">{a.anomaly_type}</span>,
    },
    {
      key: "organization_id",
      header: "Alcance",
      hideBelow: "xl",
      render: (a) =>
        a.organization_id ? (
          <span className="mono text-xs text-muted" title={a.organization_id}>
            {a.organization_id.slice(0, 8)}
          </span>
        ) : (
          <span className="text-xs text-faint">platform</span>
        ),
    },
    {
      key: "created_at",
      header: "Detectada",
      hideBelow: "md",
      render: (a) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(a.created_at)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (a) => <AnomalyStatusBadge status={a.status} />,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit Intelligence"
        subtitle="Resumen de auditoría, detección de anomalías y gobernanza de IA."
        actions={
          <Button
            variant="primary"
            leadingIcon={ShieldWarning}
            loading={busy === "check"}
            disabled={busy !== ""}
            onClick={() => void runChecks()}
          >
            Detectar anomalías
          </Button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid cols={3}>
            <Metric label="Eventos de auditoría" value={summary?.total_events ?? 0} hint={`${timelineTotal} en los últimos 30d`} />
            <Metric
              label="Anomalías abiertas"
              value={openAnomalies}
              size="md"
              tone={openAnomalies > 0 ? "warn" : "default"}
              icon={WarningCircle}
              hint={`${anomalies.length} detectadas en total`}
            />
            <Metric label="Top acción" value={summary?.top_actions?.[0]?.action ?? "—"} size="md" hint={summary?.top_actions?.[0] ? `${summary.top_actions[0].count} eventos` : undefined} />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
            <Panel>
              <PanelHeader title="Timeline 30d" description="Eventos de auditoría por día." />
              <div className="panel-body">
                {!summary?.timeline_30d.length ? (
                  <p className="text-[13px] text-muted">Sin eventos recientes.</p>
                ) : (
                  <div className="flex h-24 items-end gap-1">
                    {summary.timeline_30d.map((t) => (
                      <div
                        key={t.date}
                        className="flex-1 rounded-t-xs bg-accent/60"
                        style={{ height: `${Math.max(3, (t.count / maxTimeline) * 88)}px` }}
                        title={`${t.date}: ${t.count}`}
                      />
                    ))}
                  </div>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Top acciones" description="Acciones con más eventos en el resumen." />
              <ul className="divide-y divide-border-soft">
                {(summary?.top_actions ?? []).map((a) => (
                  <li key={a.action} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="mono min-w-0 truncate text-xs text-text" title={a.action}>
                      {a.action}
                    </span>
                    <span className="mono shrink-0 text-xs text-faint tabular-nums">{a.count}</span>
                  </li>
                ))}
                {(summary?.top_actions ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin acciones registradas.</li>
                )}
              </ul>
            </Panel>
          </div>

          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-h2">Anomalías</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  Hallazgos detectados sobre logins, errores y actividad. Seleccioná una fila para ver la evidencia.
                </p>
              </div>
            </div>
            <DataTable
              columns={columns}
              rows={anomalies}
              rowKey={(a) => a.id}
              caption="Anomalías de auditoría"
              stickyHeader
              onRowClick={(a) => setSelected(a)}
              empty={
                <EmptyState
                  icon={ShieldWarning}
                  title="Sin anomalías"
                  body="La detección no encontró desvíos en logins, errores ni actividad."
                  hint="Ejecutá «Detectar anomalías» para escanear la ventana actual."
                />
              }
              rowActions={(a) =>
                a.status !== "resolved" ? (
                  <Button variant="ghost" size="sm" onClick={() => void resolve(a.id)}>
                    Resolver
                  </Button>
                ) : null
              }
              footer={anomalies.length > 0 ? <ResultCount shown={anomalies.length} total={anomalies.length} noun="anomalías" /> : undefined}
            />
          </section>

          <Panel>
            <PanelHeader
              title={
                <span className="flex items-center gap-2">
                  <Fingerprint size={15} className="text-faint" aria-hidden />
                  PII masking (test)
                </span>
              }
              description="Prueba de enmascaramiento sobre un texto pegado. No persiste el contenido."
            />
            <div className="panel-body flex flex-col gap-3">
              <Field label="Texto a analizar">
                <Textarea
                  rows={4}
                  placeholder="Pega un texto con emails, teléfonos, DNIs…"
                  value={piiInput}
                  onChange={(e) => setPiiInput(e.target.value)}
                />
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  variant="secondary"
                  leadingIcon={Fingerprint}
                  disabled={!piiInput.trim()}
                  onClick={() => void scanPii()}
                >
                  Enmascarar
                </Button>
                {piiResult && Object.keys(piiResult.detected).length > 0 && (
                  <span className="flex flex-wrap items-center gap-1.5">
                    {Object.entries(piiResult.detected).map(([kind, count]) => (
                      <Badge key={kind} tone="warn">
                        {kind} · {count}
                      </Badge>
                    ))}
                  </span>
                )}
              </div>
              {piiResult && (
                <div>
                  <p className="eyebrow mb-2">Salida enmascarada</p>
                  <CodeBlock code={piiResult.masked} language="text" maxHeight={200} />
                </div>
              )}
            </div>
          </Panel>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Evidencia de la anomalía"
        description={selected ? selected.anomaly_type : undefined}
        width={520}
        footer={
          selected && selected.status !== "resolved" ? (
            <Button variant="primary" onClick={() => void resolve(selected.id)}>
              Resolver anomalía
            </Button>
          ) : undefined
        }
      >
        {selected && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={selected.severity} />
              <AnomalyStatusBadge status={selected.status} />
              {selected.organization_id ? (
                <Badge tone="neutral">{selected.organization_id.slice(0, 8)}</Badge>
              ) : (
                <Badge tone="neutral">platform</Badge>
              )}
            </div>
            <p className="text-[13px] leading-relaxed text-text">{selected.message || "Sin mensaje del detector."}</p>
            <KeyValue
              columns={2}
              items={[
                { key: "Tipo", value: selected.anomaly_type, mono: true },
                { key: "Detectada", value: fmtDateTime(selected.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Metadata</p>
              {Object.keys(selected.metadata ?? {}).length === 0 ? (
                <p className="text-[13px] text-muted">El detector no registró metadata adicional.</p>
              ) : (
                <CodeBlock code={JSON.stringify(selected.metadata, null, 2)} language="json" maxHeight={280} />
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
