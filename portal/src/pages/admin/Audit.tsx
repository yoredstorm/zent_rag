import { MagnifyingGlass, Scroll } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Input,
  KeyValue,
  PageHeader,
  ResultCount,
  SkeletonBlock,
  type Column,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Entry = {
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  created_at: string | null;
  metadata: Record<string, unknown>;
};

const ENTRY_COLUMNS: Column<Entry>[] = [
  {
    key: "created_at",
    header: "Fecha",
    width: "150px",
    render: (e) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(e.created_at)}</span>,
  },
  {
    key: "action",
    header: "Acción",
    render: (e) => <span className="mono text-xs text-text">{e.action}</span>,
  },
  {
    key: "resource",
    header: "Recurso",
    render: (e) => (
      <span className="text-xs text-muted">
        <span className="text-text">{e.resource_type}</span>
        {e.resource_id ? <span className="mono text-faint"> · {e.resource_id.slice(0, 12)}</span> : null}
      </span>
    ),
  },
  {
    key: "actor",
    header: "Actor",
    hideBelow: "md",
    render: (e) =>
      e.actor_user_id ? (
        <span className="mono text-xs text-muted" title={e.actor_user_id}>
          {e.actor_user_id.slice(0, 12)}
        </span>
      ) : (
        <span className="text-xs text-faint">Sistema</span>
      ),
  },
  {
    key: "organization_id",
    header: "Org",
    hideBelow: "lg",
    render: (e) =>
      e.organization_id ? (
        <span className="mono text-xs text-muted" title={e.organization_id}>
          {e.organization_id.slice(0, 8)}
        </span>
      ) : (
        <span className="text-xs text-faint">platform</span>
      ),
  },
  {
    key: "metadata",
    header: "Metadata",
    align: "right",
    hideBelow: "md",
    render: (e) => (
      <span className="mono text-xs text-faint tabular-nums">
        {Object.keys(e.metadata ?? {}).length} claves
      </span>
    ),
  },
];

export default function Audit() {
  const { session } = usePlatformAuth();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Entry | null>(null);

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
    <div className="space-y-4">
      <PageHeader
        title="Audit"
        subtitle="Registro global de acciones de plataforma y tenant."
        actions={
          <Input
            icon={MagnifyingGlass}
            className="min-w-56"
            placeholder="Filtrar por acción (ej. auth.login)"
            aria-label="Filtrar por acción"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={8} />
      ) : (
        <>
          <DataTable
            columns={ENTRY_COLUMNS}
            rows={entries}
            rowKey={(e) => `${e.created_at ?? ""}-${e.action}-${e.resource_id ?? ""}-${e.actor_user_id ?? ""}`}
            caption="Eventos de auditoría"
            stickyHeader
            onRowClick={(e) => setSelected(e)}
            empty={
              <EmptyState
                icon={Scroll}
                title="Sin eventos"
                body={filter ? "Ningún evento coincide con el filtro de acción." : "No hay eventos de auditoría."}
                hint={filter ? "Probá con otra acción o limpiá el filtro." : undefined}
              />
            }
            footer={entries.length > 0 ? <ResultCount shown={entries.length} total={entries.length} noun="eventos" /> : undefined}
          />
          {entries.length > 0 && (
            <p className="text-xs text-faint">Seleccioná una fila para inspeccionar su metadata.</p>
          )}
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Evento de auditoría"
        description={selected?.action}
        width={520}
      >
        {selected && (
          <div className="space-y-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Fecha", value: fmtDateTime(selected.created_at) },
                { key: "Recurso", value: `${selected.resource_type}${selected.resource_id ? ` · ${selected.resource_id}` : ""}`, mono: true },
                { key: "Actor", value: selected.actor_user_id ?? "Sistema", mono: Boolean(selected.actor_user_id) },
                { key: "Organización", value: selected.organization_id ?? "platform", mono: true },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Metadata</p>
              {Object.keys(selected.metadata ?? {}).length === 0 ? (
                <p className="text-[13px] text-muted">El evento no registró metadata adicional.</p>
              ) : (
                <CodeBlock
                  code={JSON.stringify(selected.metadata, null, 2)}
                  language="json"
                  maxHeight={320}
                />
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
