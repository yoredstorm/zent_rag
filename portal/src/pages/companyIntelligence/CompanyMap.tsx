import { ArrowsOut, Circle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  SkeletonBlock,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import {
  COPY,
  entityTypeLabel,
  statusLabelFor,
  statusToneFor,
} from "./companyCopy";

type EntityView = {
  id: string;
  entity_type: string;
  canonical_name: string;
  display_name: string;
  status: string;
  confidence: number | null;
  authority_level: string | null;
};

type Edge = {
  id: string;
  relationship_type: string;
  direction: string;
  from: { id: string; name: string; type: string };
  to: { id: string; name: string; type: string };
  status: string;
  confidence: number | null;
  valid_from: string | null;
  valid_to: string | null;
  confirmed: boolean;
};

type MapLayer = {
  root: EntityView;
  nodes: EntityView[];
  edges: Edge[];
  groups: Record<string, EntityView[]>;
  truncated: boolean;
  limits: { max_nodes: number; max_edges: number; max_depth: number };
};

const WIDTH = 760;
const HEIGHT = 460;

/** Layout radial determinista: la raíz al centro, vecinos en anillo. */
function layout(layer: MapLayer) {
  const center = { x: WIDTH / 2, y: HEIGHT / 2 };
  const positions = new Map<string, { x: number; y: number }>();
  positions.set(layer.root.id, center);
  const count = Math.max(1, layer.nodes.length);
  layer.nodes.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / count - Math.PI / 2;
    positions.set(node.id, {
      x: center.x + Math.cos(angle) * (Math.min(WIDTH, HEIGHT) / 2 - 60),
      y: center.y + Math.sin(angle) * (Math.min(WIDTH, HEIGHT) / 2 - 60),
    });
  });
  return positions;
}

export default function CompanyMapPage() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const entityId = params.get("entity") || "";
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<EntityView[]>([]);
  const [layer, setLayer] = useState<MapLayer | null>(null);
  const [maxNodes, setMaxNodes] = useState(15);
  const [direction, setDirection] = useState("both");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const data = await api<{ items: EntityView[] }>(
          `/api/v1/company-intelligence/entities?limit=30${search ? `&q=${encodeURIComponent(search)}` : ""}`,
          { token: session.token, organizationId: session.organizationId },
        );
        setOptions(data.items || []);
        if (!entityId && data.items?.length) {
          setParams({ entity: data.items[0].id }, { replace: true });
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error buscando entidades");
      }
    })();
  }, [session, search, entityId, setParams]);

  const load = useCallback(async () => {
    if (!session || !entityId) return;
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({
        max_nodes: String(maxNodes),
        max_edges: "60",
        direction,
      });
      if (statusFilter) query.set("status", statusFilter);
      const data = await api<MapLayer>(
        `/api/v1/company-intelligence/map/${entityId}?${query.toString()}`,
        { token: session.token, organizationId: session.organizationId },
      );
      setLayer(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando el mapa");
      setLayer(null);
    } finally {
      setLoading(false);
    }
  }, [session, entityId, maxNodes, direction, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const positions = useMemo(() => (layer ? layout(layer) : new Map()), [layer]);

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.map}
        subtitle="Navegación por capas: se expande desde una entidad, nunca el grafo completo."
      />

      <ErrorInline message={error} />

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mr-2 text-muted">Entidad</span>
          <Input
            value={search}
            placeholder="Buscar por nombre…"
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Buscar entidad"
          />
        </label>
        <Select
          value={entityId}
          onChange={(event) => setParams({ entity: event.target.value })}
          aria-label="Entidad seleccionada"
        >
          <option value="">Elegí una entidad</option>
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.display_name} ({entityTypeLabel(option.entity_type)})
            </option>
          ))}
        </Select>
        <Select
          value={direction}
          onChange={(event) => setDirection(event.target.value)}
          aria-label="Dirección"
        >
          <option value="both">Ambas direcciones</option>
          <option value="out">Salientes</option>
          <option value="in">Entrantes</option>
        </Select>
        <Select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          aria-label="Estado"
        >
          <option value="">Todos los estados</option>
          <option value="confirmed">Confirmado</option>
          <option value="auto_confirmed">Auto-confirmado</option>
          <option value="discovered">Descubierto</option>
          <option value="stale">Obsoleto</option>
        </Select>
        <Select
          value={String(maxNodes)}
          onChange={(event) => setMaxNodes(Number(event.target.value))}
          aria-label="Máximo de nodos"
        >
          <option value="10">10 nodos</option>
          <option value="15">15 nodos</option>
          <option value="25">25 nodos</option>
          <option value="50">50 nodos</option>
        </Select>
        <Button variant="secondary" onClick={() => void load()} loading={loading}>
          Recargar
        </Button>
      </div>

      {loading && (
        <Panel>
          <SkeletonBlock rows={3} />
        </Panel>
      )}

      {!loading && !entityId && (
        <Panel>
          <EmptyState title="Sin entidad seleccionada" body={COPY.emptyMap} />
        </Panel>
      )}

      {!loading && layer && (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Panel>
            <PanelHeader
              title={layer.root.display_name}
              description={`${entityTypeLabel(layer.root.entity_type)} · ${layer.limits.max_nodes} nodos máximo`}
            />
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label={`Vecindad de ${layer.root.display_name}`}
              className="w-full"
              data-testid="company-map-canvas"
            >
              {layer.edges.map((edge) => {
                const from = positions.get(edge.from.id);
                const to = positions.get(edge.to.id);
                if (!from || !to) return null;
                const otherId =
                  edge.from.id === layer.root.id ? edge.to.id : edge.from.id;
                return (
                  <g key={edge.id}>
                    <line
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      stroke="currentColor"
                      className="text-border"
                      strokeDasharray={edge.confirmed ? undefined : "4 3"}
                    />
                    <title>{`${edge.from.name} ${edge.relationship_type} ${edge.to.name} (${statusLabelFor(edge.status)})`}</title>
                    <text
                      x={(from.x + to.x) / 2}
                      y={(from.y + to.y) / 2}
                      className="fill-current text-[9px] text-muted"
                      textAnchor="middle"
                    >
                      {edge.relationship_type}
                      {otherId ? "" : ""}
                    </text>
                  </g>
                );
              })}
              {layer.nodes.map((node) => {
                const point = positions.get(node.id);
                if (!point) return null;
                return (
                  <g
                    key={node.id}
                    tabIndex={0}
                    role="button"
                    aria-label={`${node.display_name}, ${entityTypeLabel(node.entity_type)}, ${statusLabelFor(node.status)}`}
                    className="cursor-pointer"
                    onClick={() => setParams({ entity: node.id })}
                  >
                    <circle cx={point.x} cy={point.y} r={9} className="fill-current text-accent" />
                    <text
                      x={point.x}
                      y={point.y - 14}
                      textAnchor="middle"
                      className="fill-current text-[10px]"
                    >
                      {node.display_name}
                    </text>
                    <text
                      x={point.x}
                      y={point.y + 22}
                      textAnchor="middle"
                      className="fill-current text-[9px] text-muted"
                    >
                      {statusLabelFor(node.status)}
                    </text>
                  </g>
                );
              })}
              <g>
                <circle
                  cx={positions.get(layer.root.id)?.x ?? WIDTH / 2}
                  cy={positions.get(layer.root.id)?.y ?? HEIGHT / 2}
                  r={12}
                  className="fill-current text-text"
                />
                <text
                  x={positions.get(layer.root.id)?.x ?? WIDTH / 2}
                  y={(positions.get(layer.root.id)?.y ?? HEIGHT / 2) - 18}
                  textAnchor="middle"
                  className="fill-current text-[11px] font-medium"
                >
                  {layer.root.display_name}
                </text>
              </g>
            </svg>
            {layer.truncated && (
              <p className="mt-2 text-xs text-muted">
                Se alcanzó el límite de nodos: expandí o filtrá para ver más.
              </p>
            )}
            <div className="mt-2 flex gap-2">
              <Button
                variant="secondary"
                leadingIcon={ArrowsOut}
                onClick={() => setMaxNodes((value) => Math.min(value + 10, 200))}
              >
                {COPY.loadMore}
              </Button>
              <Link
                className="btn btn-secondary"
                to={`/company-intelligence/entity/${layer.root.id}`}
              >
                Ver detalle
              </Link>
            </div>
          </Panel>

          <div className="space-y-4">
            <Panel>
              <PanelHeader title="Relaciones visibles" />
              <ul className="space-y-2 text-sm" data-testid="edge-list">
                {layer.edges.map((edge) => (
                  <li key={edge.id} className="flex flex-wrap items-center gap-2">
                    <Circle size={8} aria-hidden />
                    <span>
                      {edge.from.name} → {edge.to.name}
                    </span>
                    <Badge tone="neutral">{edge.relationship_type}</Badge>
                    <Badge tone={statusToneFor(edge.status)}>
                      {statusLabelFor(edge.status)}
                    </Badge>
                    {!edge.confirmed && <span className="text-xs text-muted">(no confirmada)</span>}
                  </li>
                ))}
                {layer.edges.length === 0 && (
                  <li className="text-muted">Sin relaciones en esta dirección.</li>
                )}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader title="Capas" />
              <div className="space-y-2 text-sm">
                {Object.entries(layer.groups).map(([group, items]) => (
                  <div key={group}>
                    <p className="text-muted">{group}</p>
                    <div className="flex flex-wrap gap-1">
                      {items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className="badge badge-muted"
                          onClick={() => setParams({ entity: item.id })}
                        >
                          {item.display_name}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </CompanyIntelligenceLayout>
  );
}
