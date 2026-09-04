import {
  CloudArrowUp,
  Database,
  FolderSimple,
  Globe,
  Plugs,
  WebhooksLogo,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoonBadge } from "../components/ComingSoon";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatusBadge,
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

export default function DataSourcesPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [connectors, setConnectors] = useState<ConnectorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

const countBy = (types: string[]) =>
  sources.filter((s) => types.includes(s.type)).length;

  const cards: {
    icon: typeof Database;
    label: string;
    desc: string;
    count: number;
    to: string;
    types: string[];
  }[] = [
    {
      icon: Database,
      label: "Base de datos",
      desc: "Sincroniza tablas SQL y las convierte en conocimiento vectorial.",
      count: countBy(["sql"]),
      to: "/knowledge/sql",
      types: ["sql"],
    },
    {
      icon: CloudArrowUp,
      label: "Subida de archivos",
      desc: "Documentos, CSV y Excel con análisis de perfil y PII.",
      count: countBy(FILE_TYPES),
      to: "/knowledge/sources",
      types: FILE_TYPES,
    },
    {
      icon: Globe,
      label: "Sitios web",
      desc: "Ingesta de contenido web para que tus agentes lo consulten.",
      count: countBy(["web"]),
      to: "/knowledge/sources",
      types: ["web"],
    },
    {
      icon: Plugs,
      label: "API REST",
      desc: "Conecta sistemas vía API para retrieval estructurado.",
      count: countBy(["api"]),
      to: "/knowledge/sources",
      types: ["api"],
    },
  ];

  const upcoming = [
    { label: "Salesforce", desc: "Sincroniza oportunidades, cuentas y casos." },
    { label: "Notion", desc: "Docs y bases de conocimiento de tu equipo." },
    { label: "ERP / SAP", desc: "Datos maestros y operaciones de negocio." },
  ];

  return (
    <div>
      <PageHeader
        title="Fuentes de datos"
        subtitle="Conecta sistemas de negocio y datos estructurados a Zent para que tus agentes respondan con información de la empresa."
        actions={
          <Link to="/connectors" className="btn btn-secondary">
            Ver conectores
          </Link>
        }
      />
      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="panel space-y-3 p-4">
              <SkeletonBlock rows={2} />
            </div>
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

          <div className="mt-6 grid gap-4 xl:grid-cols-3">
            <div className="panel xl:col-span-2">
              <div className="flex items-center gap-2 border-b border-border px-5 py-4">
                <FolderSimple size={16} className="text-accent" aria-hidden />
                <h2 className="text-sm font-semibold text-text">Fuentes conectadas ({sources.length})</h2>
              </div>
              {sources.length === 0 ? (
                <EmptyState
                  icon={FolderSimple}
                  title="Sin fuentes de datos"
                  body="Conecta documentos, bases de datos o sitios web para que tus agentes respondan con información de la empresa."
                  action={
                    <Link to="/knowledge/sources" className="btn btn-primary">
                      Añadir fuente
                    </Link>
                  }
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table min-w-[640px]">
                    <thead>
                      <tr>
                        <th>Fuente</th>
                        <th>Tipo</th>
                        <th>Estado</th>
                        <th>Elementos</th>
                        <th>Última sync</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((s) => (
                        <tr key={s.id}>
                          <td className="font-medium text-text">{s.name}</td>
                          <td className="mono text-xs text-muted">{s.type}</td>
                          <td>
                            <StatusBadge status={s.status} />
                            {s.last_error && (
                              <span className="block text-[11px] text-danger">{s.last_error}</span>
                            )}
                          </td>
                          <td className="mono text-xs">{fmtNum(s.document_count)}</td>
                          <td className="text-xs text-faint">
                            {s.last_sync ? new Date(s.last_sync).toLocaleString("es-PE") : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="flex items-center gap-2 border-b border-border px-5 py-4">
                <WebhooksLogo size={16} className="text-accent" aria-hidden />
                <h2 className="text-sm font-semibold text-text">Conectores enterprise</h2>
              </div>
              <div className="flex flex-col gap-2 p-4">
                {connectors.map((c) => (
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
                {upcoming.map((u) => (
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
            </div>
          </div>
        </>
      )}
    </div>
  );
}