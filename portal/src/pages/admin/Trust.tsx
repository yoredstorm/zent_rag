import {
  ArrowRight,
  CheckCircle,
  Clock,
  Info,
  Minus,
  Prohibit,
  Question,
  ShieldCheck,
  ShieldWarning,
  WarningCircle,
  WarningOctagon,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { AttentionList } from "../../components/AttentionList";
import {
  Badge,
  ButtonLink,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  SkeletonBlock,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type SocDash = {
  events_7d: number;
  open_events: number;
  resolved_7d: number;
  avg_threat_score: number;
  by_type: { event_type: string; count: number; criticals: number }[];
  by_severity: { severity: string; count: number }[];
  top_organizations: { org: string; events: number; total_score: number }[];
};

type RiskDash = {
  open_risks: number;
  mitigated_7d: number;
  by_risk_type: { risk_type: string; count: number; avg_score: number }[];
  by_severity: { severity: string; count: number }[];
  posture_by_framework: { framework: string; avg_score: number; organizations: number }[];
  top_organizations: { org: string; open_risks: number; total_score: number }[];
};

type Framework = { framework: string; pass: number; fail: number; review: number; na: number; score: number; controls: number };

type PostureOrg = { organization_id: string; score: number };

type Anomaly = {
  id: string;
  organization_id: string | null;
  anomaly_type: string;
  severity: string;
  message: string;
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

/** Estado de una anomalía de auditoría. */
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

export default function AdminTrustPage() {
  const { session } = usePlatformAuth();
  const [soc, setSoc] = useState<SocDash | null>(null);
  const [risk, setRisk] = useState<RiskDash | null>(null);
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [posture, setPosture] = useState<PostureOrg[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, r, f, p, a] = await Promise.all([
        platformApi<SocDash>("/api/v1/platform/soc/dashboard", { token: session.token }).catch(() => null),
        platformApi<RiskDash>("/api/v1/platform/risk-center/dashboard", { token: session.token }).catch(() => null),
        platformApi<{ frameworks: Framework[] }>("/api/v1/platform/compliance/dashboard", { token: session.token }).catch(() => ({ frameworks: [] })),
        platformApi<{ organizations: PostureOrg[] }>("/api/v1/platform/security/posture", { token: session.token }).catch(() => ({ organizations: [] })),
        platformApi<{ anomalies: Anomaly[] }>("/api/v1/platform/audit-intelligence/anomalies", { token: session.token }).catch(() => ({ anomalies: [] })),
      ]);
      setSoc(s);
      setRisk(r);
      setFrameworks(f.frameworks || []);
      setPosture(p.organizations || []);
      setAnomalies(a.anomalies || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const scored = posture.filter((o) => o.score > 0);
  const avgPosture = scored.length ? Math.round(scored.reduce((n, o) => n + o.score, 0) / scored.length) : null;
  const weakPosture = posture.filter((o) => o.score > 0 && o.score < 70).length;
  const compScores = frameworks.map((f) => f.score);
  const avgCompliance = compScores.length ? Math.round(compScores.reduce((a, b) => a + b, 0) / compScores.length) : null;
  const openAnomalies = anomalies.filter((a) => a.status !== "resolved" && a.status !== "dismissed").length;
  const failingFrameworks = frameworks.filter((f) => f.fail > 0).length;

  const issues: { id: string; label: string; to: string }[] = [];
  if (weakPosture > 0) {
    issues.push({
      id: "posture",
      label: `${weakPosture} organización(es) con security posture < 70.`,
      to: "/control-center/security-center",
    });
  }
  if ((soc?.open_events ?? 0) > 0) {
    issues.push({
      id: "soc",
      label: `${soc?.open_events} eventos SOC sin resolver.`,
      to: "/control-center/security-center",
    });
  }
  if (failingFrameworks > 0) {
    issues.push({
      id: "compliance",
      label: `${failingFrameworks} framework(s) con controles en fail.`,
      to: "/control-center/compliance",
    });
  }
  if (openAnomalies > 0) {
    issues.push({
      id: "anomalies",
      label: `${openAnomalies} anomalías de auditoría sin revisar.`,
      to: "/control-center/audit-intel",
    });
  }
  if ((risk?.open_risks ?? 0) > 0) {
    issues.push({
      id: "risk",
      label: `${risk?.open_risks} riesgos de IA abiertos.`,
      to: "/control-center/risk-center",
    });
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trust Center"
        subtitle="Postura de seguridad, riesgo de IA, compliance y auditoría en una sola vista. Datos reales de los módulos."
        actions={
          <>
            <ButtonLink to="/control-center/security-center" variant="secondary" size="sm">
              Security Center
            </ButtonLink>
            <ButtonLink to="/control-center/risk-center" variant="secondary" size="sm">
              AI Risk
            </ButtonLink>
            <ButtonLink to="/control-center/compliance" variant="secondary" size="sm">
              Compliance
            </ButtonLink>
            <ButtonLink to="/control-center/audit-intel" variant="secondary" size="sm">
              Audit Intelligence
            </ButtonLink>
          </>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <div className="space-y-4">
          <SkeletonBlock rows={4} />
          <SkeletonBlock rows={6} />
        </div>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-3 xl:items-start">
            <Panel className="xl:col-span-2">
              <PanelHeader
                title="Postura de confianza"
                description="Promedio real de security posture y compliance entre las organizaciones."
                actions={
                  avgPosture != null && avgPosture < 70 ? (
                    <Badge tone="warn" icon={WarningCircle}>
                      Requiere atención
                    </Badge>
                  ) : (
                    <Badge tone="ok" icon={CheckCircle}>
                      Sobre el umbral
                    </Badge>
                  )
                }
              />
              <div className="panel-body">
                <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
                  <div className="min-w-40">
                    <p className="eyebrow">Security posture</p>
                    <p className="mt-1 text-display tabular-nums">
                      {avgPosture != null ? `${avgPosture}%` : "—"}
                    </p>
                    <p className="mt-1.5 text-xs leading-relaxed text-muted">
                      {posture.length === 0
                        ? "Sin snapshots de posture todavía."
                        : weakPosture > 0
                          ? `${weakPosture} de ${scored.length} organizaciones por debajo de 70.`
                          : `${scored.length} organizaciones en seguimiento, ninguna por debajo de 70.`}
                    </p>
                  </div>
                  <div className="min-w-48 flex-1">
                    <p className="eyebrow">Compliance</p>
                    <p className="mt-1 text-h2 tabular-nums">
                      {avgCompliance != null ? `${avgCompliance}%` : "—"}
                    </p>
                    <p className="mt-1.5 text-xs leading-relaxed text-muted">
                      {frameworks.length === 0
                        ? "Sin snapshots de compliance."
                        : `${frameworks.length} frameworks evaluados${failingFrameworks > 0 ? ` · ${failingFrameworks} con controles en fail` : ""}.`}
                    </p>
                  </div>
                  <div className="min-w-32">
                    <p className="eyebrow">Eventos SOC 7d</p>
                    <p className="mt-1 text-h2 tabular-nums">{soc?.events_7d ?? 0}</p>
                    <p className="mt-1.5 text-xs leading-relaxed text-muted">
                      {soc?.open_events ?? 0} abiertos · {soc?.resolved_7d ?? 0} resueltos
                    </p>
                  </div>
                </div>
              </div>
            </Panel>

            <AttentionList
              items={issues}
              emptyTitle="Postura sólida"
              emptyBody="Sin riesgos abiertos, anomalías pendientes ni frameworks en fail."
            />
          </div>

          <MetricGrid cols={4}>
            <Metric
              label="Riesgos de IA abiertos"
              value={risk?.open_risks ?? 0}
              size="md"
              tone={(risk?.open_risks ?? 0) > 0 ? "warn" : "default"}
              icon={WarningCircle}
              hint={`${risk?.mitigated_7d ?? 0} mitigados en 7d`}
            />
            <Metric label="Eventos SOC 7d" value={soc?.events_7d ?? 0} size="md" icon={ShieldWarning} hint={`Threat score medio ${soc?.avg_threat_score ?? 0}`} />
            <Metric
              label="SOC abiertos"
              value={soc?.open_events ?? 0}
              size="md"
              tone={(soc?.open_events ?? 0) > 0 ? "danger" : "default"}
              icon={WarningCircle}
              hint={`${soc?.resolved_7d ?? 0} resueltos en 7d`}
            />
            <Metric
              label="Anomalías sin revisar"
              value={openAnomalies}
              size="md"
              tone={openAnomalies > 0 ? "warn" : "default"}
              icon={ShieldWarning}
              hint={`${anomalies.length} detectadas en total`}
            />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title="Compliance por framework"
              description="Score real por framework evaluado; el detalle de controles vive en Compliance."
              actions={
                <ButtonLink to="/control-center/compliance" variant="ghost" size="sm" trailingIcon={ArrowRight}>
                  Ver detalle
                </ButtonLink>
              }
            />
            <div className="panel-body flex flex-col gap-4">
              {frameworks.length === 0 ? (
                <p className="text-[13px] leading-relaxed text-muted">Sin snapshots de compliance.</p>
              ) : (
                frameworks.map((f) => (
                  <Progress
                    key={f.framework}
                    label={f.framework.toUpperCase()}
                    showValue
                    value={f.score}
                  />
                ))
              )}
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <ShieldWarning size={15} className="text-faint" aria-hidden />
                    Eventos SOC por tipo
                  </span>
                }
              />
              <ul className="divide-y divide-border-soft">
                {(soc?.by_type ?? []).map((t) => (
                  <li key={t.event_type} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="mono min-w-0 truncate text-xs text-text" title={t.event_type}>
                      {t.event_type}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {t.count} · {t.criticals} críticos
                    </span>
                  </li>
                ))}
                {(soc?.by_type ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin eventos.</li>
                )}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <WarningCircle size={15} className="text-faint" aria-hidden />
                    Riesgos por severidad
                  </span>
                }
              />
              <div className="panel-body">
                {(risk?.by_severity ?? []).length === 0 ? (
                  <p className="text-[13px] text-muted">Sin riesgos.</p>
                ) : (
                  <ul className="flex flex-col gap-2.5">
                    {(risk?.by_severity ?? []).map((s) => (
                      <li key={s.severity} className="flex items-center justify-between gap-3">
                        <SeverityBadge severity={s.severity} />
                        <span className="mono text-xs text-faint tabular-nums">{s.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <ShieldCheck size={15} className="text-faint" aria-hidden />
                    Anomalías recientes
                  </span>
                }
                actions={
                  <Link
                    to="/control-center/audit-intel"
                    className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                  >
                    Ver todas <ArrowRight size={12} aria-hidden />
                  </Link>
                }
              />
              <ul className="divide-y divide-border-soft">
                {anomalies.slice(0, 5).map((a) => (
                  <li key={a.id} className="flex items-center gap-2.5 px-4 py-2.5">
                    <SeverityBadge severity={a.severity} />
                    <span className="min-w-0 flex-1 truncate text-xs text-text" title={a.message}>
                      {a.message || a.anomaly_type}
                    </span>
                    <AnomalyStatusBadge status={a.status} />
                  </li>
                ))}
                {anomalies.length === 0 && <li className="px-4 py-3 text-[13px] text-muted">Sin anomalías.</li>}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
