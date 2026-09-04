import { Key, LockKey, Scroll, ShieldWarning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoon } from "../components/ComingSoon";
import { PageTabs } from "../components/PageTabs";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type AuditEntry = {
  action: string;
  resource_type: string;
  resource_id: string | null;
  actor_user_id: string | null;
  ip_address: string | null;
  created_at: string;
};

type SecurityEvent = {
  id: string;
  event_type: string;
  severity: string;
  score: number;
  status: string;
  evidence: string | null;
  responses: number;
  detected_at: string;
  resolved_at: string | null;
};

const TABS = [
  { id: "audit", label: "Auditoría", icon: Scroll },
  { id: "events", label: "Eventos de seguridad", icon: ShieldWarning },
  { id: "auth", label: "Autenticación", icon: LockKey },
  { id: "api", label: "Actividad de API", icon: Key },
] as const;

type TabId = (typeof TABS)[number]["id"];

const SEVERITY_TONES: Record<string, string> = {
  critical: "badge-danger",
  high: "badge-danger",
  medium: "badge-pending",
  low: "badge-muted",
  info: "badge-muted",
};

export default function SecurityAuditPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("audit");
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loadingAudit, setLoadingAudit] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoadingAudit(true);
    api<{ entries: AuditEntry[] }>("/api/v1/audit-logs?limit=200", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setEntries(data.entries || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoadingAudit(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    setLoadingEvents(true);
    api<{ events: SecurityEvent[] }>("/api/v1/soc/events", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .catch(() => ({ events: [] as SecurityEvent[] }))
      .then((data) => setEvents(data.events || []))
      .finally(() => setLoadingEvents(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Seguridad y Auditoría"
        subtitle="Revisa la actividad sensible de tu workspace y los eventos de seguridad detectados por la plataforma."
      />
      <PageTabs tabs={TABS} active={tab} onChange={(id) => setTab(id as TabId)} idPrefix="sec" />
      <ErrorInline message={error} />

      {tab === "audit" && (
        <div className="panel mt-4">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <Scroll size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Eventos auditados ({entries.length})</h2>
          </div>
          {loadingAudit ? (
            <div className="p-5">
              <SkeletonBlock rows={6} />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState
              icon={Scroll}
              title="Sin eventos"
              body="Aún no hay acciones auditadas para esta organización."
            />
          ) : (
            <div className="divide-y divide-border">
              {entries.map((e, i) => (
                <div key={`${e.action}-${e.created_at}-${i}`} className="flex flex-col gap-1 px-5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="badge badge-pending">{e.action}</span>
                    <span className="text-xs text-faint">
                      {e.resource_type}
                      {e.resource_id ? ` · ${e.resource_id.slice(0, 12)}…` : ""}
                    </span>
                    <span className="ml-auto text-xs text-faint">{fmtDateTime(e.created_at)}</span>
                  </div>
                  {(e.ip_address || e.actor_user_id) && (
                    <span className="mono text-xs text-faint">
                      actor={e.actor_user_id?.slice(0, 8) ?? "system"} ip={e.ip_address ?? "—"}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "events" && (
        <div className="panel mt-4">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <ShieldWarning size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Eventos de seguridad ({events.length})</h2>
          </div>
          {loadingEvents ? (
            <div className="p-5">
              <SkeletonBlock rows={6} />
            </div>
          ) : events.length === 0 ? (
            <EmptyState
              icon={ShieldWarning}
              title="Sin eventos de seguridad"
              body="La plataforma monitorea actividad sospechosa y responderá aquí cuando la detecte."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table min-w-[680px]">
                <thead>
                  <tr>
                    <th>Evento</th>
                    <th>Severidad</th>
                    <th>Score</th>
                    <th>Estado</th>
                    <th>Detectado</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <tr key={ev.id}>
                      <td className="mono text-xs text-text">{ev.event_type}</td>
                      <td>
                        <span className={`badge ${SEVERITY_TONES[ev.severity] || "badge-muted"}`}>
                          {ev.severity}
                        </span>
                      </td>
                      <td className="mono text-xs">{Math.round(ev.score)}</td>
                      <td>
                        <span className="badge badge-muted">{ev.status}</span>
                      </td>
                      <td className="text-xs text-faint">{fmtDateTime(ev.detected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "auth" && (
        <div className="mt-4">
          <ComingSoon>
            Configuración de autenticación (SSO, contraseñas y sesiones) disponible en una próxima
            fase.
          </ComingSoon>
        </div>
      )}

      {tab === "api" && (
        <div className="mt-4">
          <ComingSoon>
            <Link to="/keys" className="text-accent underline underline-offset-2">
              Administra tus credenciales en API y Claves.
            </Link>{" "}
            El registro detallado de actividad por clave llegará en una próxima fase.
          </ComingSoon>
        </div>
      )}
    </div>
  );
}