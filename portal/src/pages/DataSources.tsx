import {
  CloudArrowUp,
  Database,
  FolderSimple,
  Globe,
  MagnifyingGlass,
  Plugs,
  WebhooksLogo,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoonBadge } from "../components/ComingSoon";
import {
  Button,
  ButtonLink,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Input,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  SkeletonBlock,
  StatusBadge,
  Toolbar,
  type Column,
} from "../components/ui";
import { fmtNum } from "../lib/format";

type SourceRow = {
  id: string;
  name: string;
  type: string;
  status: string;
  last_sync: string | null;
  last_error: string | null;
  document_count: number;
  error_count: number;
};

type ConnectorRow = {
  id: string;
  name: string;
  connector_type: string;
  status: string;
  created_at: string;
};

const FILE_TYPES = ["file", "csv", "excel"];

const SOURCE_COLUMNS: Column<SourceRow>[] = [
  {
    key: "name",
    header: "Fuente",
    render: (s) => <span className="text-[13px] font-medium text-text">{s.name}</span>,
  },
  {
    key: "type",
    header: "Tipo",
    width: "1%",
    render: (s) => <span className="mono text-xs text-muted">{s.type}</span>,
  },
  {
    key: "status",
    header: "Estado",
    render: (s) => (
      <span className="flex flex-col items-start gap-1">
        <StatusBadge status={s.status} />
        {s.last_error && (
          <span className="block max-w-[26rem] text-[11px] leading-relaxed text-danger">{s.last_error}</span>
        )}
      </span>
    ),
  },
  {
    key: "documents",
    header: "Elementos",
    align: "right",
    render: (s) => <span className="mono text-xs text-text">{fmtNum(s.document_count)}</span>,
  },
  {
    key: "errors",
    header: "Errores",
    align: "right",
    hideBelow: "md",
    render: (s) =>
      s.error_count > 0 ? (
        <span className="mono text-xs text-danger">{fmtNum(s.error_count)}</span>
      ) : (
        <span className="mono text-xs text-muted">0</span>
      ),
  },
  {
    key: "sync",
    header: "Última sync",
    hideBelow: "md",
    render: (s) => (
      <span className="text-xs text-faint">
        {s.last_sync ? new Date(s.last_sync).toLocaleString("es-PE") : "—"}
      </span>
    ),
  },
];

const UPCOMING = [
  { label: "Salesforce", desc: "Sincroniza oportunidades, cuentas y casos." },
  { label: "Notion", desc: "Docs y bases de conocimiento de tu equipo." },
  { label: "ERP / SAP", desc: "Datos maestros y operaciones de negocio." },
];

export default function DataSourcesPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [connectors, setConnectors] = useState<ConnectorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<SourceRow | null>(null);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [srcData, connData] = await Promise.all([
          api<{ sources: SourceRow[] }>("/api/v1/sources", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ sources: [] as SourceRow[] })),
          api<{ connectors: ConnectorRow[] }>("/api/v1/connectors", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ connectors: [] as ConnectorRow[] })),
        ]);
        setSources(srcData.sources || []);
        setConnectors(connData.connectors || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const countBy = (types: string[]) => sources.filter((s) => types.includes(s.type)).length;

  const cards: {
    icon: typeof Database;
    label: string;
    desc: string;
    count: number;
    to: string;
  }[] = [
    {
      icon: Database,
      label: "Base de datos",
      desc: "Conecta tu ERP o base empresarial. Zent entiende tablas y te ayuda a preguntar.",
      count: connectors.filter((c) =>
        ["postgres", "mysql", "mssql", "oracle", "db2"].includes(c.connector_type)
      ).length,
      to: "/knowledge/add",
    },
    {
      icon: CloudArrowUp,
      label: "Subida de archivos",
      desc: "Documentos, CSV y Excel.",
      count: countBy(FILE_TYPES),
      to: "/knowledge/add",
    },
    {
      icon: Globe,
      label: "Sitios web",
      desc: "Una URL para que Zent lea el contenido de tu sitio.",
      count: countBy(["web"]),
      to: "/knowledge/add",
    },
    {
      icon: Plugs,
      label: "API REST",
      desc: "Conecta sistemas vía API.",
      count: countBy(["api"]),
      to: "/knowledge/add",
    },
  ];

  const term = search.trim().toLowerCase();
  const filteredSources = useMemo(() => {
    if (!term) return sources;
    return sources.filter(
      (s) => s.name.toLowerCase().includes(term) || s.type.toLowerCase().includes(term)
    );
  }, [sources, term]);

  const filteredConnectors = useMemo(() => {
    if (!term) return connectors;
    return connectors.filter(
      (c) => c.name.toLowerCase().includes(term) || c.connector_type.toLowerCase().includes(term)
    );
  }, [connectors, term]);

  return (
    <div>
      <PageHeader
        title="Fuentes de datos"
        subtitle="Conecta sistemas de negocio y datos estructurados a Zent para que tus agentes respondan con información de la empresa."
        actions={
          <ButtonLink to="/knowledge/add" variant="primary">
            Añade conocimiento a Zent
          </ButtonLink>
        }
      />
      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Panel key={i} className="p-4">
              <SkeletonBlock rows={2} />
            </Panel>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map((card) => (
              <Link
                key={card.label}
                to={card.to}
                className="panel group flex flex-col gap-3 p-4 transition-colors duration-150 hover:border-border-strong"
              >
                <div className="flex items-center justify-between">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-soft text-accent">
                    <card.icon size={18} aria-hidden />
                  </span>
                  <span className="mono text-lg font-semibold text-text">{fmtNum(card.count)}</span>
                </div>
                <div>
                  <p className="text-sm font-medium text-text">{card.label}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{card.desc}</p>
                </div>
              </Link>
            ))}
          </div>

          <Toolbar className="mt-6 mb-3">
            <Input
              icon={MagnifyingGlass}
              className="w-full sm:max-w-72"
              placeholder="Buscar fuente o conector…"
              aria-label="Buscar fuente o conector"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <ResultCount
              shown={filteredSources.length + filteredConnectors.length}
              total={sources.length + connectors.length}
              noun="elementos"
            />
          </Toolbar>

          <div className="grid gap-4 xl:grid-cols-3">
            <div className="min-w-0 xl:col-span-2">
              <DataTable
                caption="Fuentes de datos conectadas"
                columns={SOURCE_COLUMNS}
                rows={filteredSources}
                rowKey={(s) => s.id}
                rowActions={(s) => (
                  <Button variant="ghost" size="sm" onClick={() => setDetail(s)}>
                    Detalle
                  </Button>
                )}
                empty={
                  sources.length === 0 ? (
                    <EmptyState
                      icon={FolderSimple}
                      title="Sin fuentes de datos"
                      body="Conecta documentos, bases de datos o sitios web para que tus agentes respondan con información de la empresa."
                      action={
                        <ButtonLink to="/knowledge/add" variant="primary">
                          Añadir fuente
                        </ButtonLink>
                      }
                    />
                  ) : (
                    <EmptyState
                      compact
                      icon={MagnifyingGlass}
                      title="Sin resultados"
                      body="Ninguna fuente coincide con la búsqueda."
                    />
                  )
                }
              />
            </div>

            <Panel className="min-w-0 self-start">
              <PanelHeader
                title="Conectores enterprise"
                description="Integraciones nativas en preparación."
              />
              <div className="flex flex-col gap-2 p-4">
                {filteredConnectors.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border bg-soft px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-text">{c.name}</p>
                      <p className="mono text-[11px] text-faint">{c.connector_type}</p>
                    </div>
                    <StatusBadge status={c.status} />
                  </div>
                ))}
                {filteredConnectors.length === 0 && (
                  <EmptyState
                    compact
                    icon={WebhooksLogo}
                    title={connectors.length === 0 ? "Sin conectores enterprise" : "Sin resultados"}
                    body={
                      connectors.length === 0
                        ? "Los conectores nativos se administran en Conectores."
                        : "Ningún conector coincide con la búsqueda."
                    }
                    action={
                      connectors.length === 0 ? (
                        <ButtonLink to="/connectors" variant="secondary" size="sm">
                          Ir a Conectores
                        </ButtonLink>
                      ) : undefined
                    }
                  />
                )}
                {UPCOMING.map((u) => (
                  <div
                    key={u.label}
                    className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] text-muted">{u.label}</p>
                      <p className="text-[11px] text-faint">{u.desc}</p>
                    </div>
                    <ComingSoonBadge />
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </>
      )}

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.name ?? "Fuente de datos"}
        description={detail ? `Tipo ${detail.type}` : undefined}
        width={480}
      >
        {detail && (
          <div className="flex flex-col gap-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Estado", value: <StatusBadge status={detail.status} /> },
                { key: "Tipo", value: detail.type, mono: true },
                { key: "Elementos", value: fmtNum(detail.document_count) },
                { key: "Errores", value: fmtNum(detail.error_count) },
                {
                  key: "Última sync",
                  value: detail.last_sync
                    ? new Date(detail.last_sync).toLocaleString("es-PE")
                    : "Sin sincronizar",
                },
              ]}
            />
            {detail.last_error && (
              <div>
                <p className="eyebrow mb-2">Último error</p>
                <p className="rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-[13px] leading-relaxed text-danger">
                  {detail.last_error}
                </p>
              </div>
            )}
            <p className="text-xs leading-relaxed text-faint">
              El detalle viene de la última sincronización registrada por el backend.
            </p>
          </div>
        )}
      </Drawer>
    </div>
  );
}
