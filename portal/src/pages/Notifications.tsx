import { Archive, Bell, Check, CheckSquare, EnvelopeSimple } from "@phosphor-icons/react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SaveStatus,
  SkeletonBlock,
  Switch,
  type SaveState,
} from "../components/ui";
import { fmtDateTime, timeAgo } from "../lib/format";

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

const ICONS: Record<string, ReactNode> = {
  "quota.exceeded": <EnvelopeSimple size={15} aria-hidden />,
  "invoice.paid": <CheckSquare size={15} aria-hidden />,
};

const CHANNEL_LABELS: Record<string, string> = {
  in_app: "En la app",
  email: "Email",
  webhook: "Webhook",
};

export default function NotificationsPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [prefs, setPrefs] = useState<Preferences>({
    channels: { in_app: true, email: true, webhook: true },
    events: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [prefsState, setPrefsState] = useState<SaveState>("idle");
  const [prefsError, setPrefsError] = useState("");

  async function load() {
    if (!session) return;
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
    const target = items.find((n) => n.id === id);
    if (!target) return;
    const previousItems = items;
    const previousUnread = unread;
    setError("");
    // Actualización optimista: la acción se refleja sin recargar la lista.
    setItems((list) =>
      list.map((n) =>
        n.id === id ? { ...n, read: action === "read" ? true : n.read, archived: action === "archive" ? true : n.archived } : n,
      ),
    );
    if (action === "read" && !target.read) setUnread((count) => Math.max(0, count - 1));
    try {
      await api(`/api/v1/notifications/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
    } catch (e) {
      setItems(previousItems);
      setUnread(previousUnread);
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function readAll() {
    if (!session) return;
    const previousItems = items;
    const previousUnread = unread;
    setError("");
    setItems((list) => list.map((n) => ({ ...n, read: true })));
    setUnread(0);
    try {
      await api("/api/v1/notifications/read-all", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
    } catch (e) {
      setItems(previousItems);
      setUnread(previousUnread);
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function savePrefs() {
    if (!session) return;
    setPrefsState("saving");
    setPrefsError("");
    try {
      await api("/api/v1/notifications/preferences", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ channels: prefs.channels }),
      });
      setPrefsState("saved");
    } catch (e) {
      setPrefsError(e instanceof Error ? e.message : "Error");
      setPrefsState("error");
    }
  }

  function toggleChannel(channel: string, enabled: boolean) {
    setPrefs((p) => ({ ...p, channels: { ...p.channels, [channel]: enabled } }));
    setPrefsState("dirty");
  }

  const unreadItems = items.filter((n) => !n.read);
  const readItems = items.filter((n) => n.read);

  function notificationRow(n: Notification) {
    return (
      <li
        key={n.id}
        className={`flex flex-col gap-1.5 rounded-md border px-3 py-2.5 ${
          n.read
            ? "border-border-soft bg-soft/40"
            : "border-accent-line bg-accent-soft/30"
        }`}
      >
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 shrink-0 text-faint" aria-hidden>
            {ICONS[n.event_type] ?? <Bell size={15} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <p className={`text-[13.5px] ${n.read ? "text-muted" : "font-medium text-text"}`}>
                {n.title}
              </p>
              {!n.read && <Badge tone="accent">Nueva</Badge>}
              {n.archived && <Badge tone="neutral">Archivada</Badge>}
            </div>
            {n.body && <p className="mt-1 text-[13px] leading-relaxed text-muted">{n.body}</p>}
            <p className="mt-1 text-[11px] text-faint" title={fmtDateTime(n.created_at)}>
              {timeAgo(n.created_at)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!n.read && (
              <Button
                variant="ghost"
                size="sm"
                leadingIcon={Check}
                onClick={() => void act(n.id, "read")}
              >
                Marcar leída
              </Button>
            )}
            {!n.archived && (
              <Button
                variant="ghost"
                size="sm"
                leadingIcon={Archive}
                onClick={() => void act(n.id, "archive")}
              >
                Archivar
              </Button>
            )}
          </div>
        </div>
      </li>
    );
  }

  return (
    <div>
      <PageHeader
        title="Notificaciones"
        subtitle={`${unread} sin leer · canales y alertas de la organización.`}
      />
      <ErrorInline message={error} />
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <section className="min-w-0">
            <Panel>
              <PanelHeader
                title="Centro"
                description={`${items.length} ${items.length === 1 ? "notificación" : "notificaciones"} en la vista actual.`}
                actions={
                  <>
                    <Checkbox
                      checked={unreadOnly}
                      onCheckedChange={setUnreadOnly}
                      label="Solo sin leer"
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      leadingIcon={Check}
                      disabled={unread === 0}
                      onClick={() => void readAll()}
                    >
                      Marcar todo leído
                    </Button>
                  </>
                }
              />
              <div className="flex flex-col gap-4 p-4">
                {items.length === 0 ? (
                  <EmptyState
                    icon={Bell}
                    title={unreadOnly ? "Nada sin leer" : "Sin notificaciones"}
                    body={
                      unreadOnly
                        ? "No quedan notificaciones pendientes. Desactivá el filtro para ver el historial."
                        : "Cuando ocurra algo relevante en tu organización, lo vas a ver acá."
                    }
                  />
                ) : (
                  <>
                    {unreadItems.length > 0 && (
                      <div>
                        <p className="eyebrow mb-2">Sin leer · {unreadItems.length}</p>
                        <ul className="flex flex-col gap-2">{unreadItems.map(notificationRow)}</ul>
                      </div>
                    )}
                    {readItems.length > 0 && (
                      <div>
                        <p className="eyebrow mb-2">Leídas · {readItems.length}</p>
                        <ul className="flex flex-col gap-2">{readItems.map(notificationRow)}</ul>
                      </div>
                    )}
                  </>
                )}
              </div>
            </Panel>
          </section>

          <aside className="lg:sticky lg:top-6">
            <Panel>
              <PanelHeader
                title="Preferencias por canal"
                actions={<SaveStatus state={prefsState} error={prefsError} />}
              />
              <div className="panel-body">
                <div className="flex flex-col gap-3">
                  {Object.entries(prefs.channels).map(([channel, enabled]) => (
                    <Switch
                      key={channel}
                      checked={enabled}
                      onCheckedChange={(checked) => toggleChannel(channel, checked)}
                      label={CHANNEL_LABELS[channel] ?? channel}
                    />
                  ))}
                </div>
                <Button
                  variant="primary"
                  className="mt-4"
                  loading={prefsState === "saving"}
                  disabled={prefsState !== "dirty" && prefsState !== "error"}
                  onClick={() => void savePrefs()}
                >
                  Guardar preferencias
                </Button>
              </div>
            </Panel>
          </aside>
        </div>
      )}
    </div>
  );
}
