// =============================================================================
// Knowledge Map — el cerebro empresarial navegable
// =============================================================================
// Zoom semántico con LOD real: Dominios, Temas, Objetos, Entidad. Nunca el
// grafo completo: cada nivel trae solo lo que se ve. Click inspecciona, doble
// click profundiza, breadcrumb y URL compartible.
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  CaretRight,
  ListBullets,
  MagnifyingGlass,
  ShareNetwork,
  SlidersHorizontal,
} from "@phosphor-icons/react";

import {
  Button,
  ButtonLink,
  Drawer,
  Select,
  cn,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeSearch } from "../../components/knowledge/KnowledgeSearch";
import { MapCanvas } from "../../components/knowledgeMap/MapCanvas";
import { MapInspector } from "../../components/knowledgeMap/MapInspector";
import { MapRail } from "../../components/knowledgeMap/MapRail";
import {
  layoutDomains,
  layoutGraph,
  layoutTopics,
  topicLabel,
  type MapLevel,
  type MapNode,
} from "../../components/knowledgeMap/mapInsights";
import {
  fetchKnowledgeConflicts,
  fetchKnowledgeDelta,
  fetchKnowledgeDomains,
  fetchKnowledgeGraph,
  type KnowledgeDomain,
  type KnowledgeGraphPayload,
} from "../../lib/knowledgeModel";

const TYPE_OPTIONS = [
  { value: "", label: "Todos los temas" },
  { value: "entity", label: "Entidades" },
  { value: "concept", label: "Conceptos" },
  { value: "business_rule", label: "Reglas" },
  { value: "metric", label: "Métricas" },
  { value: "process", label: "Procesos" },
  { value: "term", label: "Términos" },
  { value: "relationship", label: "Relaciones" },
];

const CONFIDENCE_OPTIONS = [
  { value: "", label: "Cualquier confianza" },
  { value: "0.6", label: "Media o más" },
  { value: "0.85", label: "Alta" },
];

const STATUS_OPTIONS = [
  { value: "", label: "Cualquier estado" },
  { value: "verified", label: "Verificados" },
  { value: "inferred", label: "Inferidos" },
  { value: "discovered", label: "Descubiertos" },
];

export default function KnowledgeMapPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const level = (params.get("level") as MapLevel) || "domains";
  const domain = params.get("domain") ?? "";
  const topic = params.get("topic") ?? "";
  const focus = params.get("focus") ?? "";
  const confidence = params.get("confidence") ?? "";
  const status = params.get("status") ?? "";
  const conflictsOnly = params.get("conflicts") === "1";
  const recentOnly = params.get("recent") === "1";

  const [domains, setDomains] = useState<KnowledgeDomain[]>([]);
  const [graph, setGraph] = useState<KnowledgeGraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [shareMsg, setShareMsg] = useState("");
  const [conflictIds, setConflictIds] = useState<Set<string>>(new Set());
  const [recentIds, setRecentIds] = useState<Set<string>>(new Set());

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params);
      for (const [key, value] of Object.entries(patch)) {
        if (value == null || value === "") next.delete(key);
        else next.set(key, value);
      }
      setParams(next, { replace: true });
    },
    [params, setParams]
  );

  // Dominios: base del nivel 1 y del rail.
  useEffect(() => {
    let cancelled = false;
    void fetchKnowledgeDomains()
      .then((data) => {
        if (!cancelled) setDomains(data.domains);
      })
      .catch(() => {
        if (!cancelled) setDomains([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Grafo del nivel objetos o entidad.
  useEffect(() => {
    if (level !== "objects" && level !== "entity") {
      setGraph(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    const request =
      level === "entity" && focus
        ? fetchKnowledgeGraph({
            focus_id: focus,
            limit_nodes: 50,
            limit_edges: 120,
          })
        : fetchKnowledgeGraph({
            domains: domain || undefined,
            types: topic || undefined,
            min_confidence: confidence ? Number(confidence) : undefined,
            limit_nodes: 70,
            limit_edges: 160,
          });
    void request
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setGraph(null);
          setError(err instanceof Error ? err.message : "No pudimos leer el grafo.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [level, domain, topic, focus, confidence]);

  // Filtros avanzados: ids reales de conflictos y de lo enriquecido (7d).
  useEffect(() => {
    if (!conflictsOnly && !recentOnly) return;
    let cancelled = false;
    void Promise.allSettled([
      conflictsOnly
        ? fetchKnowledgeConflicts("open")
        : Promise.resolve({ conflicts: [], count: 0 }),
      recentOnly
        ? fetchKnowledgeDelta({ window: "7d" })
        : Promise.resolve(null),
    ]).then(([conflictsResult, deltaResult]) => {
      if (cancelled) return;
      if (conflictsResult.status === "fulfilled") {
        setConflictIds(
          new Set(
            conflictsResult.value.conflicts
              .map((conflict) => conflict.object_id)
              .filter((value): value is string => Boolean(value))
          )
        );
      }
      if (deltaResult.status === "fulfilled" && deltaResult.value) {
        setRecentIds(new Set(deltaResult.value.enriched.map((item) => item.id)));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [conflictsOnly, recentOnly]);

  const selectedDomain = domains.find((item) => item.name === domain) ?? null;

  const layout = useMemo(() => {
    if (level === "domains") return layoutDomains(domains);
    if (level === "topics") return layoutTopics(selectedDomain);
    if (!graph) return { nodes: [], edges: [] };
    const base = layoutGraph(graph, level === "entity" ? 50 : 70);
    if (level !== "objects") return base;
    const nodes = base.nodes.filter((node) => {
      if (status && node.meta?.status !== status) return false;
      if (conflictsOnly && !conflictIds.has(node.id)) return false;
      if (recentOnly && !recentIds.has(node.id)) return false;
      return true;
    });
    const ids = new Set(nodes.map((node) => node.id));
    return {
      nodes,
      edges: base.edges.filter(
        (edge) => ids.has(edge.source) && ids.has(edge.target)
      ),
    };
  }, [
    level,
    domains,
    selectedDomain,
    graph,
    status,
    conflictsOnly,
    conflictIds,
    recentOnly,
    recentIds,
  ]);

  const handleSelect = useCallback(
    (node: MapNode) => {
      if (level === "domains") {
        update({ level: "topics", domain: node.label, topic: null, focus: null });
        return;
      }
      if (level === "topics") {
        if (node.id.startsWith("topic:")) {
          const type = String(node.meta?.type ?? "");
          update({ level: "objects", topic: type, focus: null });
        } else {
          update({ level: "domains", domain: null, topic: null, focus: null });
        }
        return;
      }
      update({ focus: node.id });
    },
    [level, update]
  );

  const handleDrill = useCallback(
    (node: MapNode) => {
      if (level === "domains") {
        update({ level: "topics", domain: node.label, topic: null, focus: null });
        return;
      }
      if (level === "topics") {
        handleSelect(node);
        return;
      }
      update({ level: "entity", focus: node.id, topic: null });
    },
    [level, update, handleSelect]
  );

  const goBack = useCallback(() => {
    if (level === "entity") {
      update({ level: "objects", focus: null });
      return;
    }
    if (level === "objects") {
      update({ level: topic ? "topics" : "objects", topic: null, focus: null });
      return;
    }
    if (level === "topics") {
      update({ level: "domains", domain: null, focus: null });
      return;
    }
    navigate("/knowledge");
  }, [level, topic, update, navigate]);

  const share = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShareMsg("Enlace copiado");
      window.setTimeout(() => setShareMsg(""), 2000);
    } catch {
      setShareMsg("Copia la URL del navegador");
      window.setTimeout(() => setShareMsg(""), 2500);
    }
  }, []);

  const emptyCopy =
    level === "topics"
      ? "Este dominio todavía no tiene temas de negocio; sus objetos son soporte (tablas, columnas y documentos)."
      : level === "objects"
        ? "Sin objetos con estos filtros. Prueba otro tema o quita filtros."
        : undefined;

  return (
    <KnowledgeLayout>
      <header className="km-header">
        <div className="min-w-0">
          <p className="eyebrow">Knowledge Map</p>
          <h1 className="text-h1">El cerebro de tu empresa, navegable</h1>
          <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
            Explora qué sabe ZENT, cómo está conectado y de dónde salió. Cada
            nivel trae solo el detalle que necesitas.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {shareMsg && <span className="text-[11px] text-ok">{shareMsg}</span>}
          <Button
            size="sm"
            variant="secondary"
            leadingIcon={ShareNetwork}
            onClick={() => void share()}
          >
            Compartir vista
          </Button>
          <Button
            size="sm"
            variant="secondary"
            leadingIcon={MagnifyingGlass}
            onClick={() => setSearchOpen(true)}
          >
            Buscar
          </Button>
          <ButtonLink
            to="/knowledge/explorer"
            size="sm"
            variant="ghost"
            leadingIcon={ListBullets}
          >
            Vista lista
          </ButtonLink>
        </div>
      </header>

      <nav className="km-breadcrumb" aria-label="Ruta en el Knowledge Map">
        <button type="button" className="km-crumb" onClick={goBack}>
          <ArrowLeft size={12} aria-hidden />
          Atrás
        </button>
        <button
          type="button"
          className={cn("km-crumb", level === "domains" && "is-current")}
          onClick={() => update({ level: "domains", domain: null, topic: null, focus: null })}
        >
          Knowledge
        </button>
        {domain && (
          <>
            <CaretRight size={10} className="text-ghost" aria-hidden />
            <button
              type="button"
              className={cn("km-crumb", level === "topics" && "is-current")}
              onClick={() => update({ level: "topics", topic: null, focus: null })}
            >
              {domain}
            </button>
          </>
        )}
        {topic && (
          <>
            <CaretRight size={10} className="text-ghost" aria-hidden />
            <button
              type="button"
              className={cn("km-crumb", level === "objects" && "is-current")}
              onClick={() => update({ level: "objects", focus: null })}
            >
              {topicLabel(topic)}
            </button>
          </>
        )}
        {focus && level === "entity" && (
          <>
            <CaretRight size={10} className="text-ghost" aria-hidden />
            <span className="km-crumb is-current">
              {graph?.nodes.find((node) => node.id === focus)?.name ?? "Entidad"}
            </span>
          </>
        )}
      </nav>

      <div className="km-filters">
        <Select
          aria-label="Tema"
          value={topic}
          onChange={(event) =>
            update({ topic: event.target.value, level: "objects", focus: null })
          }
          className="min-h-8 w-[160px]"
        >
          {TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Confianza"
          value={confidence}
          onChange={(event) => update({ confidence: event.target.value, focus: null })}
          className="min-h-8 w-[160px]"
        >
          {CONFIDENCE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Button
          size="sm"
          variant={advanced ? "secondary" : "ghost"}
          leadingIcon={SlidersHorizontal}
          onClick={() => setAdvanced((value) => !value)}
          aria-expanded={advanced}
          data-testid="map-advanced"
        >
          Avanzado
        </Button>
        {advanced && (
          <>
            <Select
              aria-label="Estado"
              value={status}
              onChange={(event) => update({ status: event.target.value })}
              className="min-h-8 w-[150px]"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <label className="km-check">
              <input
                type="checkbox"
                checked={conflictsOnly}
                onChange={(event) =>
                  update({ conflicts: event.target.checked ? "1" : null })
                }
              />
              Solo conflictos
            </label>
            <label className="km-check">
              <input
                type="checkbox"
                checked={recentOnly}
                onChange={(event) =>
                  update({ recent: event.target.checked ? "1" : null })
                }
              />
              Cambios recientes (7d)
            </label>
          </>
        )}
      </div>

      {error && <p className="text-[12px] text-danger">{error}</p>}

      <div className="km-layout">
        <div className="panel km-canvas-panel">
          {loading && !graph && level !== "domains" && level !== "topics" ? (
            <div className="p-4" aria-busy="true">
              <div className="h-[460px] animate-pulse rounded-md bg-soft" />
            </div>
          ) : (
            <MapCanvas
              layout={layout}
              selectedId={focus || null}
              onSelect={handleSelect}
              onDrill={handleDrill}
              pulse={level === "domains"}
              emptyCopy={emptyCopy}
            />
          )}
        </div>
        <MapInspector
          objectId={focus || null}
          onClose={focus ? () => update({ focus: null }) : undefined}
        />
      </div>

      <MapRail
        domains={domains}
        onSelectDomain={(name) =>
          update({ level: "topics", domain: name, topic: null, focus: null })
        }
        onSelectObject={(id) => update({ level: "entity", focus: id })}
      />

      <Drawer
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title="Buscar en el conocimiento"
        description="Conceptos, entidades, reglas, fuentes y documentos."
        width={520}
      >
        <div className="p-4">
          <KnowledgeSearch autoFocus />
        </div>
      </Drawer>
    </KnowledgeLayout>
  );
}
