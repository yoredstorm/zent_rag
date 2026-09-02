import { Scroll } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { EmptyState, ErrorInline, PageHeader, RecentActivity, SkeletonBlock } from "../../components/ui";

type Entry = {
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  created_at: string | null;
  metadata: Record<string, unknown>;
};

export default function Audit() {
  const { session } = usePlatformAuth();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!session) return;
    platformApi<{ entries: Entry[] }>(
      `/api/v1/platform/audit${filter ? `?action=${encodeURIComponent(filter)}` : ""}`,
      { token: session.token }
    )
      .then((d) => setEntries(d.entries || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session, filter]);

  return (
    <div>
      <PageHeader
        title="Audit"
        subtitle="Registro global de acciones de plataforma y tenant."
        actions={
          <input
            className="input min-w-52"
            placeholder="Filtrar por acción (ej. auth.login)"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : entries.length === 0 ? (
        <div className="panel">
          <EmptyState icon={Scroll} title="Sin eventos" body="No hay eventos de auditoría." />
        </div>
      ) : (
        <div className="panel">
          <RecentActivity items={entries} />
        </div>
      )}
    </div>
  );
}