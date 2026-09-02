import { Bell, Check, CheckSquare, EnvelopeSimple, Archive } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Notification = {
  id: string;
  event_type: string;
  title: string;
  body: string | null;
  read: boolean;
  archived: boolean;
  created_at: string;
};

type Preferences = { channels: Record<string, boolean>; events: Record<string, unknown> };

const ICONS: Record<string, React.ReactNode> = {
  "quota.exceeded": <EnvelopeSimple size={15} />,
  "invoice.paid": <CheckSquare size={15} />,
};

export default function NotificationsPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [prefs, setPrefs] = useState<Preferences>({ channels: { in_app: true, email: true, webhook: true }, events: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [n, u, p] = await Promise.all([
        api<{ notifications: Notification[] }>(`/api/v1/notifications?unread_only=${unreadOnly}`, {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ count: number }>("/api/v1/notifications/unread-count", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<Preferences>("/api/v1/notifications/preferences", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setItems(n.notifications || []);
      setUnread(u.count || 0);
      setPrefs(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, unreadOnly]);

  async function act(id: string, action: "read" | "archive") {
    if (!session) return;
    try {
      await api(`/api/v1/notifications/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function readAll() {
    if (!session) return;
    try {
      await api("/api/v1/notifications/read-all", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function savePrefs() {
    if (!session) return;
    try {
      await api("/api/v1/notifications/preferences", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ channels: prefs.channels }),
      });
      setError("Preferencias guardadas.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div>
      <PageHeader title="Notificaciones" subtitle={`${unread} sin leer · canales y alertas de la organización.`} />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-text">Centro</h2>
              <label className="flex items-center gap-1 text-xs text-text">
                <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
                Solo sin leer
              </label>
              <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" onClick={() => void readAll()}>
                Marcar todo leído
              </button>
            </div>
            <div className="panel space-y-2 p-4">
              {items.length === 0 && <p className="text-xs text-faint">Sin notificaciones.</p>}
              {items.map((n) => (
                <div key={n.id} className={`rounded-md border px-4 py-3 ${n.read ? "border-border bg-soft/50" : "border-accent/30 bg-soft"}`}>
                  <div className="flex items-center gap-2">
                    <span className="text-accent">{ICONS[n.event_type] ?? <Bell size={15} />}</span>
                    <p className="flex-1 text-sm font-medium text-text">{n.title}</p>
                    <span className="text-[10px] text-faint">{new Date(n.created_at).toLocaleString()}</span>
                    {!n.read && <span className="badge badge-ok">nueva</span>}
                  </div>
                  {n.body && <p className="mt-1 text-xs text-faint">{n.body}</p>}
                  <div className="mt-2 flex gap-2">
                    {!n.read && (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" onClick={() => void act(n.id, "read")}>
                        <Check size={12} /> Leída
                      </button>
                    )}
                    {!n.archived && (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" onClick={() => void act(n.id, "archive")}>
                        <Archive size={12} /> Archivar
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel p-4">
            <h2 className="mb-2 text-sm font-semibold text-text">Preferencias por canal</h2>
            <div className="space-y-2">
              {Object.entries(prefs.channels).map(([channel, enabled]) => (
                <label key={channel} className="flex items-center justify-between rounded-md bg-soft px-3 py-2 text-xs">
                  <span className="text-text">{channel}</span>
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setPrefs((p) => ({ ...p, channels: { ...p.channels, [channel]: e.target.checked } }))}
                  />
                </label>
              ))}
            </div>
            <button type="button" className="btn btn-primary mt-3 min-h-9 text-xs" onClick={() => void savePrefs()}>
              Guardar
            </button>
          </section>
        </div>
      )}
    </div>
  );
}