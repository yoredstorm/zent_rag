import { Robot, Storefront, TrendUp } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  SectionHeader,
  Skeleton,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type AssistantRow = { key: string; events: number };
type IntentRow = { intent: string; messages: number };
type InstallRow = { name: string; slug: string; active: number };
type Dash = { sessions: number; organizations_using: number; top_assistants: AssistantRow[]; intents: IntentRow[]; installs: InstallRow[] };

function sortRows<T>(rows: T[], sort: SortState, get: (row: T, key: string) => string | number) {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const left = get(a, sort.key);
    const right = get(b, sort.key);
    if (typeof left === "string" && typeof right === "string") {
      return sort.dir === "asc" ? left.localeCompare(right) : right.localeCompare(left);
    }
    return sort.dir === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
  });
}

export default function AdminCopilotPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortAssistants, setSortAssistants] = useState<SortState>({ key: "events", dir: "desc" });
  const [sortIntents, setSortIntents] = useState<SortState>({ key: "messages", dir: "desc" });
  const [sortInstalls, setSortInstalls] = useState<SortState>({ key: "active", dir: "desc" });

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/copilot/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const assistants = useMemo(
    () => sortRows(dash?.top_assistants ?? [], sortAssistants, (row, key) => (key === "key" ? row.key : row.events)),
    [dash?.top_assistants, sortAssistants]
  );
  const intents = useMemo(
    () => sortRows(dash?.intents ?? [], sortIntents, (row, key) => (key === "intent" ? row.intent : row.messages)),
    [dash?.intents, sortIntents]
  );
  const installs = useMemo(
    () => sortRows(dash?.installs ?? [], sortInstalls, (row, key) => (key === "name" ? row.name : row.active)),
    [dash?.installs, sortInstalls]
  );

  const activeInstalls = (dash?.installs ?? []).reduce((n, i) => n + i.active, 0);

  const assistantColumns: Column<AssistantRow>[] = [
    {
      key: "key",
      header: "Asistente",
      sortable: true,
      render: (row) => (
        <span className="block max-w-[320px] truncate text-[13px] text-text" title={row.key}>
          {row.key}
        </span>
      ),
    },
    {
      key: "events",
      header: "Eventos",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.events)}</span>,
    },
  ];

  const intentColumns: Column<IntentRow>[] = [
    {
      key: "intent",
      header: "Intención",
      sortable: true,
      render: (row) => (
        <span className="block max-w-[320px] truncate text-[13px] text-text" title={row.intent}>
          {row.intent}
        </span>
      ),
    },
    {
      key: "messages",
      header: "Mensajes",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.messages)}</span>,
    },
  ];

  const installColumns: Column<InstallRow>[] = [
    {
      key: "name",
      header: "Instalación",
      sortable: true,
      render: (row) => (
        <span className="block max-w-[320px] truncate text-[13px] text-text" title={row.name}>
          {row.name}
        </span>
      ),
    },
    {
      key: "active",
      header: "Activas",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.active)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Copilot & Asistentes" subtitle="Uso del asistente, intenciones y adopción del marketplace en todas las organizaciones." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[240px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Sesiones de copilot"
              value={(dash?.sessions ?? 0).toLocaleString()}
              hint={`${(dash?.organizations_using ?? 0).toLocaleString()} organizaciones con uso`}
              icon={Robot}
            />
            <MetricGrid cols={3} className="lg:grid-cols-3">
              <Metric label="Organizaciones activas" value={(dash?.organizations_using ?? 0).toLocaleString()} size="md" />
              <Metric
                label="Instalaciones activas"
                value={activeInstalls.toLocaleString()}
                size="md"
                hint="Marketplace"
              />
              <Metric label="Intenciones detectadas" value={(dash?.intents ?? []).length.toLocaleString()} size="md" />
            </MetricGrid>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="min-w-0">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <TrendUp size={15} aria-hidden /> Top asistentes
                  </span>
                }
                description="Eventos registrados por asistente."
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={assistantColumns}
                rows={assistants}
                rowKey={(row) => row.key}
                sort={sortAssistants}
                onSortChange={setSortAssistants}
                empty={
                  <EmptyState compact icon={Robot} title="Sin eventos aún" body="El uso del copilot aparecerá acá cuando haya actividad." />
                }
              />

              <div className="mt-6">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <Storefront size={15} aria-hidden /> Marketplace
                    </span>
                  }
                  description="Instalaciones activas por producto."
                  className="mb-3"
                />
                <DataTable
                  stickyHeader
                  columns={installColumns}
                  rows={installs}
                  rowKey={(row) => row.slug}
                  sort={sortInstalls}
                  onSortChange={setSortInstalls}
                  empty={
                    <EmptyState compact icon={Storefront} title="Sin instalaciones" body="Los productos instalados por las organizaciones se listan acá." />
                  }
                />
              </div>
            </section>

            <section className="min-w-0">
              <SectionHeader
                title="Intenciones por mensaje"
                description="Clasificación de los mensajes del asistente."
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={intentColumns}
                rows={intents}
                rowKey={(row) => row.intent}
                sort={sortIntents}
                onSortChange={setSortIntents}
                empty={
                  <EmptyState compact icon={TrendUp} title="Sin intenciones aún" body="Se clasifican cuando hay mensajes procesados." />
                }
              />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
