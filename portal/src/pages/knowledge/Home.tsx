// =============================================================================
// Knowledge Home — estado factual, una acción y lo que necesita atención
// =============================================================================
// No hay descubrimientos simulados ni un dashboard técnico en el hero.
// =============================================================================
import { useCallback, useEffect, useState } from "react";
import { Lightning } from "@phosphor-icons/react";
import { Button, ButtonLink, ErrorInline, Panel } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeHero } from "../../components/knowledge/KnowledgeHero";
import { AttentionPanel } from "../../components/knowledge/AttentionPanel";
import { ActivityFeed } from "../../components/knowledge/ActivityFeed";
import {
  fetchKnowledgeDelta,
  fetchKnowledgeOverview,
  type KnowledgeDelta as KnowledgeDeltaData,
  type KnowledgeOverview,
} from "../../lib/knowledgeModel";
import {
  fetchKnowledgeFeed,
  streamKnowledgeEvents,
  type KnowledgeFeedItem,
} from "../../lib/knowledgeActivity";
import type { LearningEvent } from "../../lib/knowledgeLearning";

export default function KnowledgeHomePage() {
  const [overview, setOverview] = useState<KnowledgeOverview | null>(null);
  const [delta, setDelta] = useState<KnowledgeDeltaData | null>(null);
  const [feed, setFeed] = useState<KnowledgeFeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [feedLoading, setFeedLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    const results = await Promise.allSettled([
      fetchKnowledgeOverview(),
      fetchKnowledgeDelta({ window: "24h" }),
    ]);
    const [overviewResult, deltaResult] = results;
    setOverview(overviewResult.status === "fulfilled" ? overviewResult.value : null);
    setDelta(deltaResult.status === "fulfilled" ? deltaResult.value : null);
    if (results.every((result) => result.status === "rejected")) {
      const reason = results[0].status === "rejected" ? results[0].reason : null;
      setError(
        reason instanceof Error
          ? reason.message
          : "No pudimos obtener el conocimiento de tu organización.",
      );
    }
    if (!silent) setLoading(false);
  }, []);

  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    try {
      setFeed(await fetchKnowledgeFeed(40));
    } catch {
      // El feed es observabilidad: su fallo no tumba la home.
    } finally {
      setFeedLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    void loadFeed();
  }, [loadFeed]);

  // Stream real: solo refresca cuando llega actividad nueva, sin duplicar poll.
  useEffect(() => {
    const connectAt = Date.now();
    let refreshTimer = 0;
    let fullRefreshTimer = 0;
    const handle = streamKnowledgeEvents({
      sinceSeq: 0,
      onEvent: (event: LearningEvent) => {
        const at = event.created_at ? Date.parse(event.created_at) : 0;
        if (at && at < connectAt - 15_000) return;
        window.clearTimeout(refreshTimer);
        refreshTimer = window.setTimeout(() => void loadFeed(), 2_000);
        window.clearTimeout(fullRefreshTimer);
        fullRefreshTimer = window.setTimeout(() => void load(true), 4_000);
      },
    });
    return () => {
      window.clearTimeout(refreshTimer);
      window.clearTimeout(fullRefreshTimer);
      handle.close();
    };
  }, [loadFeed, load]);

  const empty = overview?.state === "empty";

  return (
    <KnowledgeLayout>
      <div className="flex flex-col gap-5">
        <KnowledgeHero overview={overview} delta={delta} loading={loading} />

        {!loading && error && (
          <div data-testid="knowledge-home-error">
            <ErrorInline
              className="mb-0"
              message={`No pudimos obtener el conocimiento de tu organización. ${error}`}
            />
            <Button
              className="mt-3"
              variant="secondary"
              onClick={() => setRefreshKey((value) => value + 1)}
            >
              Reintentar
            </Button>
          </div>
        )}

        {!loading && !error && (
          <>
            {!empty ? (
              <AttentionPanel
                attention={overview?.attention ?? []}
                conflicts={overview?.conflicts_preview ?? []}
                gaps={overview?.gaps_preview ?? []}
                measured={(overview?.health.measured_dimensions ?? 0) > 0}
              />
            ) : null}

            <Panel className="p-5" data-testid="knowledge-next-step">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-text">
                    {empty
                      ? "Empieza con una fuente."
                      : "Puedes preguntar o revisar lo que necesita atención."}
                  </p>
                  <p className="mt-1 max-w-[70ch] text-xs leading-relaxed text-muted">
                    {empty
                      ? "Un PDF, una hoja de cálculo o una base de datos. ZENT te mostrará el progreso real y te dirá cuándo está disponible."
                      : "La disponibilidad no es una promesa de calidad: abre la evidencia antes de usar una respuesta en una tarea crítica."}
                  </p>
                </div>
              </div>
            </Panel>

            {!empty ? (
              <details
                className="panel px-5 py-3"
                data-testid="knowledge-recent-activity"
              >
                <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-text">
                  <Lightning size={14} className="text-accent" aria-hidden />
                  Actividad reciente
                  <span className="text-xs font-normal text-faint">
                    {feed.length > 0 ? `${feed.length} señales` : "sin señales"}
                  </span>
                </summary>
                <div className="mt-3 border-t border-border-soft pt-3">
                  <ActivityFeed items={feed} loading={feedLoading} initialLimit={5} />
                  <ButtonLink
                    to="/knowledge/activity"
                    size="sm"
                    variant="ghost"
                    className="mt-2"
                  >
                    Ver toda la actividad
                  </ButtonLink>
                </div>
              </details>
            ) : null}
          </>
        )}
      </div>
    </KnowledgeLayout>
  );
}
