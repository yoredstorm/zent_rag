import {
  Info,
  Minus,
  Question,
  ShieldCheck,
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

type Dash = { events_7d: number; open_events: number; resolved_7d: number; avg_threat_score: number; by_type: { event_type: string; count: number; criticals: number }[]; by_severity: { severity: string; count: number }[]; responses: { action_type: string; count: number }[]; top_organizations: { org: string; events: number; total_score: number }[] };

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

export default function AdminSecurityCenterPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/soc/dashboard", { token: session.token });
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

  const responses7d = (dash?.responses ?? []).reduce((n, r) => n + r.count, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Security Operations Center"
        subtitle="Amenazas en todas las organizaciones: detección, severidad y respuestas automáticas."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid className="xl:grid-cols-5">
            <Metric label="Eventos 7d" value={dash?.events_7d ?? 0} hint={`${dash?.resolved_7d ?? 0} resueltos`} />
            <Metric
              label="Abiertos"
              value={dash?.open_events ?? 0}
              size="md"
              tone={(dash?.open_events ?? 0) > 0 ? "warn" : "default"}
              icon={WarningCircle}
              hint="Eventos sin resolver"
            />
            <Metric label="Resueltos 7d" value={dash?.resolved_7d ?? 0} size="md" icon={ShieldCheck} />
            <Metric label="Threat score medio" value={dash?.avg_threat_score ?? 0} size="md" hint="Promedio de la ventana" />
            <Metric label="Respuestas 7d" value={responses7d} size="md" hint={`${(dash?.responses ?? []).length} tipos de acción`} />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="flex flex-col gap-4">
              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldWarning size={15} className="text-faint" aria-hidden />
                      Por tipo
                    </span>
                  }
                  description="Eventos y críticos detectados en la ventana."
                />
                <ul className="divide-y divide-border-soft">
                  {(dash?.by_type ?? []).map((t) => (
                    <li key={t.event_type} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <span className="mono min-w-0 truncate text-xs text-text" title={t.event_type}>
                        {t.event_type}
                      </span>
                      <span className="shrink-0 text-xs text-faint tabular-nums">
                        {t.count} · {t.criticals} críticos
                      </span>
                    </li>
                  ))}
                  {(dash?.by_type ?? []).length === 0 && (
                    <li className="px-4 py-3 text-[13px] text-muted">Sin eventos.</li>
                  )}
                </ul>
              </Panel>

              <Panel>
                <PanelHeader title="Por severidad" />
                <div className="panel-body">
                  {(dash?.by_severity ?? []).length === 0 ? (
                    <p className="text-[13px] text-muted">Sin eventos.</p>
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
              <PanelHeader title="Respuestas automáticas" description="Acciones ejecutadas por el SOC en la ventana." />
              <ul className="divide-y divide-border-soft">
                {(dash?.responses ?? []).map((r) => (
                  <li key={r.action_type} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="mono min-w-0 truncate text-xs text-text" title={r.action_type}>
                      {r.action_type}
                    </span>
                    <span className="mono shrink-0 text-xs text-faint tabular-nums">{r.count}</span>
                  </li>
                ))}
                {(dash?.responses ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin respuestas.</li>
                )}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <WarningCircle size={15} className="text-faint" aria-hidden />
                    Top organizaciones
                  </span>
                }
                description="Ordenado por eventos y score acumulado."
              />
              <ul className="divide-y divide-border-soft">
                {(dash?.top_organizations ?? []).map((o) => (
                  <li key={o.org} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1 truncate text-xs text-text" title={o.org}>
                      {o.org}
                    </span>
                    <span className="shrink-0 text-xs text-faint tabular-nums">
                      {o.events} eventos · {o.total_score}
                    </span>
                  </li>
                ))}
                {(dash?.top_organizations ?? []).length === 0 && (
                  <li className="px-4 py-3 text-[13px] text-muted">Sin actividad.</li>
                )}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
