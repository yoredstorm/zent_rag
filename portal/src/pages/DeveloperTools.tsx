import { BookOpen, Globe, Plugs } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
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

const LANGS = ["python", "javascript", "csharp", "java", "php"];

export default function DeveloperToolsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<"sdk" | "webhooks" | "status">("sdk");
  const [sdk, setSdk] = useState<SdkEndpoint[]>([]);
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [lang, setLang] = useState("python");
  const [status, setStatus] = useState<{ status: string; api_version: string; checks: { name: string; status: string }[] } | null>(null);
  const [changelog, setChangelog] = useState<{ version: string; title: string; body: string; published_at: string }[]>([]);
  const [hookForm, setHookForm] = useState({ event_type: "agent_run", url: "", secret: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

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
        api<{ changelog: { version: string; title: string; body: string; published_at: string }[] }>(
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
    try {
      const out = await api<{ id: string; secret: string }>("/api/v1/webhooks", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(hookForm),
      });
      setError(`Webhook creado (secret: ${out.secret})`);
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
    try {
      const out = await api<{ status: string }>(`/api/v1/webhooks/${hookId}/test`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: "{}",
      });
      setError(`Ping: ${out.status}`);
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
    try {
      await api(`/api/v1/webhooks/${hookId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setError("Copiado al portapapeles.");
    } catch {
      setError("No se pudo copiar.");
    }
  }

  return (
    <div>
      <PageHeader title="Developer Tools" subtitle="SDK reference, webhooks salientes y estado del platform." />
      <ErrorInline message={error} />
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="mb-4 flex gap-1 rounded-md border border-border p-1">
            {(
              [
                ["sdk", "SDK Reference", BookOpen],
                ["webhooks", "Webhooks", Plugs],
                ["status", "Estado", Globe],
              ] as const
            ).map(([key, label, Icon]) => (
              <button key={key} type="button" className={`btn min-h-8 text-xs ${tab === key ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(key)}>
                <Icon size={13} aria-hidden /> {label}
              </button>
            ))}
          </div>

          {tab === "sdk" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                {LANGS.map((l) => (
                  <button key={l} type="button" className={`btn min-h-8 px-2 text-xs ${lang === l ? "btn-secondary" : "btn-ghost"}`} onClick={() => setLang(l)}>
                    {l}
                  </button>
                ))}
              </div>
              {sdk.map((ep) => (
                <section key={ep.path} className="panel overflow-hidden">
                  <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
                    <p className="mono text-sm text-text">{ep.path}</p>
                    <span className="badge badge-muted">{ep.auth}</span>
                  </div>
                  <p className="px-4 py-2 text-xs text-muted">{ep.description}</p>
                  <pre className="m-3 overflow-x-auto rounded-md bg-soft p-3 text-[11px] leading-relaxed text-text">
                    {ep.snippets[lang] ?? ep.snippets.python}
                  </pre>
                  <div className="px-4 pb-3">
                    <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => void copy(ep.snippets[lang] ?? ep.snippets.python)}>
                      Copiar
                    </button>
                  </div>
                </section>
              ))}
            </div>
          )}

          {tab === "webhooks" && (
            <div className="space-y-4">
              <div className="panel grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={hookForm.event_type} onChange={(e) => setHookForm((f) => ({ ...f, event_type: e.target.value }))}>
                  {["agent_run", "api_query", "deployment_event", "incident", "workflow_run"].map((e) => (
                    <option key={e} value={e}>{e}</option>
                  ))}
                </select>
                <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="https://hooks.corp.example/zent" value={hookForm.url} onChange={(e) => setHookForm((f) => ({ ...f, url: e.target.value }))} />
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void createHook()}>
                  Suscribir (devuelve secret)
                </button>
              </div>
              {webhooks.length === 0 ? (
                <p className="text-sm text-muted">Sin webhooks. Los eventos del canal en tiempo real se reenvían con firma X-Zent-Signature.</p>
              ) : (
                <div className="panel overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Evento</th>
                        <th>URL</th>
                        <th>Entregas</th>
                        <th>Fallos</th>
                        <th>Última</th>
                        <th className="text-right">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {webhooks.map((w) => (
                        <tr key={w.id}>
                          <td className="mono text-xs">{w.event_type}</td>
                          <td className="text-xs text-muted">{w.url}</td>
                          <td className="text-xs">{w.delivery_count}</td>
                          <td className="text-xs">{w.fail_count}</td>
                          <td className="text-xs text-faint">{w.last_delivered_at ? new Date(w.last_delivered_at).toLocaleString("es-PE") : "—"}</td>
                          <td className="text-right">
                            <div className="flex justify-end gap-1">
                              <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void testHook(w.id)}>
                                Ping
                              </button>
                              <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs text-danger" disabled={!!busy} onClick={() => void deleteHook(w.id)}>
                                Quitar
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {tab === "status" && (
            <div className="space-y-4">
              <div className="panel flex flex-wrap items-center gap-4 p-4">
                <span className={`badge ${status?.status === "ok" ? "badge-ok" : "badge-danger"}`}>API {status?.status ?? "…"}</span>
                <span className="badge badge-pending">v{status?.api_version ?? "…"}</span>
                <div className="flex flex-wrap gap-2">
                  {(status?.checks ?? []).map((c) => (
                    <span key={c.name} className={`badge ${c.status === "ok" ? "badge-ok" : "badge-pending"}`}>
                      {c.name}: {c.status}
                    </span>
                  ))}
                </div>
              </div>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Versión</th>
                      <th>Título</th>
                      <th>Detalle</th>
                      <th>Publicado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changelog.map((c) => (
                      <tr key={c.version}>
                        <td className="mono text-xs">{c.version}</td>
                        <td className="text-sm text-text">{c.title}</td>
                        <td className="text-xs text-muted">{c.body}</td>
                        <td className="text-xs text-faint">{new Date(c.published_at).toLocaleDateString("es-PE")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}