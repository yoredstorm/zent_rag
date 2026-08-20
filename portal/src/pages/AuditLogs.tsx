import { Scroll } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
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
  metadata: Record<string, unknown>;
  created_at: string;
};

export default function AuditLogsPage() {
  const { session } = useAuth();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<{ entries: AuditEntry[] }>("/api/v1/audit-logs?limit=200", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setEntries(data.entries))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Auditoría"
        subtitle="Registro inmutable de acciones sensibles de tu organización. Solo ves tu propia actividad."
      />
      <ErrorInline message={error} />

      <div className="panel">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <Scroll size={16} className="text-accent" aria-hidden />
          <h2 className="text-sm font-semibold text-text">
            Eventos ({entries.length})
          </h2>
        </div>
        {loading ? (
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
                  <span className="ml-auto text-xs text-faint">
                    {fmtDateTime(e.created_at)}
                  </span>
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
    </div>
  );
}
