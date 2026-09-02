import { BookOpen, Download, Star, Upload } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Listing = {
  id: string;
  agent_id: string;
  organization_id: string;
  name: string;
  description: string | null;
  category: string;
  tags: string[];
  rating_avg: number;
  rating_count: number;
  installs: number;
  status: string;
  created_at: string;
  agent_snapshot?: {
    name: string;
    system_prompt: string;
    tools: string[];
    model: string;
  };
};

type Template = {
  id: string;
  name: string;
  category: string;
  description: string | null;
  content: string;
  is_builtin: boolean;
  created_at: string;
};

export default function AdminMarketplacePage() {
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<"listings" | "templates">("listings");
  const [listings, setListings] = useState<Listing[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [publishForm, setPublishForm] = useState({ orgId: "", agentId: "", name: "", category: "general" });
  const [showPublish, setShowPublish] = useState(false);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [l, t, o] = await Promise.all([
        platformApi<{ listings: Listing[] }>(`/api/v1/platform/marketplace/listings?q=${q}`, {
          token: session.token,
        }),
        platformApi<{ templates: Template[] }>("/api/v1/platform/marketplace/templates", {
          token: session.token,
        }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", {
          token: session.token,
        }),
      ]);
      setListings(l.listings || []);
      setTemplates(t.templates || []);
      setOrgs(o.organizations || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, q]);

  async function publish() {
    if (!session) return;
    setBusy("publish");
    setError("");
    try {
      await platformApi("/api/v1/platform/marketplace/listings", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(publishForm),
      });
      setShowPublish(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function install(listingId: string, orgId: string) {
    if (!session) return;
    setBusy(listingId);
    setError("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/marketplace/listings/${listingId}/install`,
        { method: "POST", token: session.token, body: JSON.stringify({ organization_id: orgId }) }
      );
      setError(`Instalado: ${out.status} (agente clonado)`);
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
        title="Agent Marketplace"
        subtitle="Publicar agentes, instalar en tenants, reviews y prompt templates."
        actions={
          <button type="button" className="btn btn-primary min-h-11" onClick={() => setShowPublish((s) => !s)}>
            <Upload size={15} aria-hidden /> Publicar
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {showPublish && (
        <div className="panel grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <select
            className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
            value={publishForm.orgId}
            onChange={(e) => setPublishForm((f) => ({ ...f, orgId: e.target.value }))}
          >
            <option value="">Org…</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <input
            className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
            placeholder="agent_id"
            value={publishForm.agentId}
            onChange={(e) => setPublishForm((f) => ({ ...f, agentId: e.target.value }))}
          />
          <input
            className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
            placeholder="Nombre"
            value={publishForm.name}
            onChange={(e) => setPublishForm((f) => ({ ...f, name: e.target.value }))}
          />
          <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void publish()}>
            Publicar listing
          </button>
        </div>
      )}

      <div className="flex items-center gap-4">
        <div className="flex gap-1 rounded-md border border-border p-1">
          {(["listings", "templates"] as const).map((t) => (
            <button
              key={t}
              type="button"
              className={`btn min-h-8 px-3 text-xs ${tab === t ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab(t)}
            >
              {t === "listings" ? "Listings" : "Templates"}
            </button>
          ))}
        </div>
        <input
          className="w-56 rounded-md border border-border bg-soft px-3 py-1.5 text-sm"
          placeholder="Buscar…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : tab === "listings" ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {listings.length === 0 ? (
            <div className="panel col-span-full">
              <EmptyState icon={Download} title="Sin listings" body="Publica un agente para empezar." />
            </div>
          ) : (
            listings.map((l) => (
              <div key={l.id} className="panel flex flex-col gap-2 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-text">{l.name}</p>
                  <span className="badge badge-ok">{l.category}</span>
                </div>
                <p className="line-clamp-2 text-xs text-muted">{l.description || "Sin descripción"}</p>
                <p className="text-xs text-faint">
                  <Star size={12} className="mr-1 inline text-warn" aria-hidden />
                  {l.rating_avg.toFixed(1)} ({l.rating_count}) · {l.installs} installs
                </p>
                <div className="flex items-center gap-2">
                  {l.tags.map((t) => (
                    <span key={t} className="badge badge-muted">{t}</span>
                  ))}
                </div>
                <select
                  className="mt-auto rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                  onChange={(e) => void install(l.id, e.target.value)}
                  defaultValue=""
                >
                  <option value="" disabled>
                    Instalar en…
                  </option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {templates.map((t) => (
            <div key={t.id} className="panel flex flex-col gap-2 p-4">
              <div className="flex items-center justify-between">
                <p className="flex items-center gap-2 text-sm font-semibold text-text">
                  <BookOpen size={14} className="text-accent" aria-hidden />
                  {t.name}
                </p>
                <span className={`badge ${t.is_builtin ? "badge-ok" : "badge-pending"}`}>
                  {t.is_builtin ? "builtin" : t.category}
                </span>
              </div>
              <p className="text-xs text-muted">{t.description}</p>
              <p className="line-clamp-3 rounded-md bg-soft p-2 text-[11px] text-faint">{t.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}