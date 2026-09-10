import { MagnifyingGlass, Plus, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { CATEGORY_META, NODE_LIBRARY, type NodeCategory, type NodeMeta } from "../lib/workflowGraph";

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
  actions: MxInstall["actions"];
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
  marketplace?: MarketplaceContext | null;
  onAddMarketplaceAction?: (installId: string, action: MxInstall["actions"][number]) => void;
  onAddRecommendation?: (rec: MxRecommendation) => void;
  onInstall?: (slug: string) => void;
};

const ORDER: NodeCategory[] = ["trigger", "data", "ai", "integration", "logic", "business", "control", "output"];

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  connected: { text: "conectado", cls: "badge-success" },
  credentials_missing: { text: "sin credenciales", cls: "badge-warning" },
  purpose_required: { text: "requiere propósito", cls: "badge-warning" },
  budget_exceeded: { text: "presupuesto superado", cls: "badge-danger" },
  provider_degraded: { text: "proveedor degradado", cls: "badge-warning" },
  deprecated: { text: "deprecated", cls: "badge-danger" },
  version_update: { text: "actualización disponible", cls: "badge-info" },
  disabled: { text: "deshabilitada", cls: "badge-muted" },
};

export function NodeLibrary({ onAdd, usedTypes, marketplace, onAddMarketplaceAction, onAddRecommendation, onInstall }: Props) {
  const [q, setQ] = useState("");
  const items = useMemo(() => Object.values(NODE_LIBRARY).filter((m) => !m.type.startsWith("trigger_") || usedTypes.length === 0), [usedTypes]);
  const filtered = items.filter(
    (m) => !q || m.label.toLowerCase().includes(q.toLowerCase()) || m.type.includes(q.toLowerCase())
  );
  const ql = q.trim().toLowerCase();

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

  return (
    <aside className="flex h-[560px] w-56 shrink-0 flex-col overflow-hidden rounded-md border border-border bg-raised/60" data-testid="wf-node-library">
      <div className="border-b border-border p-2">
        <h3 className="text-[11px] font-semibold tracking-wide text-faint uppercase">Nodos</h3>
        <div className="relative mt-1.5">
          <MagnifyingGlass size={12} className="absolute top-1/2 left-2 -translate-y-1/2 text-faint" aria-hidden />
          <input
            className="w-full rounded-md border border-border bg-bg py-1 pl-6 pr-2 text-[11px]"
            placeholder="Buscar nodo, RUC, SUNAT…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {ORDER.map((cat) => {
          const group = filtered.filter((m) => m.category === cat);
          if (group.length === 0 && !(cat === "business" && ql)) return null;
          if (group.length === 0) return null;
          return (
            <div key={cat}>
              <p className={`px-1 text-[9px] font-semibold tracking-wider uppercase ${CATEGORY_META[cat].color}`}>
                {CATEGORY_META[cat].label}
              </p>
              <div className="mt-1 space-y-1">
                {group.map((m) => (
                  <button
                    key={m.type}
                    type="button"
                    data-testid={`wf-add-${m.type}`}
                    className="flex w-full items-center gap-2 rounded-md border border-border bg-soft/60 px-2 py-1.5 text-left transition-colors hover:border-accent/40 hover:bg-soft"
                    onClick={() => onAdd(m)}
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded bg-bg text-[12px]" aria-hidden>
                      {m.icon}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[11px] font-medium text-text">{m.label}</span>
                      <span className="block truncate text-[9px] text-faint">{m.risk && m.risk !== "normal" ? `riesgo ${m.risk}` : "—"}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}

        {marketplace && mktVisible && (
          <MarketplaceSection
            context={marketplace}
            q={ql}
            onAddMarketplaceAction={onAddMarketplaceAction}
            onAddRecommendation={onAddRecommendation}
            onInstall={onInstall}
          />
        )}
        {filtered.length === 0 && !mktVisible && <p className="px-1 text-[10px] text-faint">Sin nodos para “{q}”</p>}
      </div>
    </aside>
  );
}

function MarketplaceSection({
  context,
  q,
  onAddMarketplaceAction,
  onAddRecommendation,
  onInstall,
}: {
  context: MarketplaceContext;
  q: string;
  onAddMarketplaceAction?: Props["onAddMarketplaceAction"];
  onAddRecommendation?: Props["onAddRecommendation"];
  onInstall?: Props["onInstall"];
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

  return (
    <div data-testid="wf-mkt-section" className="space-y-2">
      <p className="px-1 text-[9px] font-semibold tracking-wider uppercase text-fuchsia-400">Marketplace</p>

      {recommendations.length > 0 && (
        <div className="space-y-1" data-testid="wf-mkt-recommend">
          {recommendations.map((r) => (
            <div key={r.action_id} className="rounded-md border border-accent/40 bg-accent/5 px-2 py-1.5">
              <p className="flex items-center gap-1 text-[10px] font-medium text-text">
                <Sparkle size={10} className="text-accent" aria-hidden /> Recomendado
              </p>
              <p className="mt-0.5 text-[10px] text-muted">{r.reason}</p>
              <button
                type="button"
                data-testid={`wf-mkt-add-${r.action_id}`}
                className="mt-1 inline-flex items-center gap-1 rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-accent hover:border-accent/50"
                onClick={() => onAddRecommendation?.(r)}
              >
                <Plus size={10} aria-hidden /> Add to workflow
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1" data-testid="wf-mkt-installed">
        <p className="px-1 text-[9px] font-semibold tracking-wider uppercase text-faint">Installed</p>
        {installed.length === 0 && <p className="px-1 text-[10px] text-faint">Nada instalado aún.</p>}
        {installed.map((i) => (
          <div key={i.install_id} className="rounded-md border border-border bg-soft/60 px-2 py-1.5">
            <div className="flex items-center justify-between gap-1">
              <p className="text-[10px] font-medium text-text">{i.integration.name}</p>
              <span className={`badge ${STATUS_LABEL[i.status[0]]?.cls ?? "badge-muted"}`}>
                {STATUS_LABEL[i.status[0]]?.text ?? i.status[0]}
              </span>
            </div>
            {i.status.includes("version_update") && (
              <p className="mt-0.5 text-[9px] text-info">
                v{i.installed_version} · v{i.manifest_version} disponible
              </p>
            )}
            <div className="mt-1 flex flex-wrap gap-1">
              {i.actions.map((a) => (
                <button
                  key={a.action_id}
                  type="button"
                  data-testid={`wf-mkt-action-${a.action_id}`}
                  className="rounded border border-border bg-bg px-1.5 py-0.5 text-[9px] text-text hover:border-accent/50"
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

      {available.length > 0 && (
        <div className="space-y-1" data-testid="wf-mkt-available">
          <p className="px-1 text-[9px] font-semibold tracking-wider uppercase text-faint">Available</p>
          {available.map((a) => (
            <div key={a.slug} className="rounded-md border border-border bg-soft/60 px-2 py-1.5">
              <p className="text-[10px] font-medium text-text">{a.name}</p>
              <p className="mt-0.5 line-clamp-2 text-[9px] text-faint">{a.description || a.slug}</p>
              <button
                type="button"
                data-testid={`wf-mkt-install-${a.slug}`}
                className="mt-1 inline-flex items-center gap-1 rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-accent hover:border-accent/50"
                onClick={() => onInstall?.(a.slug)}
              >
                <Plus size={10} aria-hidden /> Add
              </button>
            </div>
          ))}
        </div>
      )}

      {installed.length === 0 && available.length === 0 && recommendations.length === 0 && (
        <p className="flex items-center gap-1 px-1 text-[10px] text-faint">
          <WarningCircle size={10} aria-hidden /> Sin capacidades de marketplace.
        </p>
      )}
    </div>
  );
}