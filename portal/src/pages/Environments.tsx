import { ArrowUpRight, CaretRight, Stack } from "@phosphor-icons/react";
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
  StatusBadge,
  type Column,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Slos = {
  status: string;
  windows?: {
    window: string;
    p95_latency_ms?: number;
    error_rate?: number;
    availability?: number;
  }[];
} | null;

type Environment = {
  id: string;
  name: string;
  slug: string;
  is_default: boolean;
  created_at: string;
  deployment: {
    id: string;
    status: string;
    slug: string;
    endpoint: string | null;
    deployed_at: string | null;
    version_number: number | null;
    agent_version_id: string | null;
    agent_name: string | null;
    traffic_pct: number;
    slos: Slos;
  } | null;
};

const ENV_TONE: Record<string, Tone> = {
  development: "neutral",
  staging: "warn",
  production: "ok",
};

function sloTone(status: string): Tone {
  if (status === "ok") return "ok";
  if (status === "degraded") return "warn";
  return "danger";
}

export default function EnvironmentsPage() {
  const { session } = useAuth();
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Environment | null>(null);

  useEffect(() => {
    if (!session) return;
    api<{ environments: Environment[] }>("/api/v1/environments", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setEnvs(d.environments || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const columns: Column<Environment>[] = [
    {
      key: "environment",
      header: "Entorno",
      render: (env) => (
        <div className="min-w-0">
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={ENV_TONE[env.slug] ?? "neutral"}>{env.name}</Badge>
            {env.is_default && <Badge tone="accent">Default</Badge>}
          </span>
          <p className="mono mt-1 text-[11px] text-faint">{env.slug}</p>
        </div>
      ),
    },
    {
      key: "version",
      header: "Versión",
      render: (env) => {
        const dep = env.deployment;
        if (!dep) return <span className="text-xs text-faint">Sin despliegue</span>;
        return (
          <span className="mono text-xs text-text">
            {dep.version_number != null
              ? `v${dep.version_number}`
              : dep.agent_version_id?.slice(0, 8) ?? "—"}
          </span>
        );
      },
    },
    {
      key: "agent",
      header: "Agente",
      hideBelow: "md",
      render: (env) => (
        <span className="text-[13px] text-text">{env.deployment?.agent_name || "—"}</span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (env) =>
        env.deployment ? <StatusBadge status={env.deployment.status} /> : <span className="text-xs text-faint">—</span>,
    },
    {
      key: "traffic",
      header: "Tráfico",
      align: "right",
      hideBelow: "lg",
      render: (env) => (
        <span className="mono text-xs text-muted">
          {env.deployment ? `${env.deployment.traffic_pct}%` : "—"}
        </span>
      ),
    },
    {
      key: "deployed_at",
      header: "Desplegado",
      hideBelow: "lg",
      render: (env) => (
        <span className="text-xs text-muted">
          {env.deployment?.deployed_at ? fmtDateTime(env.deployment.deployed_at) : "—"}
        </span>
      ),
    },
    {
      key: "slos",
      header: "Salud (SLO)",
      align: "right",
      hideBelow: "md",
      render: (env) =>
        env.deployment?.slos ? (
          <Badge tone={sloTone(env.deployment.slos.status)}>
            {env.deployment.slos.status}
          </Badge>
        ) : (
          <span className="text-xs text-faint">—</span>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Entornos"
        subtitle="Versión desplegada por entorno, salud y tráfico. Una versión es el snapshot congelado; un deployment es la ejecución de esa versión en un entorno."
      />
      <ErrorInline message={error} />
      <DataTable
        columns={columns}
        rows={envs}
        rowKey={(env) => env.id}
        caption="Entornos de la organización"
        loading={loading}
        empty={
          <EmptyState
            icon={Stack}
            title="Sin entornos"
            body="Tu organización todavía no tiene entornos configurados. Aparecerán acá cuando el backend los aprovisione."
          />
        }
        onRowClick={(env) => setSelected(env)}
        isRowSelected={(env) => selected?.id === env.id}
        rowActions={(env) => (
          <span className="flex items-center justify-end gap-1">
            <ButtonLink to="/deployments" variant="ghost" size="sm">
              Despliegues <CaretRight size={12} aria-hidden />
            </ButtonLink>
            <Button variant="ghost" size="sm" onClick={() => setSelected(env)}>
              Detalle
            </Button>
          </span>
        )}
      />

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.name ?? "Entorno"}
        description={selected?.slug}
        width={480}
        footer={
          selected?.deployment?.endpoint ? (
            <Link
              to={`/developers?deployment=${selected.deployment.slug}`}
              className="btn btn-secondary"
            >
              Consumir endpoint
              <ArrowUpRight size={14} aria-hidden />
            </Link>
          ) : undefined
        }
      >
        {selected && <EnvironmentDetail env={selected} />}
      </Drawer>
    </div>
  );
}

function EnvironmentDetail({ env }: { env: Environment }) {
  const dep = env.deployment;
  if (!dep) {
    return (
      <p className="text-[13px] text-muted">
        Sin despliegue en este entorno. Publicá una versión desde el builder de un agente.
      </p>
    );
  }
  return (
    <div className="space-y-5">
      <section>
        <p className="eyebrow mb-2">Deployment</p>
        <KeyValue
          columns={2}
          items={[
            { key: "Estado", value: <StatusBadge status={dep.status} /> },
            {
              key: "Versión",
              value:
                dep.version_number != null
                  ? `v${dep.version_number}`
                  : dep.agent_version_id?.slice(0, 8) ?? "—",
              mono: true,
            },
            { key: "Agente", value: dep.agent_name || "—" },
            { key: "Tráfico", value: `${dep.traffic_pct}%`, mono: true },
            {
              key: "Desplegado",
              value: dep.deployed_at ? fmtDateTime(dep.deployed_at) : "—",
            },
            { key: "Creado", value: fmtDateTime(env.created_at) },
          ]}
        />
      </section>

      {dep.endpoint && (
        <section>
          <p className="eyebrow mb-1.5">Endpoint</p>
          <p className="mono break-all rounded-sm border border-border bg-control px-3 py-2 text-xs text-text">
            {dep.endpoint}
          </p>
        </section>
      )}

      {dep.slos && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            <p className="eyebrow">Salud (SLO)</p>
            <Badge tone={sloTone(dep.slos.status)}>{dep.slos.status}</Badge>
          </div>
          {(dep.slos.windows ?? []).length === 0 ? (
            <p className="text-xs text-muted">Sin ventanas de medición reportadas.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <caption className="sr-only">Ventanas de SLO del deployment</caption>
                <thead>
                  <tr>
                    <th scope="col">Ventana</th>
                    <th scope="col" className="text-right">
                      p95
                    </th>
                    <th scope="col" className="text-right">
                      Error rate
                    </th>
                    <th scope="col" className="text-right">
                      Disponibilidad
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(dep.slos.windows ?? []).map((w) => (
                    <tr key={w.window}>
                      <td className="text-[13px] text-text">{w.window}</td>
                      <td className="mono text-right text-xs text-muted">
                        {w.p95_latency_ms != null ? `${w.p95_latency_ms} ms` : "—"}
                      </td>
                      <td className="mono text-right text-xs text-muted">
                        {w.error_rate != null ? `${w.error_rate}%` : "—"}
                      </td>
                      <td className="mono text-right text-xs text-muted">
                        {w.availability != null ? `${w.availability}%` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
