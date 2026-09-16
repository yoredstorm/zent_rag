import { CheckCircle, Lifebuoy, ShieldCheck } from "@phosphor-icons/react";
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
  Progress,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { policies_total: number; policies_active: number; organizations_covered: number; drills_30d: number; drill_success_rate: number; backups_total: number; restores_30d: number; drills_by_region: { region: string; count: number; success: number }[] };

export default function AdminDisasterRecoveryPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/dr/dashboard", { token: session.token });
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

  const inactive = Math.max(0, (dash?.policies_total ?? 0) - (dash?.policies_active ?? 0));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Disaster Recovery"
        subtitle="Continuidad en todas las organizaciones: políticas, drills de failover y backups. Resultados reales del período."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MetricGrid className="xl:grid-cols-5">
            <Metric
              label="Políticas"
              value={dash?.policies_total ?? 0}
              hint={inactive > 0 ? `${inactive} sin activar` : "Todas activas"}
            />
            <Metric label="Activas" value={dash?.policies_active ?? 0} size="md" tone={(dash?.policies_active ?? 0) > 0 ? "ok" : "default"} icon={ShieldCheck} />
            <Metric label="Orgs cubiertas" value={dash?.organizations_covered ?? 0} size="md" hint="Con política vigente" />
            <Metric
              label="Drills 30d"
              value={dash?.drills_30d ?? 0}
              size="md"
              hint={`${dash?.drill_success_rate ?? 0}% de éxito reportado`}
            />
            <Metric
              label="Backups"
              value={dash?.backups_total ?? 0}
              size="md"
              hint={`${dash?.restores_30d ?? 0} restores en 30d`}
            />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title={
                <span className="flex items-center gap-2">
                  <Lifebuoy size={15} className="text-faint" aria-hidden />
                  Drills por región
                </span>
              }
              description="Ejecutados y exitosos según el registro de cada región."
            />
            {(dash?.drills_by_region ?? []).length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-muted">Sin drills aún.</p>
            ) : (
              <div className="panel-body flex flex-col gap-4">
                {(dash?.drills_by_region ?? []).map((r) => {
                  const allOk = r.count > 0 && r.success === r.count;
                  return (
                    <div key={r.region} className="flex flex-wrap items-center gap-3">
                      <span className="mono w-24 shrink-0 text-xs text-text" title={r.region}>
                        {r.region}
                      </span>
                      <div className="min-w-40 flex-1">
                        <Progress
                          value={r.success}
                          max={Math.max(1, r.count)}
                          label={`Drills en ${r.region}`}
                        />
                      </div>
                      <Badge tone={r.count === 0 ? "neutral" : allOk ? "ok" : "warn"} icon={allOk ? CheckCircle : undefined}>
                        {r.success}/{r.count} exitosos
                      </Badge>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
