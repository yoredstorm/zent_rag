import { Lightbulb, Rocket, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  SectionHeader,
  SkeletonTable,
  SuccessInline,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Profile = {
  agent_id: string | null;
  agent_name: string;
  requests: number;
  error_rate_pct: number;
  p50_ms: number;
  p95_ms: number;
  tokens_per_request: number;
  cost_per_request: number;
  embedding_share_pct: number;
  sources_per_request: number;
};

type Recommendation = {
  id: string;
  organization_id: string;
  agent_id: string | null;
  recommendation_key: string;
  severity: string;
  message: string;
  expected_savings_pct: number | null;
  status: string;
  details: Record<string, unknown>;
  created_at: string;
  applied_at: string | null;
};

const SEVERITY_META: Record<string, { tone: Tone; label: string }> = {
  important: { tone: "danger", label: "Importante" },
  optimization: { tone: "warn", label: "Optimización" },
  info: { tone: "neutral", label: "Informativa" },
};

const STATUS_META: Record<string, { tone: Tone; label: string }> = {
  suggested: { tone: "accent", label: "Sugerida" },
  applied: { tone: "ok", label: "Aplicada" },
  ignored: { tone: "neutral", label: "Ignorada" },
  dismissed: { tone: "neutral", label: "Descartada" },
};

const RAIL_STATE: Record<string, "queued" | "running" | "ready" | "warning" | "failed"> = {
  suggested: "warning",
  applied: "ready",
  ignored: "queued",
  dismissed: "queued",
};

export default function AdminOptimizerPage() {
  const { session } = usePlatformAuth();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [detail, setDetail] = useState<Recommendation | null>(null);
  const [confirm, setConfirm] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [orgId] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, r] = await Promise.all([
        platformApi<{ profiles: Profile[] }>(
          `/api/v1/platform/optimizer/profiles?organization_id=${orgId}`,
          { token: session.token }
        ),
        platformApi<{ recommendations: Recommendation[] }>(
          `/api/v1/platform/optimizer/recommendations?organization_id=${orgId}`,
          { token: session.token }
        ),
      ]);
      setProfiles(p.profiles || []);
      setRecommendations(r.recommendations || []);
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

  async function scan() {
    if (!session) return;
    setBusy("scan");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ count: number }>(
        `/api/v1/platform/optimizer/scan?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setNote(`${out.count} recomendaciones creadas.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(recId: string, action: "apply" | "ignore") {
    if (!session) return;
    setBusy(recId);
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/optimizer/recommendations/${recId}/${action}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setNote(`Recomendación ${action === "apply" ? "aplicada" : "ignorada"}: ${out.status}.`);
      setConfirm(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const suggested = recommendations.filter((r) => r.status === "suggested");
  const bestSavings = suggested.reduce(
    (max, r) => (r.expected_savings_pct != null && r.expected_savings_pct > max ? r.expected_savings_pct : max),
    0
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Optimizer"
        subtitle="Perfiles de costo/desempeño y recomendaciones accionables por agente."
        actions={
          <Button variant="primary" leadingIcon={Rocket} loading={busy === "scan"} onClick={() => void scan()}>
            Escanear
          </Button>
        }
      />
      <ErrorInline message={error} />
      {note && <SuccessInline>{note}</SuccessInline>}
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={5} cols={4} />
        </Panel>
      ) : (
        <>
          <Panel className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Recomendaciones sugeridas</p>
                <p
                  className={`mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums ${
                    suggested.length > 0 ? "text-text" : "text-muted"
                  }`}
                >
                  {suggested.length}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {suggested.length === 0
                    ? "Sin pendientes: los perfiles están dentro de los parámetros o ya decidiste sobre cada recomendación."
                    : `El backend estima hasta ${bestSavings}% de ahorro en la mejor de las sugerencias pendientes. Aplicá sólo después de revisar el detalle.`}
                </p>
              </div>
            </div>
          </Panel>

          <MetricGrid cols={3}>
            <Metric size="md" label="Perfiles con actividad" value={profiles.length.toLocaleString()} hint="Últimos 30 días" />
            <Metric size="md" label="Aplicadas" value={recommendations.filter((r) => r.status === "applied").length.toLocaleString()} />
            <Metric
              size="md"
              label="Ignoradas"
              value={recommendations.filter((r) => r.status === "ignored" || r.status === "dismissed").length.toLocaleString()}
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Perfiles por agente"
              description="Costo, latencia y fuentes por request en los últimos 30 días."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              {profiles.length === 0 ? (
                <EmptyState
                  icon={Lightbulb}
                  compact
                  title="Sin actividad"
                  body="Ningún agente registró requests en la ventana."
                  hint="Ejecutá consultas para generar perfiles y después corré el scan."
                />
              ) : (
                <table className="table min-w-[880px]">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th className="text-right">Requests</th>
                      <th className="text-right">Error</th>
                      <th className="text-right">p50</th>
                      <th className="text-right">p95</th>
                      <th className="text-right">Tokens/req</th>
                      <th className="text-right">Cost/req</th>
                      <th className="text-right">Embedding</th>
                      <th className="text-right">Fuentes/req</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profiles.map((p) => (
                      <tr key={p.agent_id ?? p.agent_name}>
                        <td className="font-medium">{p.agent_name}</td>
                        <td className="text-right tabular-nums">{p.requests.toLocaleString()}</td>
                        <td
                          className={`text-right tabular-nums ${p.error_rate_pct > 0 ? "text-warn" : "text-muted"}`}
                        >
                          {p.error_rate_pct}%
                        </td>
                        <td className="text-right tabular-nums">{p.p50_ms.toFixed(0)}ms</td>
                        <td className="text-right tabular-nums">{p.p95_ms.toFixed(0)}ms</td>
                        <td className="text-right tabular-nums">{p.tokens_per_request.toFixed(0)}</td>
                        <td className="text-right font-mono tabular-nums">${p.cost_per_request.toFixed(5)}</td>
                        <td className="text-right tabular-nums">{p.embedding_share_pct}%</td>
                        <td className="text-right tabular-nums">{p.sources_per_request.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="Recomendaciones"
              description="Cada sugerencia explica qué cambia y cuánto ahorra según el backend."
              className="mb-3"
            />
            <Panel>
              {recommendations.length === 0 ? (
                <EmptyState
                  icon={Lightbulb}
                  compact
                  title="Sin recomendaciones"
                  body="Todavía no se analizaron los perfiles de costo."
                  hint="Corré el scan para detectar oportunidades."
                />
              ) : (
                <ol className="divide-y divide-border-soft">
                  {recommendations.map((r) => {
                    const sev = SEVERITY_META[r.severity] ?? { tone: "neutral" as Tone, label: r.severity };
                    const st = STATUS_META[r.status] ?? { tone: "neutral" as Tone, label: r.status };
                    return (
                      <li
                        key={r.id}
                        className="state-rail flex flex-wrap items-start justify-between gap-3 px-4 py-3"
                        data-state={RAIL_STATE[r.status] ?? "queued"}
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-text">{r.message}</p>
                          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-faint">
                            <Badge tone={sev.tone}>{sev.label}</Badge>
                            <Badge tone={st.tone} dot>
                              {st.label}
                            </Badge>
                            <span className="mono">{r.recommendation_key}</span>
                            {r.expected_savings_pct != null && (
                              <>
                                <span aria-hidden>·</span>
                                <span className="tabular-nums text-ok">~{r.expected_savings_pct}% ahorro</span>
                              </>
                            )}
                            <span aria-hidden>·</span>
                            <span className="tabular-nums">{new Date(r.created_at).toLocaleString("es-PE")}</span>
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button size="sm" variant="ghost" onClick={() => setDetail(r)}>
                            Ver detalle
                          </Button>
                          {r.status === "suggested" && (
                            <>
                              <Button
                                size="sm"
                                variant="primary"
                                loading={busy === r.id}
                                onClick={() => setConfirm(r)}
                              >
                                Aplicar
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={busy === r.id}
                                onClick={() => void act(r.id, "ignore")}
                              >
                                Ignorar
                              </Button>
                            </>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </Panel>
          </section>
        </>
      )}

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => !open && setDetail(null)}
        title={detail ? `Recomendación ${detail.recommendation_key}` : "Recomendación"}
        description={detail?.message}
        footer={
          detail?.status === "suggested" ? (
            <>
              <Button variant="ghost" onClick={() => setDetail(null)}>
                Cerrar
              </Button>
              <Button variant="primary" leadingIcon={Sparkle} onClick={() => setConfirm(detail)}>
                Aplicar
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
            <KeyValue
              columns={2}
              items={[
                { key: "Severidad", value: SEVERITY_META[detail.severity]?.label ?? detail.severity },
                { key: "Estado", value: STATUS_META[detail.status]?.label ?? detail.status },
                { key: "Agente", value: detail.agent_id ?? "—", mono: true },
                {
                  key: "Ahorro estimado",
                  value: detail.expected_savings_pct != null ? `${detail.expected_savings_pct}%` : "—",
                },
                { key: "Creada", value: new Date(detail.created_at).toLocaleString("es-PE"), mono: true },
                {
                  key: "Aplicada",
                  value: detail.applied_at ? new Date(detail.applied_at).toLocaleString("es-PE") : "—",
                  mono: true,
                },
                { key: "Organización", value: detail.organization_id, mono: true },
              ]}
            />
            <div>
              <h3 className="eyebrow mb-2">Detalle técnico</h3>
              {Object.keys(detail.details ?? {}).length === 0 ? (
                <p className="text-[13px] text-muted">El backend no adjuntó detalle técnico a esta recomendación.</p>
              ) : (
                <pre className="max-h-72 overflow-auto rounded-md border border-border bg-control p-3 font-mono text-[12.5px] leading-relaxed text-text">
                  {JSON.stringify(detail.details, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Aplicar recomendación"
        body={
          confirm
            ? `${confirm.message} El cambio modifica la configuración del agente seleccionado.`
            : undefined
        }
        confirmLabel="Aplicar"
        tone="primary"
        loading={confirm !== null && busy === confirm.id}
        onConfirm={() => confirm && void act(confirm.id, "apply")}
      />
    </div>
  );
}
