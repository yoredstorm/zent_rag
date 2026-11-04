import { ClockCounterClockwise, MagnifyingGlass, Plus, Sparkle, Star, WarningCircle, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { marketplaceHref } from "../lib/marketplaceReturn";
import { loadFavorites, loadRecents, pushRecent, toggleFavorite } from "../lib/nodeCatalogPrefs";
import { NODE_DND_TYPE } from "./workflowCanvas/geometry";
import { CATEGORY_META, NODE_LIBRARY, PURPOSE_GROUPS, type NodeCategory, type NodeMeta } from "../lib/workflowGraph";
export type MxInstall = {
  install_id: string;
  integration: { slug: string; name: string };
  installed_version: number;
  manifest_version: number;
  status: string[];
  actions: { action_id: string; display_name: string; description: string | null; cost: { model: string; price: number; currency: string }; renderer: string | null }[];
};

export type MxAvailable = {
  slug: string;
  name: string;
  description: string | null;
  requires_credentials: boolean;
  requires_purpose?: boolean;
  actions: MxInstall["actions"];
  /** Producto del catálogo global (si el asset está sincronizado). */
  legacy?: boolean;
  product?: {
    product_id: string;
    product_slug: string;
    product_name: string;
    business_category: string;
    pricing: { model?: string; amount?: number; currency?: string; interval?: string; unit?: string };
  } | null;
};

export type MxRecommendation = {
  action_id: string;
  integration_slug: string;
  reason: string;
  require_install: boolean;
};

export type MarketplaceContext = {
  installed: MxInstall[];
  available: MxAvailable[];
  recommendations: MxRecommendation[];
  costs: { action_id: string; cost: { model: string; price: number; currency: string } }[];
};

type Props = {
  onAdd: (meta: NodeMeta) => void;
  usedTypes: string[];
  /** Catálogo backend (Fase 5). Sin él se usa NODE_LIBRARY local. */
  nodes?: Record<string, NodeMeta> | null;
  /** Labels de categoría del catálogo backend (color local). */
  categoryLabels?: Record<string, string> | null;
  /** Modo negocio: agrupa por propósito; Advanced usa categorías técnicas. */
  businessMode?: boolean;
  marketplace?: MarketplaceContext | null;
  onAddMarketplaceAction?: (installId: string, action: MxInstall["actions"][number]) => void;
  onAddRecommendation?: (rec: MxRecommendation) => void;
  onInstall?: (slug: string) => void;
  /** Ruta interna a la que vuelve el Marketplace global. */
  returnTo?: string | null;
  nodeId?: string | null;
  /** Tamaño y posición; el estudio lo muestra como flyout sobre el lienzo. */
  className?: string;
  /** Flyout: botón de cierre y Esc. */
  onClose?: () => void;
  autoFocus?: boolean;
};

// AI primero: "Preguntar a un agente" es el nodo que la gente busca.
const ORDER: NodeCategory[] = ["ai", "data", "logic", "integration", "business", "control", "output", "trigger"];
const FIRST_IN_CATEGORY = ["llm"];

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  connected: { text: "conectado", cls: "badge-success" },
  credentials_missing: { text: "sin credenciales", cls: "badge-warning" },
  purpose_required: { text: "requiere propósito", cls: "badge-warning" },
  budget_exceeded: { text: "presupuesto superado", cls: "badge-danger" },
  provider_degraded: { text: "proveedor degradado", cls: "badge-warning" },
  deprecated: { text: "obsoleta", cls: "badge-danger" },
  version_update: { text: "actualización disponible", cls: "badge-info" },
  disabled: { text: "deshabilitada", cls: "badge-muted" },
};

function fold(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function matches(meta: NodeMeta, q: string): boolean {
  if (!q) return true;
  const needle = fold(q.trim());
  return [meta.label, meta.type, meta.description ?? ""].some((text) => fold(text).includes(needle));
}

/** Fila del catálogo: clic para insertar, arrastrar al lienzo, estrella para favorito. */
function NodeItem({
  meta,
  testId,
  favorite,
  onAdd,
  onToggleFavorite,
  draggable,
}: {
  meta: NodeMeta;
  testId: string;
  favorite: boolean;
  onAdd: (meta: NodeMeta) => void;
  onToggleFavorite: (type: string) => void;
  draggable: boolean;
}) {
  const unavailable = meta.available === false;
  const risky = meta.risk === "elevated" || meta.risk === "critical";
  return (
    <div className="group/item relative flex items-stretch">
      <button
        type="button"
        data-testid={testId}
        disabled={unavailable}
        title={unavailable ? meta.unavailableReason ?? "No disponible" : meta.description}
        draggable={draggable && !unavailable}
        onDragStart={(ev) => {
          ev.dataTransfer.setData(NODE_DND_TYPE, meta.type);
          ev.dataTransfer.setData("text/plain", meta.label);
          ev.dataTransfer.effectAllowed = "copy";
        }}
        className="flex min-h-10 w-full cursor-pointer items-center gap-2.5 rounded-md border border-transparent py-1.5 pr-8 pl-2 text-left transition-colors outline-none hover:border-border hover:bg-soft focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
        onClick={() => onAdd(meta)}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-border-soft bg-bg text-[13px]" aria-hidden>
          {meta.icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] leading-tight font-medium text-text">{meta.label}</span>
          {unavailable ? (
            <span className="block truncate text-[11px] leading-tight text-faint">{meta.unavailableReason ?? "No disponible"}</span>
          ) : risky ? (
            <span className="block truncate text-[11px] leading-tight text-warn">riesgo {meta.risk}</span>
          ) : meta.description ? (
            <span className="block truncate text-[11px] leading-tight text-faint">{meta.description}</span>
          ) : null}
        </span>
      </button>
      <button
        type="button"
        aria-label={favorite ? `Quitar ${meta.label} de favoritos` : `Marcar ${meta.label} como favorito`}
        aria-pressed={favorite}
        className={`absolute top-1/2 right-1 flex h-7 w-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-sm outline-none hover:bg-bg focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent ${
          favorite ? "text-warn" : "text-faint opacity-0 group-hover/item:opacity-100"
        }`}
        onClick={() => onToggleFavorite(meta.type)}
      >
        <Star size={13} weight={favorite ? "fill" : "regular"} aria-hidden />
      </button>
    </div>
  );
}

export function NodeLibrary({
  onAdd,
  usedTypes,
  nodes,
  categoryLabels,
  businessMode = false,
  marketplace,
  onAddMarketplaceAction,
  onAddRecommendation,
  returnTo,
  nodeId,
  className = "h-[560px]",
  onClose,
  autoFocus = false,
}: Props) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<string[]>(() => loadFavorites());
  const [recents, setRecents] = useState<string[]>(() => loadRecents());
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) searchRef.current?.focus();
  }, [autoFocus]);

  const items = useMemo(
    () => Object.values(nodes ?? NODE_LIBRARY).filter((m) => !m.type.startsWith("trigger_") || usedTypes.length === 0),
    [usedTypes, nodes]
  );
  const filtered = items.filter((m) => matches(m, q));
  const ql = q.trim().toLowerCase();
  const byType = useMemo(() => new Map(items.map((m) => [m.type, m])), [items]);
  const favoriteItems = favorites.map((t) => byType.get(t)).filter((m): m is NodeMeta => !!m);
  const recentItems = recents.map((t) => byType.get(t)).filter((m): m is NodeMeta => !!m);

  function add(meta: NodeMeta) {
    setRecents(pushRecent(meta.type));
    onAdd(meta);
  }

  const groups = useMemo(() => {
    if (businessMode) {
      return PURPOSE_GROUPS.map((group) => ({
        key: group.id,
        label: group.label,
        cls: "text-muted",
        items: filtered.filter((meta) => group.types.includes(meta.type)),
      }));
    }
    return ORDER.map((category) => ({
      key: category,
      label: categoryLabels?.[category] ?? CATEGORY_META[category].label,
      cls: CATEGORY_META[category].color,
      items: filtered
        .filter((meta) => meta.category === category)
        .sort(
          (a, b) =>
            Number(FIRST_IN_CATEGORY.includes(b.type)) - Number(FIRST_IN_CATEGORY.includes(a.type))
        ),
    }));
  }, [businessMode, filtered, categoryLabels]);

  const mktVisible =
    !!marketplace &&
    (!ql ||
      marketplace.installed.some(
        (i) =>
          i.integration.name.toLowerCase().includes(ql) ||
          i.integration.slug.includes(ql) ||
          i.actions.some((a) => a.action_id.includes(ql) || a.display_name.toLowerCase().includes(ql))
      ) ||
      marketplace.available.some((a) => a.name.toLowerCase().includes(ql) || a.slug.includes(ql)) ||
      (marketplace.recommendations ?? []).some((r) => r.action_id.includes(ql)));

  const toggleFav = (type: string) => setFavorites(toggleFavorite(type));
  const visibleGroups = groups.filter((group) => group.items.length > 0 && (!category || group.key === category));
  const showShortcuts = !q && !category;

  return (
    <aside
      className={`flex shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-surface ${className}`}
      data-testid="wf-node-library"
      aria-label="Catálogo de nodos"
      onKeyDown={(ev) => {
        if (ev.key === "Escape" && onClose) {
          ev.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="border-b border-border p-2.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold text-text">Añadir nodo</h3>
          {onClose && (
            <button
              type="button"
              aria-label="Cerrar catálogo"
              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-sm text-faint hover:bg-soft hover:text-text"
              onClick={onClose}
            >
              <X size={14} aria-hidden />
            </button>
          )}
        </div>
        <div className="relative mt-2">
          <MagnifyingGlass size={13} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-faint" aria-hidden />
          <input
            ref={searchRef}
            className="h-9 w-full rounded-md border border-border bg-bg pr-2 pl-8 text-[12.5px] outline-none focus-visible:border-accent"
            placeholder="Buscar por nombre o descripción…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Buscar nodo"
            data-testid="wf-node-search"
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1" role="group" aria-label="Filtrar por categoría">
          {groups
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <button
                key={group.key}
                type="button"
                aria-pressed={category === group.key}
                className={`min-h-6 cursor-pointer rounded-full border px-2 text-[11px] transition-colors ${
                  category === group.key
                    ? "border-accent/60 bg-accent/10 text-text"
                    : "border-border text-muted hover:border-border-strong hover:text-text"
                }`}
                onClick={() => setCategory((cur) => (cur === group.key ? null : group.key))}
              >
                {group.label}
              </button>
            ))}
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-2">
        {showShortcuts && favoriteItems.length > 0 && (
          <section aria-label="Favoritos">
            <p className="flex items-center gap-1 px-2 text-[11px] font-semibold text-faint">
              <Star size={11} weight="fill" className="text-warn" aria-hidden /> Favoritos
            </p>
            <div className="mt-1 space-y-0.5">
              {favoriteItems.map((m) => (
                <NodeItem key={m.type} meta={m} testId={`wf-fav-${m.type}`} favorite onAdd={add} onToggleFavorite={toggleFav} draggable />
              ))}
            </div>
          </section>
        )}
        {showShortcuts && recentItems.length > 0 && (
          <section aria-label="Recientes">
            <p className="flex items-center gap-1 px-2 text-[11px] font-semibold text-faint">
              <ClockCounterClockwise size={11} aria-hidden /> Recientes
            </p>
            <div className="mt-1 space-y-0.5">
              {recentItems.map((m) => (
                <NodeItem
                  key={m.type}
                  meta={m}
                  testId={`wf-recent-${m.type}`}
                  favorite={favorites.includes(m.type)}
                  onAdd={add}
                  onToggleFavorite={toggleFav}
                  draggable
                />
              ))}
            </div>
          </section>
        )}
        {visibleGroups.map((group) => (
          <section key={group.key} aria-label={group.label}>
            <p className={`px-2 text-[11px] font-semibold tracking-wide uppercase ${group.cls}`}>{group.label}</p>
            <div className="mt-1 space-y-0.5">
              {group.items.map((m) => (
                <NodeItem
                  key={m.type}
                  meta={m}
                  testId={`wf-add-${m.type}`}
                  favorite={favorites.includes(m.type)}
                  onAdd={add}
                  onToggleFavorite={toggleFav}
                  draggable
                />
              ))}
            </div>
          </section>
        ))}

        {marketplace && mktVisible && !category && (
          <MarketplaceSection
            context={marketplace}
            q={ql}
            returnTo={returnTo}
            nodeId={nodeId}
            onAddMarketplaceAction={onAddMarketplaceAction}
            onAddRecommendation={onAddRecommendation}
          />
        )}
        {filtered.length === 0 && !mktVisible && <p className="px-2 text-[12px] text-faint">Sin nodos para “{q}”</p>}
      </div>
    </aside>
  );
}

const SETUP_STATUS = new Set(["credentials_missing", "purpose_required", "disabled", "budget_exceeded"]);

function needsSetup(status: string[]): boolean {
  return status.some((item) => SETUP_STATUS.has(item));
}

function MarketplaceSection({
  context,
  q,
  returnTo,
  nodeId,
  onAddMarketplaceAction,
  onAddRecommendation,
}: {
  context: MarketplaceContext;
  q: string;
  returnTo?: string | null;
  nodeId?: string | null;
  onAddMarketplaceAction?: Props["onAddMarketplaceAction"];
  onAddRecommendation?: Props["onAddRecommendation"];
}) {
  const installed = (context.installed ?? []).filter(
    (i) =>
      !q ||
      i.integration.name.toLowerCase().includes(q) ||
      i.integration.slug.includes(q) ||
      i.actions.some((a) => a.action_id.toLowerCase().includes(q) || a.display_name.toLowerCase().includes(q))
  );
  const available = (context.available ?? []).filter(
    (a) =>
      !q ||
      a.name.toLowerCase().includes(q) ||
      a.slug.includes(q) ||
      a.actions.some((x) => x.action_id.toLowerCase().includes(q) || x.display_name.toLowerCase().includes(q))
  );
  const recommendations = (context.recommendations ?? []).filter((r) => !q || r.action_id.includes(q));
  const ready = installed.filter((item) => !needsSetup(item.status));
  const setup = installed.filter((item) => needsSetup(item.status));

  function resolveHref(slug: string, capabilityRef?: string) {
    return marketplaceHref({ slug, capabilityRef, returnTo, nodeId });
  }

  return (
    <div data-testid="wf-capabilities" className="space-y-2">
      <p className="px-1 text-[11px] font-medium text-text">Capacidades</p>
      <p className="px-1 text-[11.5px] leading-relaxed text-faint">
        Catálogo único. Si falta una, se resuelve en el Marketplace global.
      </p>

      {recommendations.length > 0 && (
        <div className="space-y-1" data-testid="wf-mkt-recommend">
          {recommendations.map((r) => (
            <div key={r.action_id} className="rounded-md border border-accent/40 bg-accent/5 px-2 py-1.5">
              <p className="flex items-center gap-1 text-[11.5px] font-medium text-text">
                <Sparkle size={10} className="text-accent" aria-hidden /> Recomendado
              </p>
              <p className="mt-0.5 text-[11.5px] text-muted">{r.reason}</p>
              {installed.some((item) => item.integration.slug === r.integration_slug) ? (
                <button
                  type="button"
                  data-testid={`wf-mkt-add-${r.action_id}`}
                  className="mt-1 inline-flex min-h-8 items-center gap-1 rounded border border-border bg-bg px-1.5 text-[11px] text-accent hover:border-accent/50"
                  onClick={() => onAddRecommendation?.(r)}
                >
                  <Plus size={10} aria-hidden /> Añadir al flujo
                </button>
              ) : (
                <a
                  className="mt-1 inline-flex min-h-8 items-center text-[11px] text-accent underline-offset-2 hover:underline"
                  href={resolveHref(r.integration_slug, r.action_id)}
                >
                  Resolver en Marketplace global
                </a>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1" data-testid="wf-mkt-installed">
        <p className="px-1 text-[11px] font-semibold tracking-wider uppercase text-faint">Disponibles</p>
        {ready.length === 0 && <p className="px-1 text-[11.5px] text-faint">Ninguna lista para usar.</p>}
        {ready.map((i) => (
          <div key={i.install_id} className="rounded-md border border-border bg-soft/60 px-2 py-1.5">
            <div className="flex items-center justify-between gap-1">
              <p className="text-[11.5px] font-medium text-text">{i.integration.name}</p>
              <span className={`badge ${STATUS_LABEL[i.status[0]]?.cls ?? "badge-muted"}`}>
                {STATUS_LABEL[i.status[0]]?.text ?? i.status[0]}
              </span>
            </div>
            {i.status.includes("version_update") && (
              <p className="mt-0.5 text-[11px] text-info">
                v{i.installed_version} · v{i.manifest_version} disponible
              </p>
            )}
            <div className="mt-1 flex flex-wrap gap-1">
              {i.actions.map((a) => (
                <button
                  key={a.action_id}
                  type="button"
                  data-testid={`wf-mkt-action-${a.action_id}`}
                  className="rounded border border-border bg-bg px-1.5 py-0.5 text-[11px] text-text hover:border-accent/50"
                  onClick={() => onAddMarketplaceAction?.(i.install_id, a)}
                >
                  {a.display_name}
                  {a.cost.price > 0 ? ` · S/ ${a.cost.price}` : ""}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {setup.length > 0 && (
        <div className="space-y-1" data-testid="wf-capabilities-setup">
          <p className="px-1 text-[11px] font-semibold tracking-wider uppercase text-faint">Por configurar</p>
          {setup.map((item) => (
            <div key={item.install_id} className="rounded-md border border-border bg-soft/60 px-2 py-1.5">
              <p className="text-[11.5px] font-medium text-text">{item.integration.name}</p>
              <p className="mt-0.5 text-[11.5px] text-warn">Falta configuración antes de usarla en el flujo.</p>
              <a
                className="mt-1 inline-flex min-h-8 items-center text-[11px] text-accent underline-offset-2 hover:underline"
                href={resolveHref(item.integration.slug)}
              >
                Resolver en Marketplace global
              </a>
            </div>
          ))}
        </div>
      )}

      {available.length > 0 && (
        <div className="space-y-1" data-testid="wf-mkt-available">
          <p className="px-1 text-[11px] font-semibold tracking-wider uppercase text-faint">No instaladas</p>
          {available.map((a) => (
            <div key={a.slug} className="rounded-md border border-border bg-soft/60 px-2 py-1.5">
              <p className="text-[11.5px] font-medium text-text">{a.name}</p>
              <p className="mt-0.5 line-clamp-2 text-[11px] text-faint">{a.description || a.slug}</p>
              <p className="mt-0.5 text-[11.5px] text-warn">Requisito: no está instalada en este espacio.</p>
              <a
                className="mt-1 inline-flex min-h-8 items-center text-[11px] text-accent underline-offset-2 hover:underline"
                data-testid={`wf-mkt-install-${a.slug}`}
                href={resolveHref(a.slug, a.actions[0]?.action_id)}
              >
                Resolver en Marketplace global
              </a>
            </div>
          ))}
        </div>
      )}

      {installed.length === 0 && available.length === 0 && recommendations.length === 0 && (
        <p className="flex items-center gap-1 px-1 text-[11.5px] text-faint">
          <WarningCircle size={10} aria-hidden /> Sin capacidades de marketplace.
        </p>
      )}
    </div>
  );
}