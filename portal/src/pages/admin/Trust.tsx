import {
  ArrowRight,
  ShieldCheck,
  ShieldWarning,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { AttentionList } from "../../components/AttentionList";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
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

const SEV: Record<string, string> = { low: "badge-muted", medium: "badge-warning", high: "badge-danger", critical: "badge-danger" };

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
    <div className="space-y-6">
      <PageHeader
        title="Trust Center"
        subtitle="Postura de seguridad, riesgo de IA, compliance y auditoría en una sola vista. Datos reales de los módulos."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/control-center/security-center" className="btn btn-secondary min-h-11">Security Center</Link>
            <Link to="/control-center/risk-center" className="btn btn-secondary min-h-11">AI Risk</Link>
            <Link to="/control-center/compliance" className="btn btn-secondary min-h-11">Compliance</Link>
            <Link to="/control-center/audit-intel" className="btn btn-secondary min-h-11">Audit Intelligence</Link>
          </div>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatCard label="Security posture" value={avgPosture != null ? `${avgPosture}%` : "—"} icon={ShieldCheck} tone={avgPosture != null && avgPosture < 70 ? "warn" : "ok"} />
            <StatCard label="Riesgos abiertos" value={risk?.open_risks ?? 0} icon={WarningCircle} tone={(risk?.open_risks ?? 0) > 0 ? "warn" : "default"} />
            <StatCard label="Compliance" value={avgCompliance != null ? `${avgCompliance}%` : "—"} icon={ShieldCheck} />
            <StatCard label="Eventos SOC 7d" value={soc?.events_7d ?? 0} icon={ShieldWarning} />
            <StatCard label="SOC abiertos" value={soc?.open_events ?? 0} icon={WarningCircle} tone={(soc?.open_events ?? 0) > 0 ? "danger" : "default"} />
            <StatCard label="Anomalías" value={openAnomalies} icon={WarningCircle} tone={openAnomalies > 0 ? "warn" : "default"} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <AttentionList
                items={issues}
                emptyTitle="Postura sólida"
                emptyBody="Sin riesgos abiertos, anomalías pendientes ni frameworks en fail."
              />
            </div>

            <div className="panel">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Compliance por framework</h2>
              </div>
              <div className="space-y-2 p-4">
                {frameworks.length === 0 && <p className="text-xs text-faint">Sin snapshots de compliance.</p>}
                {frameworks.map((f) => (
                  <div key={f.framework} className="flex items-center gap-2">
                    <span className="w-24 shrink-0 text-xs text-text">{f.framework.toUpperCase()}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-soft">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${f.score}%` }} />
                    </div>
                    <span className="w-10 shrink-0 text-right text-xs text-faint">{f.score}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldWarning size={15} /> Eventos SOC por tipo</h3>
              <div className="panel space-y-1 p-3">
                {(soc?.by_type ?? []).map((t) => (
                  <div key={t.event_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{t.event_type}</span>
                    <span className="text-faint">{t.count} · {t.criticals} críticos</span>
                  </div>
                ))}
                {(soc?.by_type ?? []).length === 0 && <p className="text-xs text-faint">Sin eventos.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><WarningCircle size={15} /> Riesgos por severidad</h3>
              <div className="panel flex flex-wrap gap-1 p-3">
                {(risk?.by_severity ?? []).map((s) => (
                  <span key={s.severity} className={`badge ${SEV[s.severity] ?? "badge-muted"}`}>{s.severity} · {s.count}</span>
                ))}
                {(risk?.by_severity ?? []).length === 0 && <p className="text-xs text-faint">Sin riesgos.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center justify-between gap-2 text-sm font-semibold text-text">
                <span className="flex items-center gap-2"><WarningCircle size={15} /> Anomalías recientes</span>
                <Link to="/control-center/audit-intel" className="flex items-center gap-1 text-xs text-accent hover:underline">
                  Ver <ArrowRight size={12} aria-hidden />
                </Link>
              </h3>
              <div className="panel space-y-1 p-3">
                {anomalies.slice(0, 5).map((a) => (
                  <div key={a.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className={`badge ${SEV[a.severity] ?? "badge-muted"}`}>{a.severity}</span>
                    <span className="min-w-0 flex-1 truncate text-text" title={a.message}>{a.message || a.anomaly_type}</span>
                  </div>
                ))}
                {anomalies.length === 0 && <p className="text-xs text-faint">Sin anomalías.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}