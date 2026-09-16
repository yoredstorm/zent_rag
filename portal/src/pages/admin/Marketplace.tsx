import { BookOpen, Download, MagnifyingGlass, Star, Upload } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
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
  const [notice, setNotice] = useState("");
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
      setNotice("Listing publicado.");
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
    setNotice("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/marketplace/listings/${listingId}/install`,
        { method: "POST", token: session.token, body: JSON.stringify({ organization_id: orgId }) }
      );
      setNotice(`Instalado: ${out.status} (agente clonado)`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const listingColumns: Column<Listing>[] = [
    {
      key: "name",
      header: "Agente",
      render: (l) => (
        <span className="block min-w-0">
          <span className="block truncate text-[13px] font-medium text-text" title={l.name}>
            {l.name}
          </span>
          <span className="mt-0.5 block max-w-80 truncate text-xs text-muted" title={l.description ?? undefined}>
            {l.description || "Sin descripción"}
          </span>
          {l.tags.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {l.tags.map((t) => (
                <Badge key={t} tone="neutral">
                  {t}
                </Badge>
              ))}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "category",
      header: "Categoría",
      hideBelow: "md",
      render: (l) => <Badge tone="neutral">{l.category}</Badge>,
    },
    {
      key: "rating",
      header: "Rating",
      align: "right",
      hideBelow: "lg",
      render: (l) => (
        <span className="inline-flex items-center gap-1 text-xs text-muted tabular-nums">
          <Star size={12} className="text-warn" aria-hidden />
          {l.rating_avg.toFixed(1)} ({l.rating_count})
        </span>
      ),
    },
    {
      key: "installs",
      header: "Installs",
      align: "right",
      hideBelow: "md",
      render: (l) => <span className="mono text-xs text-muted tabular-nums">{l.installs}</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (l) => <StatusBadge status={l.status} />,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Agent Marketplace"
        subtitle="Publicar agentes, instalar en tenants, reviews y prompt templates."
        actions={
          <Button variant="primary" leadingIcon={Upload} onClick={() => setShowPublish(true)}>
            Publicar
          </Button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}

      <Tabs value={tab} variant="pill" onValueChange={(v) => setTab(v as "listings" | "templates")}>
        <div className="flex flex-wrap items-center gap-3">
          <TabsList>
            <TabsTrigger value="listings">Listings</TabsTrigger>
            <TabsTrigger value="templates">Templates</TabsTrigger>
          </TabsList>
          <span className="flex-1" aria-hidden />
          <Input
            icon={MagnifyingGlass}
            className="w-full sm:w-56"
            placeholder="Buscar…"
            aria-label="Buscar listings"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <TabsContent value="listings">
          {loading ? (
            <SkeletonBlock rows={6} />
          ) : (
            <DataTable
              columns={listingColumns}
              rows={listings}
              rowKey={(l) => l.id}
              caption="Listings del marketplace"
              stickyHeader
              rowActions={(l) => (
                <Select
                  className="w-44"
                  aria-label={`Instalar ${l.name}`}
                  value=""
                  disabled={!!busy}
                  onChange={(e) => void install(l.id, e.target.value)}
                >
                  <option value="" disabled>
                    Instalar en…
                  </option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.id.slice(0, 8)}
                    </option>
                  ))}
                </Select>
              )}
              empty={
                <EmptyState
                  icon={Download}
                  title="Sin listings"
                  body="Publica un agente para empezar a distribuirlo entre los tenants."
                  hint="El alta crea el listing desde un agente existente."
                />
              }
              footer={listings.length > 0 ? <ResultCount shown={listings.length} total={listings.length} noun="listings" /> : undefined}
            />
          )}
        </TabsContent>

        <TabsContent value="templates">
          {loading ? (
            <SkeletonBlock rows={6} />
          ) : templates.length === 0 ? (
            <Panel>
              <EmptyState
                icon={BookOpen}
                title="Sin templates"
                body="El catálogo de prompt templates está vacío."
                hint="Los templates builtin aparecen al cargar el catálogo de la plataforma."
              />
            </Panel>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
              {templates.map((t) => (
                <Panel key={t.id}>
                  <PanelHeader
                    title={
                      <span className="flex items-center gap-2">
                        <BookOpen size={14} className="text-faint" aria-hidden />
                        {t.name}
                      </span>
                    }
                    actions={
                      t.is_builtin ? (
                        <Badge tone="ok">builtin</Badge>
                      ) : (
                        <Badge tone="warn">{t.category}</Badge>
                      )
                    }
                    description={t.description || undefined}
                  />
                  <div className="panel-body">
                    <p className="line-clamp-4 rounded-sm border border-border bg-control p-2.5 font-mono text-[11px] leading-relaxed text-muted">
                      {t.content}
                    </p>
                  </div>
                </Panel>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Modal
        open={showPublish}
        onOpenChange={setShowPublish}
        title="Publicar listing"
        description="El listing clona el agente indicado en la organización seleccionada."
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowPublish(false)}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={busy === "publish"}
              disabled={!publishForm.orgId || !publishForm.agentId.trim() || !publishForm.name.trim()}
              onClick={() => void publish()}
            >
              Publicar listing
            </Button>
          </>
        }
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Organización" className="sm:col-span-2">
            <Select
              placeholder="Org…"
              value={publishForm.orgId}
              onChange={(e) => setPublishForm((f) => ({ ...f, orgId: e.target.value }))}
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id.slice(0, 8)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="agent_id">
            <Input
              className="font-mono"
              placeholder="agent_id"
              value={publishForm.agentId}
              onChange={(e) => setPublishForm((f) => ({ ...f, agentId: e.target.value }))}
            />
          </Field>
          <Field label="Nombre">
            <Input
              placeholder="Nombre"
              value={publishForm.name}
              onChange={(e) => setPublishForm((f) => ({ ...f, name: e.target.value }))}
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
