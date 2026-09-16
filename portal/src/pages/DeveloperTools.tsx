import { BookOpen, Globe, Plugs, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
} from "../components/ui";

type SdkEndpoint = {
  path: string;
  auth: string;
  body: string | null;
  description: string;
  snippets: Record<string, string>;
};

type Webhook = {
  id: string;
  event_type: string;
  url: string;
  enabled: boolean;
  delivery_count: number;
  fail_count: number;
  last_delivered_at: string | null;
};

const LANGS = ["python", "javascript", "csharp", "java", "php"] as const;

const LANG_EXT: Record<string, string> = {
  python: "py",
  javascript: "js",
  csharp: "cs",
  java: "java",
  php: "php",
};

const WEBHOOK_EVENTS = ["agent_run", "api_query", "deployment_event", "incident", "workflow_run"];

type ChangelogEntry = { version: string; title: string; body: string; published_at: string };

const CHANGELOG_COLUMNS: Column<ChangelogEntry>[] = [
  { key: "version", header: "Versión", width: "1%", render: (c) => <span className="mono text-xs">{c.version}</span> },
  { key: "title", header: "Título", render: (c) => <span className="text-[13px] font-medium text-text">{c.title}</span> },
  {
    key: "body",
    header: "Detalle",
    render: (c) => <span className="block max-w-[42rem] text-[13px] leading-relaxed text-muted">{c.body}</span>,
  },
  {
    key: "published",
    header: "Publicado",
    hideBelow: "md",
    render: (c) => <span className="text-xs text-faint">{new Date(c.published_at).toLocaleDateString("es-PE")}</span>,
  },
];

export default function DeveloperToolsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState("sdk");
  const [sdk, setSdk] = useState<SdkEndpoint[]>([]);
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [lang, setLang] = useState<string>("python");
  const [status, setStatus] = useState<{ status: string; api_version: string; checks: { name: string; status: string }[] } | null>(null);
  const [changelog, setChangelog] = useState<ChangelogEntry[]>([]);
  const [hookForm, setHookForm] = useState({ event_type: "agent_run", url: "", secret: "" });
  const [createdSecret, setCreatedSecret] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Webhook | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, w, st, ch] = await Promise.all([
        api<{ endpoints: SdkEndpoint[] }>("/api/v1/dev/sdk-reference", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ endpoints: [] as SdkEndpoint[] })),
        api<{ webhooks: Webhook[] }>("/api/v1/webhooks", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ webhooks: [] as Webhook[] })),
        api<{ status: string; api_version: string; checks: { name: string; status: string }[] }>(
          "/api/v1/dev/status",
          {}
        ).catch(() => null),
        api<{ changelog: ChangelogEntry[] }>(
          "/api/v1/dev/changelog",
          {}
        ).catch(() => ({ changelog: [] })),
      ]);
      setSdk(s.endpoints || []);
      setWebhooks(w.webhooks || []);
      setStatus(st);
      setChangelog(ch.changelog || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createHook() {
    if (!session) return;
    setBusy("hook");
    setError("");
    setNotice("");
    try {
      const out = await api<{ id: string; secret: string }>("/api/v1/webhooks", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(hookForm),
      });
      setCreatedSecret(out.secret);
      setNotice("Webhook creado. Copia el secreto ahora: no se vuelve a mostrar.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function testHook(hookId: string) {
    if (!session) return;
    setBusy(hookId);
    setError("");
    setNotice("");
    try {
      const out = await api<{ status: string }>(`/api/v1/webhooks/${hookId}/test`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: "{}",
      });
      setNotice(`Ping enviado. Respuesta del webhook: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function deleteHook(hookId: string) {
    if (!session) return;
    setBusy(hookId);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/webhooks/${hookId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
      setPendingDelete(null);
      setNotice("Webhook eliminado.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const webhookColumns: Column<Webhook>[] = [
    {
      key: "event",
      header: "Evento",
      render: (w) => <span className="mono text-xs text-text">{w.event_type}</span>,
    },
    {
      key: "url",
      header: "URL",
      render: (w) => (
        <span className="mono block max-w-[22rem] truncate text-xs text-muted" title={w.url}>
          {w.url}
        </span>
      ),
    },
    {
      key: "deliveries",
      header: "Entregas",
      align: "right",
      render: (w) => <span className="mono text-xs">{w.delivery_count}</span>,
    },
    {
      key: "failures",
      header: "Fallos",
      align: "right",
      render: (w) =>
        w.fail_count > 0 ? (
          <span className="mono text-xs text-danger">{w.fail_count}</span>
        ) : (
          <span className="mono text-xs text-muted">0</span>
        ),
    },
    {
      key: "last",
      header: "Último intento",
      hideBelow: "md",
      render: (w) => (
        <span className="text-xs text-faint">
          {w.last_delivered_at ? new Date(w.last_delivered_at).toLocaleString("es-PE") : "—"}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Developer Tools" subtitle="SDK reference, webhooks salientes y estado del platform." />
      <ErrorInline message={error} />
      <SuccessInline message={notice} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="sdk" icon={BookOpen}>
            SDK Reference
          </TabsTrigger>
          <TabsTrigger value="webhooks" icon={Plugs}>
            Webhooks
          </TabsTrigger>
          <TabsTrigger value="status" icon={Globe}>
            Estado
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sdk">
          {loading ? (
            <Panel className="p-4">
              <SkeletonBlock rows={4} />
            </Panel>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <Field label="Lenguaje" className="w-full max-w-56">
                  <Select value={lang} onChange={(e) => setLang(e.target.value)}>
                    {LANGS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </Select>
                </Field>
                <p className="text-xs text-faint">Cada ejemplo incluye copia inline.</p>
              </div>

              {sdk.length === 0 ? (
                <Panel>
                  <EmptyState
                    icon={BookOpen}
                    title="Sin referencia de SDK"
                    body="La referencia se publica con la API. Mientras tanto, usa la API Console o los logs."
                  />
                </Panel>
              ) : (
                sdk.map((ep) => {
                  const code = ep.snippets[lang] ?? ep.snippets.python;
                  return (
                    <Panel key={ep.path}>
                      <PanelHeader
                        title={<span className="mono text-sm">{ep.path}</span>}
                        description={ep.description}
                        actions={<Badge tone="neutral">{ep.auth}</Badge>}
                      />
                      <div className="panel-body">
                        <CodeBlock
                          code={code}
                          language={lang}
                          filename={`snippet.${LANG_EXT[lang] ?? "txt"}`}
                          maxHeight={320}
                        />
                      </div>
                    </Panel>
                  );
                })
              )}
            </div>
          )}
        </TabsContent>

        <TabsContent value="webhooks">
          <div className="flex flex-col gap-4">
            <Panel>
              <PanelHeader
                title="Suscribir webhook"
                description="Zent firma cada entrega con X-Zent-Signature. El secreto se muestra una sola vez."
              />
              <div className="panel-body grid gap-3 lg:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] lg:items-end">
                <Field label="Evento">
                  <Select
                    value={hookForm.event_type}
                    onChange={(e) => setHookForm((f) => ({ ...f, event_type: e.target.value }))}
                  >
                    {WEBHOOK_EVENTS.map((e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="URL de destino">
                  <Input
                    placeholder="https://hooks.corp.example/zent"
                    value={hookForm.url}
                    onChange={(e) => setHookForm((f) => ({ ...f, url: e.target.value }))}
                    autoComplete="off"
                  />
                </Field>
                <Button
                  variant="primary"
                  loading={busy === "hook"}
                  leadingIcon={Plugs}
                  disabled={!hookForm.url.trim()}
                  onClick={() => void createHook()}
                >
                  Suscribir
                </Button>
              </div>
            </Panel>

            {createdSecret && (
              <Panel className="border-accent/30">
                <PanelHeader
                  title="Secreto del webhook"
                  description="Cópialo ahora: por seguridad no se vuelve a mostrar."
                  actions={<Badge tone="warn">Cópialo ahora</Badge>}
                />
                <div className="panel-body">
                  <CodeBlock code={createdSecret} language="text" filename="X-Zent-Signature secret" maxHeight={120} />
                  <div className="mt-3">
                    <Button variant="ghost" size="sm" onClick={() => setCreatedSecret("")}>
                      Ocultar secreto
                    </Button>
                  </div>
                </div>
              </Panel>
            )}

            <DataTable
              columns={webhookColumns}
              rows={webhooks}
              rowKey={(w) => w.id}
              empty={
                <EmptyState
                  icon={Plugs}
                  title="Sin webhooks"
                  body="Suscribe un evento para reenviarlo con firma X-Zent-Signature."
                />
              }
              rowActions={(w) => (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={busy === w.id}
                    onClick={() => void testHook(w.id)}
                  >
                    Ping
                  </Button>
                  <IconButton
                    label={`Eliminar webhook ${w.event_type}`}
                    icon={Trash}
                    variant="ghost"
                    onClick={() => setPendingDelete(w)}
                  />
                </>
              )}
            />
          </div>
        </TabsContent>

        <TabsContent value="status">
          <div className="flex flex-col gap-4">
            <Panel className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={status?.status === "ok" ? "healthy" : "failed"} label={status ? `API ${status.status}` : "API sin datos"} />
                <Badge tone="neutral">v{status?.api_version ?? "…"}</Badge>
                {(status?.checks ?? []).map((c) => (
                  <StatusBadge
                    key={c.name}
                    status={c.status === "ok" ? "healthy" : "warning"}
                    label={`${c.name}: ${c.status}`}
                  />
                ))}
                {(status?.checks ?? []).length === 0 && (
                  <span className="text-xs text-faint">Sin checks reportados.</span>
                )}
              </div>
            </Panel>

            <DataTable
              caption="Changelog del platform"
              columns={CHANGELOG_COLUMNS}
              rows={changelog}
              rowKey={(c) => c.version}
              empty={
                <EmptyState
                  icon={Globe}
                  title="Sin changelog"
                  body="Los cambios publicados de la API aparecerán acá."
                />
              }
            />
          </div>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={pendingDelete ? `Eliminar el webhook ${pendingDelete.event_type}` : "Eliminar webhook"}
        body={
          pendingDelete
            ? `Se dejan de enviar los eventos a ${pendingDelete.url}. Esta acción no se puede deshacer.`
            : undefined
        }
        confirmLabel="Eliminar"
        loading={busy === pendingDelete?.id}
        onConfirm={() => {
          if (pendingDelete) void deleteHook(pendingDelete.id);
        }}
      />
    </div>
  );
}
