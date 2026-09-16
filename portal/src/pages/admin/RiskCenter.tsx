import {
  Info,
  Minus,
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
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { open_risks: number; mitigated_7d: number; by_risk_type: { risk_type: string; count: number; avg_score: number }[]; by_severity: { severity: string; count: number }[]; posture_by_framework: { framework: string; avg_score: number; organizations: number }[]; top_organizations: { org: string; open_risks: number; total_score: number }[] };

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

export default function AdminRiskCenterPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/risk-center/dashboard", { token: session.token });
      setDash(d);
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

  return (
    <div className="space-y-4">
      <PageHeader
        title="Risk & Compliance"
        subtitle="Riesgos de IA en todas las organizaciones: scoring automático, postura por framework y mitigaciones."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid cols={4}>
            <Metric
              label="Riesgos abiertos"
              value={dash?.open_risks ?? 0}
              tone={(dash?.open_risks ?? 0) > 0 ? "warn" : "default"}
              icon={WarningCircle}
              hint="En todas las organizaciones"
            />
            <Metric label="Mitigados 7d" value={dash?.mitigated_7d ?? 0} size="md" hint="Cierres registrados" />
            <Metric label="Frameworks con postura" value={(dash?.posture_by_framework ?? []).length} size="md" />
            <Metric label="Orgs en top riesgo" value={(dash?.top_organizations ?? []).length} size="md" hint="Orden por score acumulado" />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="flex flex-col gap-4">
              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldWarning size={15} className="text-faint" aria-hidden />
                      Riesgos por tipo
                    </span>
                  }
                />
                <ul className="divide-y divide-border-soft">
                  {(dash?.by_risk_type ?? []).map((r) => (
                    <li key={r.risk_type} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <span className="mono min-w-0 truncate text-xs text-text" title={r.risk_type}>
                        {r.risk_type}
                      </span>
                      <span className="shrink-0 text-xs text-faint tabular-nums">
                        {r.count} · score {r.avg_score}
                      </span>
                    </li>
                  ))}
                  {(dash?.by_risk_type ?? []).length === 0 && (
                    <li className="px-4 py-3 text-[13px] text-muted">Sin riesgos.</li>
                  )}
                </ul>
              </Panel>

              <Panel>
                <PanelHeader title="Por severidad" />
                <div className="panel-body">
                  {(dash?.by_severity ?? []).length === 0 ? (
                    <p className="text-[13px] text-muted">Sin riesgos.</p>
                  ) : (
                    <ul className="flex flex-col gap-2.5">
                      {(dash?.by_severity ?? []).map((s) => (
                        <li key={s.severity} className="flex items-center justify-between gap-3">
                          <SeverityBadge severity={s.severity} />
                          <span className="mono text-xs text-faint tabular-nums">{s.count}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Panel>
            </div>

            <Panel>
              <PanelHeader title="Postura por framework" description="Score promedio y alcance por framework evaluado." />
              <ul className="divide-y divide-border-soft">
                {(dash?.posture_by_framework ?? []).map((p) => (
                  <li key={p.framework} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0 truncate text-xs text-text" title={p.framework}>
                      {p.framework}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {p.avg_score}% · {p.organizations} orgs
                    </span>
                  </li>
                ))}
                {(dash?.posture_by_framework ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin snapshots aún.</li>
                )}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <WarningCircle size={15} className="text-faint" aria-hidden />
                    Top organizaciones en riesgo
                  </span>
                }
              />
              <ul className="divide-y divide-border-soft">
                {(dash?.top_organizations ?? []).map((o) => (
                  <li key={o.org} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1 truncate text-xs text-text" title={o.org}>
                      {o.org}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {o.open_risks} riesgos · {o.total_score}
                    </span>
                  </li>
                ))}
                {(dash?.top_organizations ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin riesgos registrados.</li>
                )}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
