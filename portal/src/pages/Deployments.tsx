import {
  AppWindow,
  Globe,
  ListBullets,
  PlugsConnected,
  PuzzlePiece,
  RocketLaunch,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
  StatusBadge,
  type Column,
} from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type Deployment = {
  id: string;
  environment_id: string;
  agent_id: string;
  agent_version_id: string;
  slug: string;
  status: string;
  endpoint: string | null;
  deployed_by: string | null;
  deployed_at: string | null;
  rollback_from_id: string | null;
  created_at: string;
};

type ApiLog = {
  id: string;
  request_id: string;
  endpoint: string;
  status: number;
  latency_ms: number | null;
  tokens: number;
  created_at: string;
};

const TARGETS: { icon: typeof AppWindow; label: string; desc: string; ready: boolean; to?: string }[] = [
  {
    icon: Globe,
    label: "REST API",
    desc: "Consulta tus agentes desde cualquier sistema con una API pública.",
    ready: true,
    to: "/developers",
  },
  {
    icon: AppWindow,
    label: "Web Widget",
    desc: "Embeber tu asistente en sitios web y aplicaciones.",
    ready: false,
  },
  {
    icon: PuzzlePiece,
    label: "SDK",
    desc: "Integraciones en Python, JavaScript y otros lenguajes.",
    ready: true,
    to: "/developers/tools",
  },
  {
    icon: PlugsConnected,
    label: "Integración ERP",
    desc: "Conectores nativos para sistemas empresariales.",
    ready: false,
  },
  {
    icon: ListBullets,
    label: "MCP",
    desc: "Exponer tus agentes como herramientas para asistentes y agentes externos.",
    ready: false,
  },
];

export default function DeploymentsPage() {
  const { session } = useAuth();
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [logs, setLogs] = useState<ApiLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Deployment | null>(null);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [depData, logData] = await Promise.all([
          api<{ deployments: Deployment[] }>("/api/v1/deployments", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ deployments: [] as Deployment[] })),
          api<{ logs: ApiLog[] }>("/api/v1/deployments/logs", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ logs: [] as ApiLog[] })),
        ]);
        setDeployments(depData.deployments || []);
        setLogs(logData.logs || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando despliegues");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const columns: Column<Deployment>[] = [
    {
      key: "endpoint",
      header: "Endpoint",
      render: (d) => (
        <div className="min-w-0">
          <p className="mono truncate text-xs text-accent">{d.slug}</p>
          {d.endpoint && (
            <p className="mono mt-0.5 max-w-[48ch] truncate text-[11px] text-faint" title={d.endpoint}>
              {d.endpoint}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "environment",
      header: "Entorno",
      hideBelow: "md",
      render: (d) => (
        <span className="mono text-xs text-muted">
          {d.environment_id ? d.environment_id.slice(0, 8) : "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (d) => <StatusBadge status={d.status} />,
    },
    {
      key: "deployed_at",
      header: "Desplegado",
      hideBelow: "md",
      render: (d) => (
        <span className="text-xs text-muted">
          {d.deployed_at ? fmtDateTime(d.deployed_at) : fmtDateTime(d.created_at)}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Despliegues"
        subtitle="Despliega tus experiencias de IA en aplicaciones, APIs y sistemas empresariales."
        actions={
          <ButtonLink to="/developers" variant="secondary">
            Centro de desarrolladores
          </ButtonLink>
        }
      />
      <ErrorInline message={error} />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {TARGETS.map((t) => {
          const Content = (
            <>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-raised text-faint">
                <t.icon size={18} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[13.5px] font-medium text-text">{t.label}</p>
                  {!t.ready && <Badge tone="warn">Próximamente</Badge>}
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-muted">{t.desc}</p>
              </div>
            </>
          );
          return t.ready && t.to ? (
            <Link
              key={t.label}
              to={t.to}
              className="panel flex items-start gap-3 p-4 transition-colors duration-150 hover:border-border-strong"
            >
              {Content}
            </Link>
          ) : (
            <Panel key={t.label} className="flex items-start gap-3 p-4">
              {Content}
            </Panel>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <DataTable
            columns={columns}
            rows={deployments}
            rowKey={(d) => d.id}
            caption="Deployments"
            loading={loading}
            empty={
              <EmptyState
                icon={RocketLaunch}
                title="Sin deployments activos"
                body="Desplegá un agente desde su editor para obtener un endpoint público y comenzar a integrarlo."
                action={
                  <ButtonLink to="/agents" variant="primary">
                    Ir a Agentes
                  </ButtonLink>
                }
              />
            }
            onRowClick={(d) => setSelected(d)}
            isRowSelected={(d) => selected?.id === d.id}
            rowActions={(d) => (
              <Button variant="ghost" size="sm" onClick={() => setSelected(d)}>
                Detalle
              </Button>
            )}
          />
        </div>

        <Panel>
          <PanelHeader
            title="Tráfico reciente"
            description="Consultas registradas contra tus endpoints."
          />
          {loading ? (
            <div className="panel-body">
              <SkeletonBlock rows={5} />
            </div>
          ) : logs.length === 0 ? (
            <EmptyState
              icon={ListBullets}
              title="Sin llamadas"
              body="Las consultas a tus endpoints públicos aparecerán aquí."
            />
          ) : (
            <div className="divide-y divide-border-soft">
              {logs.slice(0, 8).map((l) => (
                <div key={l.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <div className="min-w-0">
                    <p className="mono truncate text-xs text-text">{l.request_id.slice(0, 8)}</p>
                    <p className="truncate text-[11px] text-faint">{l.endpoint}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-0.5">
                    <Badge tone={l.status === 200 ? "ok" : "danger"}>{l.status}</Badge>
                    <span className="mono text-[11px] text-faint">
                      {fmtLatency(l.latency_ms ?? 0)} · {fmtNum(l.tokens)} tok
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.slug ?? "Deployment"}
        description={selected?.deployed_at ? `Desplegado ${fmtDateTime(selected.deployed_at)}` : undefined}
        width={480}
      >
        {selected && (
          <div className="space-y-4">
            <StatusBadge status={selected.status} />
            <KeyValue
              columns={2}
              items={[
                { key: "Entorno", value: selected.environment_id || "—", mono: true },
                { key: "Agente", value: selected.agent_id, mono: true },
                { key: "Versión", value: selected.agent_version_id, mono: true },
                { key: "Desplegado por", value: selected.deployed_by || "—", mono: true },
                { key: "Rollback desde", value: selected.rollback_from_id || "—", mono: true },
                {
                  key: "Desplegado",
                  value: selected.deployed_at ? fmtDateTime(selected.deployed_at) : "—",
                },
                { key: "Creado", value: fmtDateTime(selected.created_at) },
              ]}
            />
            {selected.endpoint && (
              <div>
                <p className="eyebrow mb-1.5">Endpoint</p>
                <p className="mono break-all rounded-sm border border-border bg-control px-3 py-2 text-xs text-text">
                  {selected.endpoint}
                </p>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
