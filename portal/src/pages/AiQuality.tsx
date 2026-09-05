import { ChartLineUp, Star, Target, ThumbsDown, ThumbsUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
} from "../components/ui";
import { QualityLayout } from "../components/QualityLayout";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type EvalStats = {
  period_days: number;
  total_evaluations: number;
  thumbs_up: number;
  thumbs_down: number;
  approval_rate: number;
  avg_latency_ms: number;
  avg_tokens: number;
  models_used: number;
};

type EvalRecent = {
  id: string;
  query: string;
  answer: string;
  role: string;
  rating: "up" | "down" | null;
  comment: string;
  model: string;
  total_tokens: number;
  latency_ms: number;
  method: string;
  created_at: string;
};

export default function AiQualityPage() {
  const { session } = useAuth();
  const [stats, setStats] = useState<EvalStats | null>(null);
  const [recent, setRecent] = useState<EvalRecent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [statsData, recentData] = await Promise.all([
          api<EvalStats>("/api/v1/eval/stats?days=30", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => null),
          api<EvalRecent[]>("/api/v1/eval/recent?limit=20", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => []),
        ]);
        setStats(statsData);
        setRecent(recentData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando calidad");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const needsAttention = recent.filter((r) => r.rating === "down");
  const hasData = Boolean(stats && stats.total_evaluations > 0);

  return (
    <QualityLayout>
      <PageHeader
        title="Calidad de IA"
        subtitle="Mide y mejora la calidad de tus respuestas a partir del feedback real de los usuarios."
      />
      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="stat space-y-2">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : !hasData ? (
        <EmptyState
          icon={Star}
          title="Aún no hay evaluaciones"
          body="Cuando los usuarios califiquen respuestas en el Playground o tus aplicaciones, verás aquí la calidad de tu IA: aprobación, latencia y casos que requieren atención."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <StatCard
              label="Evaluaciones"
              value={fmtNum(stats?.total_evaluations ?? 0)}
              icon={Target}
            />
            <StatCard
              label="Feedback positivo"
              value={fmtNum(stats?.thumbs_up ?? 0)}
              icon={ThumbsUp}
              tone="ok"
            />
            <StatCard
              label="Feedback negativo"
              value={fmtNum(stats?.thumbs_down ?? 0)}
              icon={ThumbsDown}
              tone={stats && stats.thumbs_down > 0 ? "danger" : "default"}
            />
            <StatCard
              label="Aprobación"
              value={`${stats?.approval_rate ?? 0}%`}
              icon={ChartLineUp}
              tone={stats && stats.approval_rate >= 70 ? "ok" : "warn"}
              hint="de respuestas con feedback"
            />
            <StatCard
              label="Latencia media"
              value={fmtLatency(stats?.avg_latency_ms ?? 0)}
              hint={`${fmtNum(stats?.avg_tokens ?? 0)} tokens promedio`}
            />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel xl:col-span-2">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Evaluaciones recientes</h2>
                <span className="mono text-[11px] text-faint">últimas 20</span>
              </div>
              {recent.length === 0 ? (
                <EmptyState
                  icon={Star}
                  title="Sin evaluaciones recientes"
                  body="Tus últimas preguntas con feedback aparecerán aquí."
                />
              ) : (
                <div className="divide-y divide-border/60">
                  {recent.map((r) => (
                    <div key={r.id} className="flex flex-col gap-1 px-5 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`badge ${r.rating === "down" ? "badge-danger" : r.rating === "up" ? "badge-ok" : "badge-muted"}`}
                        >
                          {r.rating === "down" ? "Negativo" : r.rating === "up" ? "Positivo" : "Sin feedback"}
                        </span>
                        <span className="mono text-xs text-faint">{r.model || "modelo"}</span>
                        <span className="ml-auto text-xs text-faint">{fmtDateTime(r.created_at)}</span>
                      </div>
                      <p className="truncate text-[13px] text-text" title={r.query}>
                        «{r.query}»
                      </p>
                      <p className="text-[11px] text-faint">
                        {fmtLatency(r.latency_ms)} · {fmtNum(r.total_tokens)} tokens · {r.role}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="panel">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Requieren atención</h2>
              </div>
              {needsAttention.length === 0 ? (
                <div className="px-5 py-6 text-[13px] leading-relaxed text-muted">
                  Todo se ve bien. No hay respuestas con feedback negativo en el período reciente.
                </div>
              ) : (
                <div className="divide-y divide-border/60">
                  {needsAttention.slice(0, 8).map((r) => (
                    <div key={r.id} className="flex flex-col gap-1 px-5 py-3">
                      <p className="truncate text-[13px] text-text" title={r.query}>
                        «{r.query}»
                      </p>
                      {r.comment && (
                        <p className="text-xs text-warn" title={r.comment}>
                          {r.comment}
                        </p>
                      )}
                      <p className="text-[11px] text-faint">{fmtDateTime(r.created_at)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </QualityLayout>
  );
}