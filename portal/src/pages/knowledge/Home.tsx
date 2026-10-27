// =============================================================================
// Knowledge Home — el cerebro vivo de la empresa
// =============================================================================
// Responde en segundos: qué sabe ZENT, qué aprendió, qué cambió, qué está
// creciendo y qué necesita atención. Todo desde el backend real.
// =============================================================================
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ChatCircleDots,
  Lightning,
  Plus,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import { loadSession } from "../../api";
import { Button, ButtonLink, ErrorInline, Panel } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeHero } from "../../components/knowledge/KnowledgeHero";
import { KnowledgePulse } from "../../components/knowledge/KnowledgePulse";
import { KnowledgeDelta } from "../../components/knowledge/KnowledgeDelta";
import { KnowledgeDomains } from "../../components/knowledge/KnowledgeDomains";
import { AttentionPanel } from "../../components/knowledge/AttentionPanel";
import { ActivityFeed } from "../../components/knowledge/ActivityFeed";
import {
  fetchKnowledgeDelta,
  fetchKnowledgeGraph,
  fetchKnowledgeOverview,
  type KnowledgeDelta as KnowledgeDeltaData,
  type KnowledgeGraphPayload,
  type KnowledgeOverview,
} from "../../lib/knowledgeModel";
import {
  fetchKnowledgeFeed,
  streamKnowledgeEvents,
  type KnowledgeFeedItem,
} from "../../lib/knowledgeActivity";
import type { LearningEvent } from "../../lib/knowledgeLearning";

function FirstSteps() {
  const steps = [
    {
      title: "Añade una fuente",
      body: "PDF, Excel, base de datos o API. ZENT la lee y la entiende.",
      to: "/knowledge/sources?new=1",
    },
    {
      title: "Observa cómo aprende",
      body: "El pulso se llena de nodos y conexiones reales mientras comprende.",
      to: "/knowledge/activity",
    },
    {
      title: "Usa el conocimiento",
      body: "Tus agentes responden con evidencia de lo que ZENT aprendió.",
      to: "/knowledge/playground",
    },
  ];
  return (
    <Panel className="p-5" data-testid="knowledge-first-steps">
      <p className="eyebrow flex items-center gap-2">
        <Sparkle size={12} weight="fill" className="text-accent" aria-hidden />
        Primeros pasos
      </p>
      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        {steps.map((step, index) => (
          <div key={step.title} className="flex flex-col gap-1">
            <span className="mono text-[11px] text-faint">
              {String(index + 1).padStart(2, "0")}
            </span>
            <p className="text-sm font-medium text-text">{step.title}</p>
            <p className="text-xs leading-relaxed text-muted">{step.body}</p>
            <ButtonLink
              to={step.to}
              variant="ghost"
              size="sm"
              className="mt-1 self-start"
              leadingIcon={ArrowRight}
            >
              Empezar
            </ButtonLink>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function QuickActions({ permissions }: { permissions: string[] }) {
  const can = (code: string) =>
    permissions.length === 0 || permissions.includes("*") || permissions.includes(code);
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-soft/60 px-3 py-2.5"
      data-testid="knowledge-quick-actions"
    >
      <span className="mr-1 text-xs font-medium text-muted">Acciones frecuentes</span>
      {can("sources:write") ? (
        <ButtonLink to="/knowledge/sources?new=1" variant="primary" size="sm" leadingIcon={Plus}>
          Añadir información
        </ButtonLink>
      ) : null}
      {can("knowledge:read") ? (
        <ButtonLink to="/knowledge/ask" variant="secondary" size="sm" leadingIcon={ChatCircleDots}>
          Hacer una pregunta
        </ButtonLink>
      ) : null}
      {can("knowledge:read") ? (
        <ButtonLink
          to="/knowledge/improve?tab=conflicts"
          variant="ghost"
          size="sm"
          leadingIcon={WarningCircle}
        >
          Revisar problemas
        </ButtonLink>
      ) : null}
    </div>
  );
}

export default function KnowledgeHomePage() {
  const permissions = loadSession()?.permissions ?? [];
  const navigate = useNavigate();
  const [overview, setOverview] = useState<KnowledgeOverview | null>(null);
  const [delta, setDelta] = useState<KnowledgeDeltaData | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraphPayload | null>(null);
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
      fetchKnowledgeGraph({ limit_nodes: 40, limit_edges: 90 }),
    ]);
    const [overviewResult, deltaResult, graphResult] = results;
    setOverview(overviewResult.status === "fulfilled" ? overviewResult.value : null);
    setDelta(deltaResult.status === "fulfilled" ? deltaResult.value : null);
    setGraph(graphResult.status === "fulfilled" ? graphResult.value : null);
    const failed = results.filter((result) => result.status === "rejected").length;
    if (failed === results.length) {
      const reason = results[0].status === "rejected" ? results[0].reason : null;
      setError(
        reason instanceof Error
          ? reason.message
          : "No pudimos obtener el conocimiento de tu organización."
      );
    } else {
      setError("");
    }
    if (!silent) setLoading(false);
  }, []);

  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    try {
      const items = await fetchKnowledgeFeed(60);
      setFeed(items);
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
    const interval = window.setInterval(() => void loadFeed(), 45_000);
    return () => window.clearInterval(interval);
  }, [loadFeed]);

  // Stream real: el replay viejo no refresca; los eventos nuevos sí (batched).
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

  const openObject = useCallback(
    (id: string) => navigate(`/knowledge/objects/${id}`),
    [navigate]
  );

  const empty = overview?.state === "empty";

  return (
    <KnowledgeLayout>
      <div className="flex flex-col gap-5">
        <KnowledgeHero
          overview={overview}
          delta={delta}
          loading={loading}
          onSearch={(query) =>
            navigate(`/knowledge/search?q=${encodeURIComponent(query)}`)
          }
        />

        {!loading && !error ? <QuickActions permissions={permissions} /> : null}

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

        {!loading && !error && empty && <FirstSteps />}

        {!loading && !error && !empty && (
          <>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <KnowledgePulse
                graph={graph}
                events={feed}
                loading={loading}
                onSelect={openObject}
              />
              <KnowledgeDelta onSelectObject={openObject} refreshKey={refreshKey} />
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <KnowledgeDomains
                domains={overview?.domains ?? []}
                loading={loading}
              />
              <AttentionPanel
                attention={overview?.attention ?? []}
                conflicts={overview?.conflicts_preview ?? []}
                gaps={overview?.gaps_preview ?? []}
              />
            </div>

            <ActivityFeed
              items={feed}
              loading={feedLoading}
              initialLimit={7}
              actions={
                <ButtonLink
                  to="/knowledge/activity"
                  size="sm"
                  variant="ghost"
                  leadingIcon={Lightning}
                >
                  Ver toda la actividad
                </ButtonLink>
              }
            />
          </>
        )}

        {!loading && !error && empty && (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <KnowledgePulse graph={null} events={[]} onSelect={openObject} />
            <Panel className="flex flex-col justify-center gap-3 p-5">
              <p className="text-sm text-text">
                El Knowledge Pulse se llenará solo.
              </p>
              <p className="text-xs leading-relaxed text-muted">
                Cuando conectes la primera fuente, cada entidad y cada relación
                real aparecerá aquí. Sin datos de ejemplo, sin decoración.
              </p>
              <ButtonLink
                to="/knowledge/sources?new=1"
                variant="primary"
                leadingIcon={Plus}
                className="self-start"
              >
                Añadir fuente
              </ButtonLink>
            </Panel>
          </div>
        )}
      </div>
    </KnowledgeLayout>
  );
}
