import { Lightbulb, Rocket } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
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

const SEVERITY_BADGE: Record<string, string> = {
  important: "badge-danger",
  optimization: "badge-pending",
  info: "badge-muted",
};

export default function AdminOptimizerPage() {
  const { session } = usePlatformAuth();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [orgId, setOrgId] = useState("");

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
    try {
      const out = await platformApi<{ count: number }>(
        `/api/v1/platform/optimizer/scan?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`${out.count} recomendaciones creadas`);
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
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/optimizer/recommendations/${recId}/${action}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`Rec ${action === "apply" ? "aplicada" : "ignorada"}: ${out.status}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Optimizer"
        subtitle="Perfiles de costo/desempeño y recomendaciones accionables por agente."
        actions={
          <button type="button" className="btn btn-primary min-h-11" disabled={!!busy} onClick={() => void scan()}>
            <Rocket size={15} aria-hidden /> Escanear
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Perfiles por agente (30d)</h3>
            <div className="panel overflow-x-auto">
              {profiles.length === 0 ? (
                <EmptyState icon={Lightbulb} title="Sin actividad" body="Ejecuta consultas para generar perfiles." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th>Requests</th>
                      <th>Error %</th>
                      <th>p50</th>
                      <th>p95</th>
                      <th>Tokens/req</th>
                      <th>Cost/req</th>
                      <th>Embedding %</th>
                      <th>Fuentes/req</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profiles.map((p) => (
                      <tr key={p.agent_id ?? p.agent_name}>
                        <td className="text-sm text-text">{p.agent_name}</td>
                        <td className="text-xs">{p.requests}</td>
                        <td className="text-xs">{p.error_rate_pct}%</td>
                        <td className="text-xs">{p.p50_ms.toFixed(0)}ms</td>
                        <td className="text-xs">{p.p95_ms.toFixed(0)}ms</td>
                        <td className="text-xs">{p.tokens_per_request.toFixed(0)}</td>
                        <td className="text-xs">${p.cost_per_request.toFixed(5)}</td>
                        <td className="text-xs">{p.embedding_share_pct}%</td>
                        <td className="text-xs">{p.sources_per_request.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Lightbulb size={15} aria-hidden /> Recomendaciones
            </h3>
            <div className="panel">
              {recommendations.length === 0 ? (
                <EmptyState icon={Lightbulb} title="Sin recomendaciones" body="Ejecuta el scan para analizar los perfiles." />
              ) : (
                <ul className="space-y-2 p-3">
                  {recommendations.map((r) => (
                    <li
                      key={r.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 ${
                        r.status === "suggested"
                          ? "border-accent/30 bg-soft"
                          : "border-border"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">{r.message}</p>
                        <p className="text-xs text-faint">
                          <span className={`badge ${SEVERITY_BADGE[r.severity] ?? "badge-muted"}`}>
                            {r.severity}
                          </span>{" "}
                          {r.recommendation_key} ·{" "}
                          {r.expected_savings_pct != null ? `~${r.expected_savings_pct}% ahorro · ` : ""}
                          {new Date(r.created_at).toLocaleString("es-PE")} ·{" "}
                          <span className={`badge ${r.status === "applied" ? "badge-ok" : "badge-muted"}`}>
                            {r.status}
                          </span>
                        </p>
                      </div>
                      {r.status === "suggested" && (
                        <div className="flex gap-1">
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 text-xs"
                            disabled={!!busy}
                            onClick={() => void act(r.id, "apply")}
                          >
                            Aplicar
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 text-xs text-faint"
                            disabled={!!busy}
                            onClick={() => void act(r.id, "ignore")}
                          >
                            Ignorar
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}